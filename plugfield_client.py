# plugfield_client.py
# -*- coding: utf-8 -*-

import json
import os
import urllib.request
from typing import Optional, Dict, List, Tuple
import re
import math


LOGIN_URL = os.getenv("PLUGFIELD_LOGIN_URL", "https://prod-api.plugfield.com.br/login")
DEVICE_URL = os.getenv("PLUGFIELD_DEVICE_URL", "https://prod-api.plugfield.com.br/device?page=1")
USERNAME = os.getenv("PLUGFIELD_USERNAME")
PASSWORD = os.getenv("PLUGFIELD_PASSWORD")
API_KEY = os.getenv("PLUGFIELD_API_KEY")
PLUGFIELD_CENTER_LAT = os.getenv("PLUGFIELD_CENTER_LAT")
PLUGFIELD_CENTER_LON = os.getenv("PLUGFIELD_CENTER_LON")

# Token em memória (processo)
_ACCESS_TOKEN: Optional[str] = None


def _require_credentials() -> Tuple[str, str, str]:
    missing = [
        name
        for name, value in {
            "PLUGFIELD_USERNAME": USERNAME,
            "PLUGFIELD_PASSWORD": PASSWORD,
            "PLUGFIELD_API_KEY": API_KEY,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Configure as credenciais Plugfield no ambiente: " + ", ".join(missing))
    return USERNAME, PASSWORD, API_KEY


def _http_json(url: str, method: str = "GET", data: Optional[Dict] = None, headers: Optional[Dict] = None,
               timeout_s: int = 10) -> Tuple[int, Dict]:
    headers = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, (json.loads(raw) if raw else {})


def get_auth_token() -> Optional[str]:
    global _ACCESS_TOKEN
    username, password, api_key = _require_credentials()
    headers = {"x-api-key": api_key}
    data = {"username": username, "password": password}
    try:
        status, payload = _http_json(LOGIN_URL, method="POST", data=data, headers=headers, timeout_s=10)
        if status == 200:
            _ACCESS_TOKEN = payload.get("access_token")
            return _ACCESS_TOKEN
    except Exception:
        return None
    return None


def _ensure_token() -> Optional[str]:
    if _ACCESS_TOKEN:
        return _ACCESS_TOKEN
    return get_auth_token()


def fetch_device_list() -> Dict:
    token = _ensure_token()
    if not token:
        raise RuntimeError("Não foi possível obter token da Plugfield.")

    _, _, api_key = _require_credentials()

    headers = {
        "Authorization": token,
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    status, payload = _http_json(DEVICE_URL, method="GET", headers=headers, timeout_s=10)
    if status == 401:
        # token expirou, tenta renovar uma vez
        token = get_auth_token()
        if not token:
            raise RuntimeError("Token Plugfield expirou e não foi possível renovar.")
        headers["Authorization"] = token
        status, payload = _http_json(DEVICE_URL, method="GET", headers=headers, timeout_s=10)
    if status != 200:
        raise RuntimeError(f"Erro Plugfield (status {status}).")
    return payload


def _extract_regions(query: str) -> List[str]:
    """Retorna TODAS as regioes mencionadas na query (ex: ['sul', 'norte'])."""
    q = (query or "").lower()
    regions = ["centro", "norte", "sul", "leste", "oeste", "sudeste", "sudoeste", "nordeste", "noroeste"]
    return [r for r in regions if re.search(rf"\b{r}\b", q)]


def _extract_region(query: str) -> Optional[str]:
    """Compat: retorna a primeira regiao encontrada, ou None."""
    found = _extract_regions(query)
    return found[0] if found else None


def _extract_place_terms(query: str) -> List[str]:
    q = (query or "").lower()
    tokens = re.findall(r"[a-zA-Z0-9]+", q)
    stop = {
        "chuva", "chuvas", "agora", "tempo", "estacao", "estacoes", "tempo", "real", "zona",
        "no", "na", "em", "do", "da", "de", "para", "pra", "por",
        "o", "a", "os", "as", "um", "uma", "uns", "umas",
        "como", "esta", "estao", "regiao", "cidade", "area", "monitorada",
        "nivel", "rio", "agua", "piezometro",
        "centro", "norte", "sul", "leste", "oeste", "sudeste", "sudoeste", "nordeste", "noroeste",
        "mais", "perto", "proximo", "proxima", "proximas", "proximos",
    }
    return [t for t in tokens if len(t) >= 3 and t not in stop]


def _to_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_center_coords(query: str) -> Optional[Tuple[float, float]]:
    q = (query or "").lower()
    if "centro" in q and PLUGFIELD_CENTER_LAT and PLUGFIELD_CENTER_LON:
        lat = _to_float(PLUGFIELD_CENTER_LAT)
        lon = _to_float(PLUGFIELD_CENTER_LON)
        if lat is not None and lon is not None:
            return (lat, lon)
    return None


def get_station_reports(query: Optional[str] = None) -> List[Dict]:
    data = fetch_device_list()
    reports: List[Dict] = []
    regions = _extract_regions(query or "")
    terms = _extract_place_terms(query or "")
    center = _get_center_coords(query or "")
    device_list = data.get("deviceList") or []
    for station in device_list:
        try:
            name = station.get("name", "estacao")
            name_l = name.lower()
            if regions and not any(r in name_l for r in regions):
                continue
            if terms and not any(t in name_l for t in terms):
                continue

            dash = station.get("dashboard", {}) or {}
            rain_today = _to_float(dash.get("rainDay")) or 0.0
            wind = _to_float(dash.get("wind"))
            gust = _to_float(dash.get("winb"))
            temp = _to_float(dash.get("temp"))
            humi = _to_float(dash.get("humi"))
            pres = _to_float(dash.get("pres"))
            dire = dash.get("direString")
            river_level = _to_float(dash.get("levelAdditional"))
            river_level_unit = None
            for sensor in ((dash.get("lastSensorData") or {}).get("sensorDataList") or []):
                if sensor.get("sensorCode") == "la" or "Nível de líquidos" in str(sensor.get("sensorName") or ""):
                    river_level_unit = sensor.get("sensorUnit")
                    break
            lat = _to_float(station.get("latitude"))
            lon = _to_float(station.get("longitude"))
            dist_km = None
            if center and lat is not None and lon is not None:
                dist_km = _distance_km(center[0], center[1], lat, lon)

            reports.append({
                "name": name,
                "rain_day": rain_today,
                "wind": wind,
                "gust": gust,
                "temp": temp,
                "humi": humi,
                "pres": pres,
                "dire": dire,
                "river_level": river_level,
                "river_level_unit": river_level_unit,
                "lat": lat,
                "lon": lon,
                "dist_km": dist_km,
            })
        except Exception:
            continue

    if not reports and (regions or terms):
        terms = []
        for station in device_list:
            try:
                name = station.get("name", "estacao")
                name_l = name.lower()
                if regions and not any(r in name_l for r in regions):
                    continue
                dash = station.get("dashboard", {}) or {}
                rain_today = _to_float(dash.get("rainDay")) or 0.0
                wind = _to_float(dash.get("wind"))
                gust = _to_float(dash.get("winb"))
                temp = _to_float(dash.get("temp"))
                humi = _to_float(dash.get("humi"))
                pres = _to_float(dash.get("pres"))
                dire = dash.get("direString")
                river_level = _to_float(dash.get("levelAdditional"))
                river_level_unit = None
                for sensor in ((dash.get("lastSensorData") or {}).get("sensorDataList") or []):
                    if sensor.get("sensorCode") == "la" or "Nível de líquidos" in str(sensor.get("sensorName") or ""):
                        river_level_unit = sensor.get("sensorUnit")
                        break
                lat = _to_float(station.get("latitude"))
                lon = _to_float(station.get("longitude"))
                dist_km = None
                if center and lat is not None and lon is not None:
                    dist_km = _distance_km(center[0], center[1], lat, lon)
                reports.append({
                    "name": name,
                    "rain_day": rain_today,
                    "wind": wind,
                    "gust": gust,
                    "temp": temp,
                    "humi": humi,
                    "pres": pres,
                    "dire": dire,
                    "river_level": river_level,
                    "river_level_unit": river_level_unit,
                    "lat": lat,
                    "lon": lon,
                    "dist_km": dist_km,
                })
            except Exception:
                continue

    if any(r.get("dist_km") is not None for r in reports):
        reports.sort(key=lambda x: (x.get("dist_km") is None, x.get("dist_km") or 0))
    else:
        reports.sort(key=lambda x: x.get("rain_day", 0.0), reverse=True)
    return reports


def format_station_reports(reports: List[Dict], region: Optional[str] = None, limit: int = 5) -> str:
    if not reports:
        if region:
            return f"Nenhuma das estacoes em {region} esta registrando chuva no momento."
        return "Nenhuma das estacoes esta registrando chuva no momento."

    lines = []
    for r in reports[:limit]:
        name = r.get("name", "estacao")
        rain = r.get("rain_day", 0.0)
        wind = r.get("wind")
        gust = r.get("gust")
        temp = r.get("temp")
        humi = r.get("humi")
        pres = r.get("pres")
        dire = r.get("dire")
        dist = r.get("dist_km")

        parts = [f"{name}: {rain:.1f} mm hoje"]
        if temp is not None:
            parts.append(f"temp {temp:.1f}C")
        if humi is not None:
            parts.append(f"umid {humi:.0f}%")
        if wind is not None:
            w = f"vento {wind:.1f} km/h"
            if dire:
                w += f" {dire}"
            parts.append(w)
        if gust is not None and gust > 0:
            parts.append(f"rajada {gust:.1f} km/h")
        if pres is not None:
            parts.append(f"pressao {pres:.0f} hPa")
        if dist is not None:
            parts.append(f"{dist:.1f} km do centro")

        lines.append(" - ".join(parts) + ".")
    return "\n".join(lines)
