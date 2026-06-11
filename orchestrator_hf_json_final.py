# orchestrator_hf_json_final.py
# -*- coding: utf-8 -*-

"""
Orquestrador (HF Transformers CPU) com:
- Classificação de intenção via LLM (Gemma 2) retornando JSON
- Modo "só LLM": sem override por keyword e sem fallback por keyword
- Auto-reparo 100% LLM: "label-only" e "self-consistency vote"
- LGPD labeling + masking
- Logging JSONL detalhado (inclui llm_raw truncado e métricas)
- Pré-carregamento + warm-up
- Evento meta_start com infos de máquina e runtime
- Modo "precisão > velocidade" (determinístico + retries)
- Camada pré-SLM: handlers determinísticos para consultas analíticas

Execução:
  python orchestrator_hf_json_final.py
"""

import os
import re
import json
import time
import uuid
import random
import platform
import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import hashlib
import secrets
import difflib as _difflib
import unicodedata as _unicodedata

# ----- ML/LLM (opcional: indisponivel em ambientes sem GPU/CPU stack) -----
try:
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    _TORCH_OK = True
except ImportError:
    torch = None  # type: ignore
    AutoTokenizer = None  # type: ignore
    AutoModelForCausalLM = None  # type: ignore
    _TORCH_OK = False

# =========================
# Configurações por ambiente
# =========================

ORCH_VERSION = os.getenv("ORCH_VERSION", "2.6.0")

def _to_bool(x: Optional[str], default=False) -> bool:
    if x is None:
        return default
    return x.strip().lower() in ("1", "true", "yes", "y", "on")

HF_MODEL_ID = os.getenv("HF_MODEL_ID", "google/gemma-2-2b-it")

# Threads (CPU)
HF_NUM_THREADS   = int(os.getenv("HF_NUM_THREADS", "12"))
HF_NUM_INTEROP   = int(os.getenv("HF_NUM_INTEROP", "1"))
os.environ.setdefault("OMP_NUM_THREADS", str(HF_NUM_THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(HF_NUM_THREADS))

# Geração — preferimos precisão (determinístico + retries)
ORCH_MAX_NEW_TOKENS = int(os.getenv("ORCH_MAX_NEW_TOKENS", "64"))
ORCH_DO_SAMPLE      = _to_bool(os.getenv("ORCH_DO_SAMPLE", "0"), False)
ORCH_JSON_RETRIES   = int(os.getenv("ORCH_JSON_RETRIES", "5"))  # tentativas extras p/ JSON válido
ORCH_SLOW_MODE      = _to_bool(os.getenv("ORCH_SLOW_MODE", "1"), True)  # se 1, aumenta tokens/retries p/ robustez

# Controle de fluxo LLM
ORCH_USE_LLM        = _to_bool(os.getenv("ORCH_USE_LLM", "1"), True)  # se 0, ignora LLM e usa keywords
ORCH_STRICT_LLM     = _to_bool(os.getenv("ORCH_STRICT_LLM", "0"), False)  # se 1 e LLM falhar → erro

# Logging do texto bruto
ORCH_INCLUDE_LLM_RAW   = _to_bool(os.getenv("ORCH_INCLUDE_LLM_RAW", "1"), True)
ORCH_LLM_RAW_MAXCHARS  = int(os.getenv("ORCH_LLM_RAW_MAXCHARS", "4000"))

# --- SOMENTE LLM (sem override/fallback por keyword) ---
ORCH_ENABLE_RT_OVERRIDE = _to_bool(os.getenv("ORCH_ENABLE_RT_OVERRIDE", "1"), False)  # override desativado
ORCH_ENABLE_PV_OVERRIDE = _to_bool(os.getenv("ORCH_ENABLE_PV_OVERRIDE", "1"), False)  # override desativado
ORCH_KW_FALLBACK        = _to_bool(os.getenv("ORCH_KW_FALLBACK", "0"), False)         # fallback por keyword desativado

# limites específicos p/ classificação
ORCH_CLS_MAX_NEW_TOKENS = int(os.getenv("ORCH_CLS_MAX_NEW_TOKENS", "64"))
ORCH_LABEL_ONLY_MAX_NEW_TOKENS = int(os.getenv("ORCH_LABEL_ONLY_MAX_NEW_TOKENS", "16"))
ORCH_SELF_CONSIST       = int(os.getenv("ORCH_SELF_CONSIST", "3"))  # tentativas p/ voto LLM

# (opcional/estético) tempo limite "conceitual" p/ chamadas LLM
ORCH_LLM_TIMEOUT_S      = int(os.getenv("ORCH_LLM_TIMEOUT_S", "25"))




# Caminho do log
LOG_PATH = os.getenv("ORCH_LOG_PATH", "audit_log.jsonl")

# Intents válidas
INTENTS = ("PREVISAO", "ESTACOES_RT", "GENERICO")

# Ajustes de "slow mode"
if ORCH_SLOW_MODE:
    ORCH_JSON_RETRIES   = max(ORCH_JSON_RETRIES, 5)
    ORCH_MAX_NEW_TOKENS = max(ORCH_MAX_NEW_TOKENS, 64)

# =========================
# Utilidades
# =========================
def pre_mask_for_llm(text: str) -> str:
    # preserva localidades; mascara identificadores pessoais
    t = PII_PATTERNS["CPF"].sub("***.***.***-**", text)
    t = PII_PATTERNS["CNPJ"].sub("**.***.***/****-**", t)
    t = PII_PATTERNS["PHONE"].sub("(**) *****-****", t)
    t = PII_PATTERNS["EMAIL"].sub("***@***", t)
    return t

def sanitize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())

def now_utc_iso() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"

def write_jsonl(path: str, obj: Dict):
    obj["ts"] = obj.get("ts") or now_utc_iso()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def get_machine_info() -> Dict:
    # RAM opcional via psutil
    ram_gb = None
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        pass
    return {
        "os": f"{platform.system()}-{platform.release()}",
        "python": platform.python_version(),
        "pytorch": torch.__version__ if _TORCH_OK else None,
        "cuda": torch.cuda.is_available() if _TORCH_OK else False,
        "cuda_name": (torch.cuda.get_device_name(0) if torch.cuda.is_available() else None) if _TORCH_OK else None,
        "mps": (getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()) if _TORCH_OK else False,
        "cpu_logical": os.cpu_count() or None,
        "cpu_physical": None,  # deixamos None para evitar dependência
        "ram_total_gb": ram_gb,
    }

# =========================
# API de Perfil (simulada)
# =========================

def _gen_user_id(prefix: str = "u") -> str:
    ts_hex = f"{time.time_ns():x}"
    pid_hex = f"{os.getpid():x}"
    rnd_hex = secrets.token_hex(3)
    return f"{prefix}_{ts_hex}_{pid_hex}_{rnd_hex}"

def _short_hash(s: str, n: int = 12) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:n]

def api_perfil(user_id: str) -> Dict:
    user_id = _gen_user_id(prefix="u")
    h = _short_hash(user_id, n=12)

    return {
        "user_id_hash": f"u_{h}",
        "papel": "cidadao",
        "permissoes": ["meteo.basico"],
        "idioma": "pt-BR",
        "loc": "Sao Jose dos Campos",
        "policy_version": "v1",
        "ttl_perfil": 600,
    }

# =========================
# Rotulagem LGPD (heurística)
# =========================

PII_PATTERNS = {
    "CPF": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "CNPJ": re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"),
    "PHONE": re.compile(r"\b(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}-?\d{4}\b"),
    "EMAIL": re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE),
    "COORD": re.compile(r"\b-?\d{1,2}\.\d{4,},\s*-?\d{1,3}\.\d{4,}\b"),
    "ADDRESS": re.compile(r"\b(rua|avenida|av\.?|rodovia|estrada)\s+[^\d\n]+(\d{1,5})\b", re.IGNORECASE),
}

SENSITIVE_TERMS = [
    "religião", "religioso", "saúde", "hospital", "doença",
    "genético", "biométrico", "político", "partido", "sindicato", "vida sexual"
]

def detect_sensitivity(text: str) -> List[str]:
    labels = set()
    for name, rgx in PII_PATTERNS.items():
        if rgx.search(text):
            labels.add("GEO_PRECISA" if name in ("COORD", "ADDRESS") else "DADO_PESSOAL")
    for t in SENSITIVE_TERMS:
        if re.search(rf"\b{re.escape(t)}\b", text, flags=re.IGNORECASE):
            labels.add("DADO_SENSIVEL")
            break
    return sorted(labels)

def mask_text(text: str) -> str:
    text = PII_PATTERNS["CPF"].sub("***.***.***-**", text)
    text = PII_PATTERNS["CNPJ"].sub("**.***.***/****-**", text)
    text = PII_PATTERNS["PHONE"].sub("(**) *****-****", text)
    text = PII_PATTERNS["EMAIL"].sub("***@***", text)
    text = PII_PATTERNS["ADDRESS"].sub("sua região", text)
    text = PII_PATTERNS["COORD"].sub("sua região", text)
    return text

# =========================
# Simulação das rotas
# =========================

def api_previsao(query: str, perfil: Dict) -> str:
    try:
        from openweather_client import fetch_forecast, format_forecast_pt
        city = (perfil or {}).get("loc") or None
        data = fetch_forecast(city=city)
        return format_forecast_pt(query, data)
    except Exception:
        janelas = ["próximas 6h", "hoje à noite", "amanhã cedo", "fim de semana"]
        cond = random.choice(["chuva fraca", "nublado", "pancadas isoladas", "céu claro"])
        return f"Previsão para {random.choice(janelas)} na sua região: {cond}."

def api_estacoes(query: str, perfil: Dict) -> str:
    try:
        from plugfield_client import get_station_reports, format_station_reports, _extract_region
        region = _extract_region(query)
        reports = get_station_reports(query=query)
        return format_station_reports(reports, region=region, limit=len(reports) or 5)
    except Exception:
        mm = round(random.uniform(0.0, 15.0), 1)
        vento = round(random.uniform(0.0, 20.0), 1)
        return f"Estações em tempo real — chuva: {mm} mm (últ. 2h); vento: {vento} km/h (agora)."

def llm_generico(query: str, perfil: Dict) -> str:
    return ("Posso ajudar com informações gerais. "
            "Se quiser previsão, diga 'previsão'; para dados de estações, diga 'estações'.")

# =========================
# LLM helpers
# =========================

_tokenizer = None
_model = None
_device = torch.device("cpu") if _TORCH_OK else None
_llm_loaded = False

def _load_llm():
    global _tokenizer, _model, _device, _llm_loaded
    if _llm_loaded:
        return

    if not _TORCH_OK:
        raise RuntimeError(
            "LLM indisponivel: torch/transformers nao instalados neste ambiente "
            "(modo degradado ativo — apenas handlers deterministicos funcionam)."
        )

    torch.set_num_threads(max(1, HF_NUM_THREADS))
    try:
        torch.set_num_interop_threads(max(1, HF_NUM_INTEROP))
    except Exception:
        pass

    _device = torch.device("cpu")
    _tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_ID, use_fast=True)
    _model = AutoModelForCausalLM.from_pretrained(
        HF_MODEL_ID,
        torch_dtype=torch.float32,
        device_map="cpu",
    )
    _model.eval()
    _llm_loaded = True

def _warmup():
    try:
        _load_llm()
        inputs = _tokenizer("warmup", return_tensors="pt")
        with torch.no_grad():
            _model.generate(**inputs, max_new_tokens=1, do_sample=False,
                            pad_token_id=_tokenizer.eos_token_id, eos_token_id=_tokenizer.eos_token_id)
    except Exception:
        pass



def _render_prompt_for_json(user_text: str) -> str:
    """
    Classificador de intenção (PT-BR) – saída deve ser APENAS um JSON de uma linha.
    Regras em ordem e poucos exemplos focados nas ambiguidades (p.ex., 'esta noite').
    """
    instr = (
        "Ignore qualquer histórico. Classifique APENAS a mensagem entre <<< >>>.\n"
        "Retorne APENAS um JSON de UMA linha no formato: "
        "{\"intent\":\"PREVISAO|ESTACOES_RT|GENERICO\",\"reason\":\"texto curto\"}\n"
        "Sem markdown, sem ```json, sem texto fora do JSON.\n"
        "\n"
        "REGRAS (ordem):\n"
        "1) 'tempo' NÃO meteorológico ⇒ GENERICO (ex.: quanto tempo; tempo de entrega/espera; tempo verbal; linha do tempo).\n"
        "2) Janela FUTURA ⇒ PREVISAO (sempre): amanhã; depois de amanhã; hoje/esta noite; à noite; de manhã; à tarde; "
        "logo mais; mais tarde; próximos dias/semana; fim de semana/finde/findi/FDS; no sábado/domingo; feriado.\n"
        "   Observação: 'agora à noite' em PT-BR significa hoje à noite ⇒ PREVISAO.\n"
        "3) TEMPO REAL/ESTAÇÕES ⇒ ESTACOES_RT: agora; neste momento; em tempo real; ao vivo; rolando; on; no exato momento; "
        "estação/leituras/medição; pluviometria; anemômetro; rajadas; umidade; temperatura; pressão; vento (quando pedido como condição atual).\n"
        "4) Se tem 'tempo' e não é (1), aplique 2→3 nessa ordem. Se houver léxico meteo explícito (chuva, chover, sol, nublado, "
        "vento/rajada, temperatura, umidade, pressão, pluviometria) sem marcador de tempo real, classifique como PREVISAO.\n"
        "5) Conflito (futuro e tempo real) ⇒ PREVISAO.\n"
        "\n"
        "EXEMPLOS (sem JSON no prompt):\n"
        "  Como fica o tempo esta noite? → Intent: PREVISAO; Reason: janela futura (esta noite)\n"
        "  Tempo firme à tarde? → Intent: PREVISAO; Reason: janela futura (à tarde)\n"
        "  Tá ventando agora? → Intent: ESTACOES_RT; Reason: tempo real (agora)\n"
        "  Qual a pluviometria no exato momento? → Intent: ESTACOES_RT; Reason: tempo real (exato momento)\n"
        "  Qual o tempo de entrega do pedido? → Intent: GENERICO; Reason: duração (não meteorológico)\n"
        "\n"
        "Responda SOMENTE com um único objeto JSON de uma linha e finalize exatamente no '}'.\n"
        "<<<" + user_text.strip() + ">>>"
    )
    return instr



def _clean_reason(r: Optional[str]) -> str:
    if not r:
        return "texto curto"
    r = re.sub(r"\s+", " ", str(r)).strip()
    # Evita confusão com transporte
    r = re.sub(r"\b(metr[oô]|trem|linha|estação de metr[oô])\b", "estações meteorológicas", r, flags=re.IGNORECASE)
    # Mantém conciso
    return r[:160]


def _generate_text(prompt: str, max_new_tokens: Optional[int] = None) -> Tuple[str, Dict]:
    from time import perf_counter
    _load_llm()
    t0 = perf_counter()
    inputs = _tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        out = _model.generate(
            **inputs,
            max_new_tokens=(max_new_tokens or ORCH_MAX_NEW_TOKENS),
            do_sample=ORCH_DO_SAMPLE,
            pad_token_id=_tokenizer.eos_token_id,
            eos_token_id=_tokenizer.eos_token_id,
            use_cache=True,
        )
    llm_ms = int((perf_counter() - t0) * 1000)
    raw_text = _tokenizer.decode(out[0], skip_special_tokens=True)
    try:
        new_tokens = int(out.shape[-1] - inputs["input_ids"].shape[-1])
    except Exception:
        new_tokens = None
    info = {"llm_ms": llm_ms, "new_tokens": new_tokens, "stop_reason": None}
    return raw_text, info

def _strip_code_fences(s: str) -> str:
    # remove blocos ```...``` e ```json ... ```
    s = re.sub(r"```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = s.replace("```", "")
    return s

def _iter_json_objects(text: str):
    """
    Itera por TODOS os objetos JSON top-level no texto,
    balanceando chaves e ignorando chaves dentro de strings.
    Produz tuplas (start, end, obj_dict).
    """
    txt = _strip_code_fences(text)
    in_str = False
    escape = False
    depth = 0
    start = None

    for i, ch in enumerate(txt):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            # dentro de string ignoramos chaves
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    blob = txt[start:i+1]
                    try:
                        obj = json.loads(blob)
                        yield (start, i+1, obj)
                    except Exception:
                        pass
                    start = None

def _extract_best_json_object(text: str) -> Optional[Dict]:
    """
    Retorna o MELHOR objeto JSON encontrado:
    - prioridade 1: último objeto cujo "intent" normaliza para INTENTS
      e NÃO contém pipes ('|') no valor cru
    - prioridade 2: último objeto que tenha "intent" normalizado válido
    - fallback: último objeto válido (se nenhum tiver intent válido)
    """
    candidates = []
    valid_intent_objs = []
    strict_intent_objs = []

    for _, _, obj in _iter_json_objects(text):
        candidates.append(obj)
        raw_intent = str(obj.get("intent", "")).strip()
        norm = _normalize_intent(raw_intent)
        if norm:
            valid_intent_objs.append((obj, raw_intent, norm))
            # descarta aqueles que são eco do enunciado "PREVISAO|ESTACOES_RT|GENERICO"
            if '|' not in raw_intent:
                strict_intent_objs.append((obj, raw_intent, norm))

    # 1) último com intent OK e sem '|'
    if strict_intent_objs:
        obj, raw_intent, norm = strict_intent_objs[-1]
        obj["intent"] = norm
        return obj

    # 2) último com intent OK (mesmo que tenha '|', como fallback fraco)
    if valid_intent_objs:
        obj, raw_intent, norm = valid_intent_objs[-1]
        obj["intent"] = norm
        return obj

    # 3) nenhum com intent válido → último objeto JSON qualquer
    if candidates:
        return candidates[-1]

    return None

def _extract_first_json_object(text: str) -> Optional[Dict]:
    """
    Encontra o primeiro objeto JSON balanceando chaves.
    Aceita lixo antes/depois e contém 'code fences'.
    """
    txt = _strip_code_fences(text)
    try:
        start = txt.index("{")
    except ValueError:
        return None
    depth = 0
    end = None
    for i in range(start, len(txt)):
        c = txt[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return None
    blob = txt[start:end+1]
    try:
        obj = json.loads(blob)
        return obj
    except Exception:
        return None

def _normalize_intent(x: str) -> Optional[str]:
    if not x:
        return None
    x = x.strip().upper()
    if x in INTENTS:
        return x
    # tolerância a acentos/minúsculas comuns:
    if x in ("PREVISÃO", "PREVISAO", "PREV"):
        return "PREVISAO"
    if x in ("ESTACOES_RT", "ESTAÇÕES_RT", "ESTACOES", "ESTACOES-RT"):
        return "ESTACOES_RT"
    if x in ("GENÉRICO", "GEN", "GENERIC", "GERAL"):
        return "GENERICO"
    return None

# ====== Auto-reparo 100% LLM: label-only e voting ======

def _parse_label_only(text: str) -> Optional[str]:
    """
    Extrai a ÚLTIMA ocorrência de PREVISAO|ESTACOES_RT|GENERICO do texto,
    para ignorar a linha das instruções e ficar com a resposta final.
    """
    t = re.sub(r"```(?:json)?\s*|\*\*|__", "", text, flags=re.IGNORECASE)
    matches = re.findall(r'\b(PREVISAO|ESTACOES_RT|GENERICO)\b', t.upper())
    if not matches:
        return None
    return _normalize_intent(matches[-1])

def _call_llm_label_only(user_text: str) -> Tuple[Optional[str], str, Dict]:
    prompt = (
        "Responda SOMENTE com UMA palavra EXATA entre:\n"
        "PREVISAO | ESTACOES_RT | GENERICO\n"
        "Sem frases, sem pontuação, sem markdown.\n"
        "Regras:\n"
        " - PREVISAO: perguntas de futuro/previsão (amanhã, próximos dias, fim de semana, \"finde\", \"vai molhar\", \"cai água\").\n"
        " - ESTACOES_RT: condição AGORA/tempo real (\"agora\", \"neste momento\", estação, medição, \"ventinho\"/vento AGORA).\n"
        " - GENERICO: restante/fora do domínio.\n"
        f"Usuário: {user_text.strip()}\n"
    )
    raw, info = _generate_text(prompt, max_new_tokens=8)
    label = _parse_label_only(raw)
    return label, raw, info


def _vote_llm_label_only(user_text: str, k: int = ORCH_SELF_CONSIST) -> Tuple[Optional[str], List[str]]:
    from collections import Counter
    votes: List[str] = []
    raws: List[str] = []
    for _ in range(max(1, k)):
        lab, raw, _info = _call_llm_label_only(user_text)
        raws.append(raw)
        if lab:
            votes.append(lab)
    if not votes:
        return None, raws
    return Counter(votes).most_common(1)[0][0], raws

# =========================
# Orquestrador (regexes de suporte)
# =========================

RT_REGEX = re.compile(r"\b(agora|neste momento|no momento|momento|ao vivo|tempo real|agorinha|imediato|atual)\b", re.IGNORECASE)
PV_REGEX = re.compile(
    r"\b("
    r"previs(?:ao|ão)"
    r"|amanh(?:a|ã)"
    r"|depois de amanh(?:a|ã)"
    r"|pr(?:o|ó)xim[oa]s?"
    r"|semana"
    r"|fim de semana|final de semana|finde|findi|FDS"
    r"|vai chover|chover(?:a|á)?"
    r"|temperatura para|clima para"
    r"|domingo|segunda|terça|quarta|quinta|sexta|sábado"
    r"|feriado"
    r"|esta noite|essa noite|hoje à noite|à noite"
    r"|de manhã|cedo"
    r"|logo mais|mais tarde|à tarde"
    r"|nos próximos|nos? dia"
    r"|vai fazer frio|vai fazer calor|vai esquentar|vai esfriar"
    r"|vai ter chuva|vai ter tempestade|vai ter sol"
    r"|vai dar pra|vai dar chuva"
    r"|esse fim|esse final|essa semana|nessa semana"
    r"|no fim|no final|neste fim|neste final"
    r"|daqui a pouco|daqui a"
    r")\b",
    re.IGNORECASE,
)
ESTAC_REGEX = re.compile(r"\b(estac(?:ao|oes|ões)|pluviom(?:etrica|étrica|etrico|étrico)|anem(?:ometro|ômetro|ometrio|ômetrio)|vento|umidade|press(?:ao|ão)|temperatura|rajada|chuva)\b", re.IGNORECASE)
REGION_REGEX = re.compile(r"\b(regi(?:ao|ão)|zona|bairro|centro|norte|sul|leste|oeste|sudeste|sudoeste|nordeste|noroeste)\b", re.IGNORECASE)
STATUS_REGEX = re.compile(r"\b(situa(?:cao|ção)|condi(?:cao|ção)|monitoramento|dados|leituras?|como esta|como estao|mostre|me diga|quero saber|qual|quais|panorama|status|alerta)\b", re.IGNORECASE)


# ============================================================
# CAMADA PRÉ-PROCESSAMENTO: handlers determinísticos (pré-SLM)
#
# Intercepta consultas analíticas bem-definidas ANTES de chamar o
# Gemma 2, retornando respostas sintetizadas em Python puro.
# Se a API de estações estiver indisponível, retorna None e o
# fluxo normal (SLM) assume o controle automaticamente.
# ============================================================

def _strip_accents(s: str) -> str:
    """Remove acentos e faz lowercase — usado para matching robusto de padrões."""
    nfkd = _unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not _unicodedata.combining(c)).lower()


# ── Patterns (aplicados sobre texto normalizado sem acentos) ─────────────────

# Handler 1 — bairros com chuva agora
_PAT_RAIN_BAIRROS = re.compile(
    r"bairros?\s*(?:com|tendo|registrando|sob)\s*chuva"
    r"|onde\s+(?:esta\s+)?chovendo"
    r"|quais?\s*(?:bairros?|locais?|regioes?|lugares?)\s*(?:estao?\s*)?(?:chovendo|com\s*chuva)"
    r"|esta\s*chovendo\s*em\s*quais?"
    r"|(?:chovendo|chuva)\s*(?:agora|no\s+momento|neste\s+momento)",
)

_PAT_RAIN_REGION = re.compile(
    r"\bchuvas?\s+(?:agora\s+)?(?:na|no|em)\s+(?:(?:zona|regi[aã]o)\s+)?"
    r"(?:centro|norte|sul|leste|oeste|sudeste|sudoeste|nordeste|noroeste)\b",
    re.IGNORECASE,
)

# Handler 2 — maior/menor métrica (dois sub-padrões: sinal extremo + nome de métrica)
_PAT_EXTREME_SIGNAL = re.compile(
    r"\b(?:maior|menor|maximo?|maxima?|minimo?|minima?"
    r"|mais\s+(?:quente|fria?|umido?|seco?|chuvoso?))\b"
)
_PAT_METRIC = re.compile(
    r"\b(?:temperatura|temp\b|umidade|umid\b|chuva|precipitacao|pressao)\b"
)

# Handler 3 — resumo / panorama geral do clima
_PAT_SUMMARY = re.compile(
    r"como\s+esta\s+o\s+(?:tempo|clima)"
    r"|como\s+esta\s+a\s+(?:regiao|cidade|area\s+monitorada)"
    r"|resumo\s+(?:do\s+)?(?:tempo|clima|climatico)"
    r"|resumo\s+(?:da\s+)?(?:regiao|cidade|area\s+monitorada)"
    r"|panorama\s+(?:do\s+)?(?:tempo|clima)"
    r"|panorama\s+(?:da\s+)?(?:regiao|cidade|area\s+monitorada)"
    r"|situacao\s+(?:atual\s+)?(?:do\s+)?(?:tempo|clima)"
    r"|situacao\s+(?:atual\s+)?(?:da\s+)?(?:regiao|cidade|area\s+monitorada)"
    r"|visao\s+geral\s+(?:do\s+)?(?:tempo|clima)"
    r"|visao\s+geral\s+(?:da\s+)?(?:regiao|cidade|area\s+monitorada)"
    r"|como\s+anda\s+o\s+(?:tempo|clima)"
    r"|geral\s+do\s+(?:tempo|clima)",
)

# Sinal genérico de estações em tempo real — usado para triagem do handler 4
_PAT_STATION_SIGNAL = re.compile(
    r"\b(?:agora|tempo\s+real|momento|estacao|temperatura|umidade|chuva|vento|pressao)\b"
)


# ── Acesso seguro à API ──────────────────────────────────────────────────────

def _fetch_all_stations_safe() -> Optional[List[Dict]]:
    """Busca todas as estações via Plugfield; retorna None em caso de falha."""
    try:
        from plugfield_client import get_station_reports
        stations = get_station_reports(query="")
        return stations if stations is not None else []
    except Exception:
        return None



def _fetch_stations_for_query_safe(query: str) -> Optional[List[Dict]]:
    """Busca estacoes via Plugfield respeitando filtros presentes na query."""
    try:
        from plugfield_client import get_station_reports
        stations = get_station_reports(query=query)
        return stations if stations is not None else []
    except Exception:
        return None

# ── Handlers individuais ─────────────────────────────────────────────────────

def _handle_rain_bairros(
    stations: List[Dict],
    region: Optional[str] = None,
    regions: Optional[List[str]] = None,
) -> str:
    """
    Handler 1 — lista estações com chuva, ordenadas por volume decrescente.
    Formato: "Chovendo agora em N estações: X (Y mm), ... Sem chuva nas outras Z."
    Aceita 'regions' (lista) ou 'region' (string) para compatibilidade.
    """
    raining = sorted(
        [s for s in stations if (s.get("rain_day") or 0.0) > 0.0],
        key=lambda s: s.get("rain_day", 0.0),
        reverse=True,
    )
    total = len(stations)
    if not raining:
        return (
            f"Nenhuma das {total} estações monitoradas está "
            "registrando chuva no momento."
        )
    n = len(raining)
    top5 = raining[:5]
    top_str = ", ".join(
        f"{s['name']} ({s['rain_day']:.1f} mm)" for s in top5
    )
    dry = total - n
    # Monta escopo: usa 'regions' (lista) se disponível, senão cai em 'region'
    _regions = regions or ([region] if region else [])
    scope = f" da zona {' e '.join(_regions)}" if _regions else ""
    if n > 5:
        top_str += f" (e mais {n - 5})"
    msg = f"Chovendo agora em {n} {'estações' if n > 1 else 'estação'}{scope}: {top_str}."
    if dry > 0:
        msg += f" Sem chuva nas {'outras' if dry > 1 else 'outra'} {dry} {'estações' if dry > 1 else 'estação'}."
    return msg


def _handle_extremes(query_stripped: str, stations: List[Dict]) -> str:
    """
    Handler 2 — retorna maior e menor valor para a métrica pedida na query.
    Formato: "A maior temperatura agora é X°C em [bairro]. A menor é Y°C em [bairro]."
    """
    if re.search(r"\b(?:umidade|umid)\b", query_stripped):
        key, label, fmt = "humi", "umidade", "{:.0f}%"
    elif re.search(r"\b(?:pressao|pres)\b", query_stripped):
        key, label, fmt = "pres", "pressão", "{:.0f} hPa"
    elif re.search(r"\b(?:chuva|precipitacao)\b", query_stripped):
        key, label, fmt = "rain_day", "chuva (acumulado hoje)", "{:.1f} mm"
    else:
        # default: temperatura
        key, label, fmt = "temp", "temperatura", "{:.1f}°C"

    valid = [
        (s.get("name", "?"), s[key])
        for s in stations
        if s.get(key) is not None
    ]
    if not valid:
        return f"Não há dados de {label} disponíveis no momento."

    max_name, max_val = max(valid, key=lambda x: x[1])
    min_name, min_val = min(valid, key=lambda x: x[1])
    return (
        f"A maior {label} agora é {fmt.format(max_val)} em {max_name}. "
        f"A menor é {fmt.format(min_val)} em {min_name}."
    )


def _handle_summary(stations: List[Dict]) -> str:
    """
    Handler 3 — resumo de 2-3 linhas com médias cidade e condições principais.
    """
    total = len(stations)
    if not total:
        return "Não há dados de estações disponíveis no momento."

    temps   = [s["temp"] for s in stations if s.get("temp") is not None]
    humis   = [s["humi"] for s in stations if s.get("humi") is not None]
    raining = [s          for s in stations if (s.get("rain_day") or 0.0) > 0.0]

    lines = []

    if temps:
        avg_t = sum(temps) / len(temps)
        lines.append(
            f"Temperatura: média {avg_t:.1f}°C "
            f"(máx {max(temps):.1f}°C, mín {min(temps):.1f}°C)"
        )

    if humis:
        avg_h = sum(humis) / len(humis)
        lines.append(f"Umidade média: {avg_h:.0f}%")

    n_rain = len(raining)
    if n_rain:
        top3 = sorted(raining, key=lambda x: x.get("rain_day", 0), reverse=True)[:3]
        top3_str = ", ".join(
            f"{s['name']} ({s['rain_day']:.1f} mm)" for s in top3
        )
        lines.append(
            f"Chuva em {n_rain}/{total} estações da regiao monitorada — destaque: {top3_str}"
        )
    else:
        lines.append(f"Sem chuva nas {total} estações da regiao monitorada")

    return ". ".join(lines) + "."


# Perguntas interrogativas de localidade NAO sao lookups de bairro
_PAT_INTERROGATIVE_LOC = re.compile(
    r"\bqual\s+bairro\b"
    r"|\bem\s+qual\b"
    r"|\bonde\s+est[a]\b"
    r"|\bonde\s+venta\b"
    r"|\bonde\s+chove\b",
    re.IGNORECASE,
)


def _handle_ambiguous_location(
    query_stripped: str, stations: List[Dict]
) -> Optional[str]:
    """
    Handler 4 ? verifica se ha localidade explicitamente reconhecivel.
    Se a localidade nao for encontrada, NAO responde diretamente: devolve None
    para que o fluxo normal possa cair no SLM e tentar entender a intencao.
    Nao dispara para consultas interrogativas.
    """
    if _PAT_INTERROGATIVE_LOC.search(query_stripped):
        return None

    try:
        from plugfield_client import _extract_place_terms
        terms = _extract_place_terms(query_stripped)
    except Exception:
        return None

    if not terms:
        return None  # sem termos de localidade ? nao e caso de ambiguidade

    names = [s.get("name", "") for s in stations if s.get("name")]
    names_norm = [_strip_accents(n) for n in names]

    for term in terms:
        t_norm = _strip_accents(term)
        if any(t_norm in n for n in names_norm):
            return None

    # Nenhuma estacao encontrada. Este residuo pode ser apenas ruido lexical
    # ("qual", "acumulada", "hoje" etc.), entao nao devemos bloquear o SLM.
    return None

# ── Patterns pré-SLM: consultas genéricas de tempo real ──────────────────────
# Aplicados ANTES do SLM; nao devem capturar perguntas de previsao futura.

# Temperatura atual generica
# Nao deve capturar perguntas futuras como "temperatura para amanha" ou "temperatura no domingo".
# Estrategia: alternativas separadas por presenca de qualificador de tempo real
#   ou ausencia verificada de marcadores futuros conhecidos.
_PAT_TEMP_ATUAL = re.compile(
    # 1. Qualificador explicito de tempo real — sempre valido
    r"qual\s+(?:e\s+a?\s+|a\s+)?temp(?:eratura)?\s+(?:agora|atual|no\s+momento|em\s+tempo\s+real)"
    r"|como\s+esta\s+a\s+temp(?:eratura)?\s*(?:agora|atual|no\s+momento|em\s+tempo\s+real)?"
    r"(?!\s+para|\s+de\s+amanh|\s+no\s+(?:fim|final|domingo|feriado|proxim))"
    # 2. Pergunta curta sem qualificador: "Qual a temperatura?" ou "Qual e a temperatura?"
    # Exige que logo apos temperatura nao venha marcador de futuro
    r"|qual\s+(?:e\s+)?a\s+temperatura\s*(?!\s*para|\s*de\s*amanh|\s*no\s*(?:fim|final|domingo|feriado|proxim))\s*\??"
    # 3. Formas curtas com qualificador
    r"|temp(?:eratura)?\s+(?:agora|atual|no\s+momento)"
    r"|temp\s+agora"
)

# Umidade atual generica
_PAT_UMIDADE_ATUAL = re.compile(
    r"qual\s+(?:e\s+a?\s+|a\s+)?umidade(?:\s+do\s+ar|\s+atual|\s+agora|\s+no\s+momento)?"
    r"|como\s+esta\s+a\s+umidade"
    r"|umidade\s+(?:agora|atual|do\s+ar|no\s+momento)"
)

# Vento atual generico (inclui perguntas locativas: onde venta mais)
_PAT_VENTO_ATUAL = re.compile(
    r"qual\s+(?:e\s+a?\s+|a\s+)?(?:velocidade\s+do\s+|vento\s+(?:atual|agora|no\s+momento))"
    r"|como\s+esta\s+o\s+vento"
    r"|vento\s+(?:agora|atual|no\s+momento)"
    r"|tem\s+rajada"
    r"|onde\s+(?:esta\s+)?ventando"
    r"|onde\s+venta\s+mais"
    r"|qual\s+(?:bairro|estacao|local)\s+(?:esta\s+)?(?:com\s+mais\s+vento|mais\s+ventoso)"
    r"|em\s+que\s+(?:bairro|estacao|local)\s+(?:esta\s+ventando|o\s+vento\s+esta)"
    r"|onde\s+tem\s+mais\s+vento"
)

# Pressao atual generica
_PAT_PRESSAO_ATUAL = re.compile(
    r"qual\s+(?:e\s+a?\s+|a\s+)?press(?:ao)\s*(?:atmosferica|atual|agora|no\s+momento)?"
    r"|como\s+esta\s+a\s+press(?:ao)"
    r"|press(?:ao)\s+(?:agora|atual|no\s+momento|atmosferica)"
)

# Nivel do rio / piezometro atual (hoje exposto por poucas estacoes)
_PAT_NIVEL_RIO = re.compile(
    r"qual\s+(?:e\s+o?\s+|o\s+)?nivel\s+(?:do|de)\s+(?:rio|agua)"
    r"|como\s+esta\s+o\s+nivel\s+(?:do|de)\s+(?:rio|agua)"
    r"|nivel\s+(?:do|de)\s+(?:rio|agua)"
    r"|piezometro"
)

# Ranking de chuva: estacao com mais/menos chuva acumulada
_PAT_CHUVA_RANKING = re.compile(
    r"qual\s+(?:a\s+)?(?:estacao|local|bairro)\s+(?:tem|teve|esta\s+com)\s+mais\s+chuva"
    r"|onde\s+(?:esta\s+)?choveu?\s+mais"
    r"|onde\s+(?:esta\s+)?chove\s+mais"
    r"|qual\s+(?:a\s+)?(?:estacao|local|bairro)\s+(?:com|de)\s+mais\s+chuva"
    r"|mais\s+chuva\s+acumulada"
    r"|chuva\s+acumulada\s+(?:hoje|agora)"
    r"|qual\s+(?:estacao|local|bairro)\s+(?:chove|choveu)\s+mais"
    r"|(?:estacao|local|bairro)\s+mais\s+chuvos"
    r"|onde\s+(?:esta|tem)\s+chovendo\s+mais"
    r"|maior\s+(?:acumulo|acumulado|volume)\s+de\s+chuva"
    r"|estacao\s+(?:tem|teve|com)\s+mais\s+chuva"
    r"|tem\s+mais\s+chuva\s+acumulada"
)


# ── Handlers pre-SLM: consultas genericas de tempo real ──────────────────────

def _handle_temp_atual(stations):
    """Temperatura media das estacoes, estacao mais quente e mais fria."""
    valid = [(s.get("name", "?"), s["temp"]) for s in stations if s.get("temp") is not None]
    if not valid:
        return "Nao ha dados de temperatura disponiveis no momento."
    avg = sum(v for _, v in valid) / len(valid)
    hottest = max(valid, key=lambda x: x[1])
    coldest = min(valid, key=lambda x: x[1])
    return (
        f"Temperatura media: {avg:.1f}°C ({len(valid)} estacoes). "
        f"Mais quente: {hottest[0]} ({hottest[1]:.1f}°C). "
        f"Mais fria: {coldest[0]} ({coldest[1]:.1f}°C)."
    )


def _handle_umidade_atual(stations):
    """Umidade media das estacoes, estacao mais umida e mais seca."""
    valid = [(s.get("name", "?"), s["humi"]) for s in stations if s.get("humi") is not None]
    if not valid:
        return "Nao ha dados de umidade disponiveis no momento."
    avg = sum(v for _, v in valid) / len(valid)
    wettest = max(valid, key=lambda x: x[1])
    driest  = min(valid, key=lambda x: x[1])
    return (
        f"Umidade media: {avg:.0f}% ({len(valid)} estacoes). "
        f"Mais umida: {wettest[0]} ({wettest[1]:.0f}%). "
        f"Mais seca: {driest[0]} ({driest[1]:.0f}%)."
    )


def _handle_vento_atual(stations):
    """
    Vento medio, estacao mais ventosa e maior rajada.
    Aceita contrato real do Plugfield (wind/gust) com aliases defensivos (wind_speed/wind_gust).
    """
    def _wind(s):
        v = s.get("wind")
        if v is None:
            v = s.get("wind_speed")
        return float(v) if v is not None else None

    def _gust(s):
        g = s.get("gust")
        if g is None:
            g = s.get("wind_gust")
        return float(g) if g is not None else None

    valid_wind = [(s.get("name", "?"), _wind(s)) for s in stations if _wind(s) is not None]
    if not valid_wind:
        return "Nao ha dados de vento disponiveis no momento."
    avg = sum(v for _, v in valid_wind) / len(valid_wind)
    windiest = max(valid_wind, key=lambda x: x[1])

    gust_vals = [(s.get("name", "?"), _gust(s)) for s in stations if _gust(s) is not None]
    max_gust  = max(gust_vals, key=lambda x: x[1]) if gust_vals else None

    msg = (
        f"Vento medio: {avg:.1f} km/h. "
        f"Mais ventosa: {windiest[0]} ({windiest[1]:.1f} km/h)."
    )
    if max_gust:
        msg += f" Maior rajada: {max_gust[0]} ({max_gust[1]:.1f} km/h)."
    return msg


def _handle_pressao_atual(stations):
    """Pressao media das estacoes, estacao com maior e menor pressao."""
    valid = [(s.get("name", "?"), s["pres"]) for s in stations if s.get("pres") is not None]
    if not valid:
        return "Nao ha dados de pressao disponiveis no momento."
    avg = sum(v for _, v in valid) / len(valid)
    highest = max(valid, key=lambda x: x[1])
    lowest  = min(valid, key=lambda x: x[1])
    return (
        f"Pressao media: {avg:.0f} hPa ({len(valid)} estacoes). "
        f"Maior: {highest[0]} ({highest[1]:.0f} hPa). "
        f"Menor: {lowest[0]} ({lowest[1]:.0f} hPa)."
    )


def _handle_nivel_rio(stations, query: str = ""):
    """Nivel atual do rio/piezometro, priorizando a estacao citada na pergunta."""
    valid = [s for s in stations if s.get("river_level") is not None]
    if not valid:
        return "Nao ha dados de nivel do rio disponiveis no momento."

    try:
        from plugfield_client import _extract_place_terms
        terms = _extract_place_terms(query)
    except Exception:
        terms = []

    chosen = None
    if terms:
        for station in valid:
            name_norm = _strip_accents(str(station.get("name", "")))
            if all(_strip_accents(term) in name_norm for term in terms):
                chosen = station
                break
    if chosen is None:
        chosen = valid[0]

    unit = chosen.get("river_level_unit") or "mca"
    return (
        f"Nivel do rio na estacao {chosen.get('name', '?')}: "
        f"{float(chosen['river_level']):.2f} {unit} no momento."
    )


def _handle_chuva_ranking(stations):
    """Estacao com maior chuva acumulada hoje (rain_day)."""
    valid = [(s.get("name", "?"), s.get("rain_day") or 0.0) for s in stations]
    raining = [(name, val) for name, val in valid if val > 0.0]
    if not raining:
        return "Nenhuma estacao registra chuva acumulada no momento."
    top = sorted(raining, key=lambda x: x[1], reverse=True)
    top3 = top[:3]
    top3_str = ", ".join(f"{name} ({val:.1f} mm)" for name, val in top3)
    total_raining = len(raining)
    total = len(valid)
    return (
        f"Chuva acumulada hoje: {total_raining}/{total} estacoes com registro. "
        f"Mais chuva: {top3_str}."
    )


# ── Dispatcher principal ─────────────────────────────────────────────────────

def handle_analytical_query(query: str) -> Optional[Tuple[str, str]]:
    """
    Tenta responder a query deterministicamente, sem chamar o SLM.

    Retorna (resposta, nome_handler) se reconhecer um padrão analítico,
    ou None para deixar o fluxo normal (intent + SLM) assumir.

    Prioridade de avaliação:
      1. bairros com chuva agora
      2. maior/menor [métrica]
      3. resumo / panorama do clima
      4. bairro ambíguo (não encontrado entre as estações)
    """
    qs = _strip_accents(query)  # sem acentos para matching robusto

    # Prioridade 0: metricas genericas de tempo real (pre-SLM)
    _pre_slm = [
        (_PAT_TEMP_ATUAL,      _handle_temp_atual,      "temp_atual"),
        (_PAT_UMIDADE_ATUAL,   _handle_umidade_atual,   "umidade_atual"),
        (_PAT_VENTO_ATUAL,     _handle_vento_atual,     "vento_atual"),
        (_PAT_PRESSAO_ATUAL,   _handle_pressao_atual,   "pressao_atual"),
        (_PAT_NIVEL_RIO,       _handle_nivel_rio,       "nivel_rio"),
        (_PAT_CHUVA_RANKING,   _handle_chuva_ranking,   "chuva_ranking"),
    ]
    for _pat, _fn, _nm in _pre_slm:
        if _pat.search(qs):
            _st = _fetch_all_stations_safe()
            if _st:
                if _nm == "nivel_rio":
                    return _fn(_st, qs), _nm
                return _fn(_st), _nm
            return None

    is_rain_bairros = bool(_PAT_RAIN_BAIRROS.search(qs))
    is_rain_region  = bool(_PAT_RAIN_REGION.search(qs))
    is_extremes     = bool(_PAT_EXTREME_SIGNAL.search(qs) and _PAT_METRIC.search(qs))
    is_summary      = bool(_PAT_SUMMARY.search(qs))
    has_station_sig = bool(_PAT_STATION_SIGNAL.search(qs))

    # Sem nenhum sinal relevante — não interfere no fluxo
    if not (is_rain_bairros or is_rain_region or is_extremes or is_summary or has_station_sig):
        return None

    # Busca estações — se falhar, cai no fluxo normal (SLM)
    stations = _fetch_stations_for_query_safe(query) if is_rain_region else _fetch_all_stations_safe()
    if not stations:
        return None

    if is_rain_bairros or is_rain_region:
        regions = []
        if is_rain_region:
            try:
                from plugfield_client import _extract_regions
                regions = _extract_regions(query)
            except Exception:
                regions = []
        return _handle_rain_bairros(stations, regions=regions or None), "rain_bairros"

    if is_extremes:
        return _handle_extremes(qs, stations), "extremes"

    if is_summary:
        return _handle_summary(stations), "summary"

    if has_station_sig:
        result = _handle_ambiguous_location(qs, stations)
        if result:
            return result, "ambiguous_location"

    return None


@dataclass
class Orchestrator:
    log_path: str = LOG_PATH
    stats: dict = field(default_factory=lambda: {"llm": 0, "fallback": 0})

    # runtime
    max_new_tokens: int = ORCH_MAX_NEW_TOKENS
    do_sample: bool = ORCH_DO_SAMPLE
    json_retries: int = ORCH_JSON_RETRIES

    def _log(self, event: Dict):
        write_jsonl(self.log_path, event)

    def meta_start(self):
        machine = get_machine_info()
        runtime = {
            "hf_num_threads": HF_NUM_THREADS,
            "hf_num_interop": HF_NUM_INTEROP,
            "orch_max_new_tokens": self.max_new_tokens,
            "omp_num_threads": os.getenv("OMP_NUM_THREADS"),
            "mkl_num_threads": os.getenv("MKL_NUM_THREADS"),
            "orch_cls_max_new_tokens": ORCH_CLS_MAX_NEW_TOKENS,
            "orch_self_consist": ORCH_SELF_CONSIST,
            "orch_llm_timeout_s": ORCH_LLM_TIMEOUT_S,
            "orch_strict_llm": ORCH_STRICT_LLM,
            "orch_kw_fallback": ORCH_KW_FALLBACK,
            "orch_enable_rt_override": ORCH_ENABLE_RT_OVERRIDE,
            "orch_enable_pv_override": ORCH_ENABLE_PV_OVERRIDE,
        }
        self._log({
            "type": "meta_start",
            "orchestrator_version": ORCH_VERSION,
            "model_id": HF_MODEL_ID,
            "machine": machine,
            "runtime_params": runtime
        })

    # ---------- LLM JSON ----------
    def _call_llm_json(self, user_text: str) -> Tuple[Optional[Dict], str, Dict, str]:
        """
        Retorna (data_json, raw_text, gen_info, decision_source)
        Pode fazer retries com re-prompt.
        """
        prompt = _render_prompt_for_json(user_text)

        # tentativa 1
        raw1, info1 = _generate_text(prompt, max_new_tokens=ORCH_CLS_MAX_NEW_TOKENS)
        data1 = _extract_best_json_object(raw1)
        if data1 and _normalize_intent(data1.get("intent")) in INTENTS:
            data1["intent"] = _normalize_intent(data1.get("intent"))
            info1["stop_reason"] = info1.get("stop_reason") or "balanced_json"
            return data1, raw1, info1, "llm_json"

        # retries com re-prompt (mais explícito)
        last_raw, last_info, last_data = raw1, info1, data1
        for _ in range(self.json_retries):
            retry_prompt = (
                "Responda APENAS com JSON válido no formato "
                "{\"intent\":\"PREVISAO|ESTACOES_RT|GENERICO\",\"reason\":\"texto curto\"}. "
                "Sem markdown, sem explicações. Usuário: " + user_text.strip()
            )
            raw_r, info_r = _generate_text(retry_prompt, max_new_tokens=ORCH_CLS_MAX_NEW_TOKENS)
            data_r = _extract_best_json_object(raw_r)
            if data_r and _normalize_intent(data_r.get("intent")) in INTENTS:
                data_r["intent"] = _normalize_intent(data_r.get("intent"))
                info_r["stop_reason"] = info_r.get("stop_reason") or "balanced_json"
                return data_r, raw_r, info_r, "llm_json"
            last_raw, last_info, last_data = raw_r, info_r, data_r

        # falha
        return None, (last_raw or raw1), (last_info or info1), "llm_json_failed"

    # ---------- Heurística/override ----------
    def _override_by_keywords(self, text: str) -> Optional[Tuple[str, str]]:
        """
        Retorna (intent, reason_override) se houver override forte; caso contrario, None.
        (Desligado por padrao para modo so LLM)
        """
        has_rt = bool(RT_REGEX.search(text))
        has_pv = bool(PV_REGEX.search(text))
        has_station = bool(ESTAC_REGEX.search(text))
        has_region = bool(REGION_REGEX.search(text))
        has_status = bool(STATUS_REGEX.search(text))

        if ORCH_ENABLE_RT_OVERRIDE:
            if has_rt:
                return "ESTACOES_RT", "override: sinal explicito de tempo real no texto do usuario"
            if has_station and not has_pv:
                return "ESTACOES_RT", "override: sinal de dados operacionais de estacao no texto do usuario"
            if has_region and has_status and not has_pv:
                return "ESTACOES_RT", "override: consulta operacional por regiao no texto do usuario"

        if ORCH_ENABLE_PV_OVERRIDE and has_pv:
            return "PREVISAO", "override: sinal de previsao no texto do usuario"
        return None

    # ---------- Classificação ----------
    def classify_intent(self, entrada: str) -> Tuple[str, str, str, Optional[str], Optional[Dict]]:
        """
        Retorna: (intent, reason, decision_source, llm_raw, gen_info)
        """
        # Override forte por keywords (desligado por padrão)
        ov = self._override_by_keywords(entrada)
        if ov:
            intent, reason = ov
            return intent, f"texto curto ({reason})", "llm_json_override", None, None

        # Somente keywords? (apenas se ORCH_USE_LLM=0)
        if not ORCH_USE_LLM:
            if ESTAC_REGEX.search(entrada) or RT_REGEX.search(entrada):
                return "ESTACOES_RT", "keyword_only", "llm_keywords", None, None
            if PV_REGEX.search(entrada):
                return "PREVISAO", "keyword_only", "llm_keywords", None, None
            return "GENERICO", "keyword_only", "llm_keywords", None, None

        # LLM -> JSON (com retries)
        try:
            data, llm_raw, gen_info, source = self._call_llm_json(entrada)
        except Exception as _llm_exc:
            # LLM levantou excecao (modelo indisponivel, 401, timeout, torch ausente)
            _llm_exc_str = str(_llm_exc)
            self._log({
                "type": "llm_unavailable",
                "orchestrator_version": ORCH_VERSION,
                "reason": _llm_exc_str[:200],
                "torch_ok": _TORCH_OK,
                "kw_fallback": ORCH_KW_FALLBACK,
                "entrada_norm": entrada[:120],
            })
            if ORCH_KW_FALLBACK:
                if PV_REGEX.search(entrada):
                    return "PREVISAO", "kw_fallback:llm_unavailable", "llm_json_override", None, None
                if ESTAC_REGEX.search(entrada) or RT_REGEX.search(entrada):
                    return "ESTACOES_RT", "kw_fallback:llm_unavailable", "llm_json_override", None, None
                return "GENERICO", "kw_fallback:llm_unavailable", "llm_json_override", None, None
            if ORCH_STRICT_LLM:
                raise
            self.stats["fallback"] += 1
            return "GENERICO", "llm_exception", "llm_fail_generic", None, None

        if data:
            self.stats["llm"] += 1
            intent = _normalize_intent(data.get("intent")) or "GENERICO"
            reason = _clean_reason(data.get("reason"))
            return intent, reason, source, llm_raw, gen_info

        # Falhou JSON → Auto-reparo 100% LLM
        lab1, lab1_raw, lab1_info = _call_llm_label_only(entrada)
        if lab1:
            self.stats["llm"] += 1
            llm_raw = (llm_raw or "") + "\n[label_only]\n" + lab1_raw
            return lab1, "llm_label_only", "llm_label_only", llm_raw, lab1_info

        labv, raws = _vote_llm_label_only(entrada, ORCH_SELF_CONSIST)
        if labv:
            self.stats["llm"] += 1
            llm_raw = (llm_raw or "") + "\n[label_vote]\n" + "\n---\n".join(raws)
            return labv, "llm_vote", "llm_vote", llm_raw, {"llm_ms": None, "new_tokens": None, "stop_reason": "vote"}

        # Strict?
        if ORCH_STRICT_LLM:
            raise RuntimeError("LLM falhou e o fallback esta desativado (ORCH_STRICT_LLM=1).")

        # Registra no audit log que o LLM falhou todos os retries
        self._log({
            "type": "llm_fallback_event",
            "orchestrator_version": ORCH_VERSION,
            "reason": "llm_failed_all_retries",
            "orch_kw_fallback": ORCH_KW_FALLBACK,
            "entrada_preview": entrada[:120],
        })

        # Fallback final SEM keywords
        self.stats["fallback"] += 1
        return "GENERICO", "llm_default_generic", "llm_fail_generic", llm_raw, gen_info

    # ---------- Roteamento ----------
    def route(self, msg: str, user_id: str) -> Tuple[str, str, List[str], str]:
        """
        Executa a rota e loga o evento.
        Retorna: final_output, intent, sensitivity_labels, engine
        """
        t0 = time.time()

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        perfil = api_perfil(user_id)
        entrada_norm = pre_mask_for_llm(sanitize(msg))

        # ── Camada pré-SLM: handlers determinísticos ──────────────────
        # Intercepta consultas analíticas bem-definidas sem chamar o Gemma 2.
        # Se a API de estações falhar ou a query não bater em nenhum padrão,
        # retorna None e o fluxo normal (classify_intent + SLM) assume.
        _analytical = handle_analytical_query(entrada_norm)
        if _analytical is not None:
            raw, _handler_name  = _analytical
            intent              = "ESTACOES_RT"
            reason              = f"deterministic:{_handler_name}"
            decision_source     = "deterministic"
            engine              = f"deterministic:{_handler_name}"
            llm_raw             = None
            gen_info            = None
        else:
            # SLM: classifica intencao + roteia
            intent, reason, decision_source, llm_raw, gen_info = self.classify_intent(entrada_norm)

            if intent == "PREVISAO":
                raw = api_previsao(entrada_norm, perfil)
            elif intent == "ESTACOES_RT":
                raw = api_estacoes(entrada_norm, perfil)
            else:
                raw = llm_generico(entrada_norm, perfil)
            engine = f"hf:{HF_MODEL_ID}"

        labels = detect_sensitivity(raw)
        final = mask_text(raw)

        latency_ms = int((time.time() - t0) * 1000)

        # monta evento
        event = {
            "orchestrator_version": ORCH_VERSION,
            "engine": engine,
            "decision_source": decision_source,
            "user_id_hash": perfil["user_id_hash"],
            "session_id": session_id,
            "perfil": {
                "papel": perfil["papel"],
                "permissoes": perfil["permissoes"],
                "idioma": perfil["idioma"],
                "loc": perfil["loc"],
                "policy_version": perfil["policy_version"],
            },
            "entrada_norm": entrada_norm,
            "intent": intent,
            "reason": reason,
            "raw_output": raw,
            "sensitivity_labels": labels,
            "final_output": final,
            "latency_ms": latency_ms,
        }

        # logging da resposta bruta do LLM + metricas de geracao
        if ORCH_INCLUDE_LLM_RAW and llm_raw is not None:
            if ORCH_LLM_RAW_MAXCHARS > 0 and len(llm_raw) > ORCH_LLM_RAW_MAXCHARS:
                event["llm_raw"] = llm_raw[:ORCH_LLM_RAW_MAXCHARS] + "…[trunc]"
            else:
                event["llm_raw"] = llm_raw

        if isinstance(gen_info, dict):
            if gen_info.get("llm_ms") is not None:
                event["llm_ms"] = gen_info["llm_ms"]
            if gen_info.get("new_tokens") is not None:
                event["llm_new_tokens"] = gen_info["new_tokens"]
            if gen_info.get("stop_reason") is not None:
                event["llm_stop_reason"] = gen_info["stop_reason"]

        self._log(event)
        return final, intent, labels, engine
