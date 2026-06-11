# openweather_client.py
# -*- coding: utf-8 -*-

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Optional, Dict, List, Tuple
import datetime as dt
from zoneinfo import ZoneInfo

_TZ_BRASILIA = ZoneInfo("America/Sao_Paulo")

WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY") or os.getenv("WEATHER_API_KEY")
DEFAULT_CITY = os.getenv("WEATHER_DEFAULT_CITY", "Sao Jose dos Campos")


def _require_api_key() -> str:
    if not WEATHER_API_KEY:
        raise RuntimeError("Configure OPENWEATHER_API_KEY no ambiente antes de consultar o OpenWeather.")
    return WEATHER_API_KEY


def _build_url(city: str) -> str:
    params = {
        "q": city,
        "appid": _require_api_key(),
        "lang": "pt",
        "units": "metric",
    }
    return "http://api.openweathermap.org/data/2.5/weather?" + urllib.parse.urlencode(params)


def _build_forecast_url(city: str) -> str:
    params = {
        "q": city,
        "appid": _require_api_key(),
        "lang": "pt",
        "units": "metric",
    }
    return "http://api.openweathermap.org/data/2.5/forecast?" + urllib.parse.urlencode(params)


def fetch_current_weather(city: Optional[str] = None, timeout_s: int = 8) -> Dict:
    """
    Busca o clima atual no OpenWeatherMap. Retorna o JSON ja parseado.
    Lanca excecao se houver erro de rede ou resposta invalida.
    """
    city = (city or DEFAULT_CITY).strip()
    url = _build_url(city)
    req = urllib.request.Request(url, headers={"User-Agent": "orchestrator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def fetch_forecast(city: Optional[str] = None, timeout_s: int = 8) -> Dict:
    """
    Busca previsao 5 dias/3h no OpenWeatherMap. Retorna o JSON ja parseado.
    """
    city = (city or DEFAULT_CITY).strip()
    url = _build_forecast_url(city)
    req = urllib.request.Request(url, headers={"User-Agent": "orchestrator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def format_weather_pt(data: Dict) -> str:
    """
    Formata uma frase curta em PT-BR com dados do OpenWeatherMap.
    """
    name = data.get("name") or DEFAULT_CITY
    main = data.get("main", {})
    weather = (data.get("weather") or [{}])[0]
    desc = weather.get("description", "condicao desconhecida")
    temp = main.get("temp")
    feels = main.get("feels_like")

    parts = ["Agora em " + name + ": " + desc]
    if temp is not None:
        parts.append(str(round(temp)) + "C")
    if feels is not None:
        parts.append("sensacao " + str(round(feels)) + "C")
    return " - ".join(parts) + "."


def _group_by_date(items: List[Dict]) -> Dict[str, List[Dict]]:
    """Agrupa slots de previsao por data no fuso de Brasilia (UTC-3).
    O campo dt_txt da API OpenWeather esta em UTC — convertemos para
    America/Sao_Paulo antes de extrair a data, garantindo que meia-noite
    UTC (21h Brasilia) seja tratada como o mesmo dia local.
    """
    by_date: Dict[str, List[Dict]] = {}
    for it in items:
        dt_txt = it.get("dt_txt")
        if not dt_txt:
            continue
        # Converte UTC -> Brasilia para obter a data local correta
        try:
            utc_dt = dt.datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=dt.timezone.utc
            )
            local_dt = utc_dt.astimezone(_TZ_BRASILIA)
            date_str = local_dt.date().isoformat()
        except Exception:
            date_str = dt_txt.split(" ")[0]  # fallback seguro
        by_date.setdefault(date_str, []).append(it)
    return by_date


def _choose_date_from_query(query: str, available_dates: List[str]) -> Optional[str]:
    q = (query or "").lower()
    if not available_dates:
        return None

    # Usa horario de Brasilia (UTC-3) para calcular "hoje" e "amanha" corretamente
    today = dt.datetime.now(tz=_TZ_BRASILIA).date()
    available_set = set(available_dates)

    today_str    = today.isoformat()
    tomorrow_str = (today + dt.timedelta(days=1)).isoformat()
    day2_str     = (today + dt.timedelta(days=2)).isoformat()

    if "depois de amanh" in q:
        target = day2_str if day2_str in available_set else (available_dates[2] if len(available_dates) >= 3 else None)
        return target
    if "amanh" in q:
        target = tomorrow_str if tomorrow_str in available_set else (available_dates[1] if len(available_dates) >= 2 else None)
        return target
    if "hoje" in q:
        target = today_str if today_str in available_set else available_dates[0]
        return target

    # dd/mm ou dd-mm (assume ano atual)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", q)
    if m:
        d = int(m.group(1))
        mth = int(m.group(2))
        try:
            target = dt.date(today.year, mth, d).isoformat()
            if target in available_set:
                return target
        except Exception:
            pass

    # dia do mes (ex: dia 15)
    m = re.search(r"\bdia\s+(\d{1,2})\b", q)
    if m:
        d = int(m.group(1))
        try:
            target = dt.date(today.year, today.month, d).isoformat()
            if target in available_set:
                return target
        except Exception:
            pass

    # dia da semana
    weekday_map = {
        "segunda": 0,
        "terca": 1,
        "quarta": 2,
        "quinta": 3,
        "sexta": 4,
        "sabado": 5,
        "domingo": 6,
    }
    for wname, wd in weekday_map.items():
        if re.search(r"\b" + wname + r"\b", q):
            delta = (wd - today.weekday()) % 7
            target_date = today + dt.timedelta(days=delta if delta else 7)
            target = target_date.isoformat()
            if target in available_set:
                return target

    return None


def _summarize_day(items: List[Dict]) -> Tuple[Optional[float], Optional[float], str, Optional[float], Optional[float]]:
    """Sumariza um dia de previsao.

    Retorna: (tmin, tmax, desc_dominante, pop_max, rain_mm_total)
    - pop_max: maior probabilidade de precipitacao do dia (0.0 a 1.0)
    - rain_mm_total: soma de rain['3h'] de todos os slots do dia (mm)
    """
    temps = []
    descs = []
    pops = []
    rain_mms = []
    for it in items:
        main = it.get("main", {})
        if "temp" in main:
            temps.append(float(main["temp"]))
        weather = (it.get("weather") or [{}])[0]
        desc = weather.get("description")
        if desc:
            descs.append(desc)
        # pop = probability of precipitation (0..1)
        if "pop" in it:
            try:
                pops.append(float(it["pop"]))
            except (TypeError, ValueError):
                pass
        # rain volume acumulado nos slots de 3h
        rain_block = it.get("rain") or {}
        rain_3h = rain_block.get("3h") or rain_block.get("1h")
        if rain_3h is not None:
            try:
                rain_mms.append(float(rain_3h))
            except (TypeError, ValueError):
                pass
    tmin = min(temps) if temps else None
    tmax = max(temps) if temps else None
    desc = max(set(descs), key=descs.count) if descs else "condicao desconhecida"
    pop_max = max(pops) if pops else None
    rain_mm_total = sum(rain_mms) if rain_mms else None
    return tmin, tmax, desc, pop_max, rain_mm_total


def _weekday_pt(d: dt.date) -> str:
    names = ["segunda-feira", "terca-feira", "quarta-feira", "quinta-feira",
             "sexta-feira", "sabado", "domingo"]
    return names[d.weekday()]


def format_forecast_pt(query: str, data: Dict) -> str:
    """
    Formata previsao para hoje/amanha com base no texto da pergunta.
    """
    city = (data.get("city") or {}).get("name") or DEFAULT_CITY
    items = data.get("list") or []
    if not items:
        return "Previsao indisponivel para " + city + "."

    by_date = _group_by_date(items)
    dates = sorted(by_date.keys())
    target = _choose_date_from_query(query, dates)
    if not target:
        q = (query or "").lower()
        if "fim de semana" in q or "final de semana" in q:
            return "Previsao de fim de semana indisponivel nos proximos 5 dias para " + city + "."
        target = dates[0] if dates else None
    if not target:
        return "Previsao indisponivel para " + city + "."

    tmin, tmax, desc, pop_max, rain_mm_total = _summarize_day(by_date[target])

    try:
        target_date = dt.date.fromisoformat(target)
        day_label = _weekday_pt(target_date) + " (" + target_date.strftime("%d/%m") + ")"
    except Exception:
        day_label = "amanha" if "amanh" in (query or "").lower() else "hoje"

    # Monta partes da resposta
    parts = ["Previsao para " + day_label + " em " + city + ": " + desc]
    if tmin is not None and tmax is not None:
        parts.append("minima " + str(round(tmin)) + "C e maxima " + str(round(tmax)) + "C")
    # Probabilidade de precipitacao (pop) - exibida quando >= 10%
    if pop_max is not None and pop_max >= 0.10:
        parts.append("chance de chuva " + str(round(pop_max * 100)) + "%")
    # Volume acumulado de chuva - exibido quando ha registro real
    if rain_mm_total is not None and rain_mm_total > 0.0:
        parts.append("precipitacao estimada " + str(round(rain_mm_total, 1)) + " mm")
    return ", ".join(parts) + "."
