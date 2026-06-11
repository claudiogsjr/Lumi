# app.py
import os
import json
import time
import threading
import uuid
import datetime as dt
import shutil
from functools import wraps
from flask import Flask, request, jsonify, Response, send_from_directory, session, redirect
import psutil
from orchestrator_hf_json_final import Orchestrator, _warmup, write_jsonl, LOG_PATH, ORCH_VERSION

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    RealDictCursor = None

APP_ENV = os.getenv("APP_ENV", "local").strip().lower()


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Configure {name} no ambiente antes de iniciar em producao.")
    return value


app = Flask(__name__)

# WhatsApp webhook blueprint
from whatsapp_webhook import whatsapp_bp  # noqa: E402
app.register_blueprint(whatsapp_bp)

if APP_ENV == "production":
    app.secret_key = _required_env("FLASK_SECRET_KEY")
else:
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
FRONTEND_DIST_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")

USER_LOG_PATH = os.getenv("USER_LOG_PATH", "user_interactions.jsonl")
USABILITY_SESSIONS_PATH = os.getenv("USABILITY_SESSIONS_PATH", "usability_sessions.jsonl")
USABILITY_CHAT_LOGS_PATH = os.getenv("USABILITY_CHAT_LOGS_PATH", "usability_chat_logs.jsonl")
USABILITY_SURVEYS_PATH = os.getenv("USABILITY_SURVEYS_PATH", "usability_surveys.jsonl")
ADMIN_PHONES_PATH = os.getenv("ADMIN_PHONES_PATH", "admin_phones.jsonl")
STATE_LOCK = threading.Lock()
CURRENT_MODE = "hybrid"
CURRENT_CFG = "robust"
POSTGRES_ENABLED = os.getenv("POSTGRES_ENABLED", "0") == "1"
PGHOST = os.getenv("PGHOST", "")
PGPORT = int(os.getenv("PGPORT", "5432"))
PGDATABASE = os.getenv("PGDATABASE", "")
PGUSER = os.getenv("PGUSER", "")
PGPASSWORD = os.getenv("PGPASSWORD", "")
PGSSLMODE = os.getenv("PGSSLMODE", "require")
_DB_INIT_DONE = False
_DB_INIT_LOCK = threading.Lock()
DASHBOARD_ACCESS_TOKEN = (
    _required_env("DASHBOARD_ACCESS_TOKEN")
    if APP_ENV == "production"
    else os.getenv("DASHBOARD_ACCESS_TOKEN", "dev-only-dashboard-token").strip()
)


def _sanitize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _request_id() -> str:
    return request.headers.get("X-Request-ID") or str(uuid.uuid4())


@app.after_request
def _add_response_headers(response):
    response.headers.setdefault("X-Request-ID", getattr(request, "request_id", _request_id()))
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.before_request
def _attach_request_id():
    request.request_id = _request_id()


def _read_jsonl(path: str):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _append_jsonl(path: str, obj: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _auth_payload():
    user = session.get("auth_user")
    if not isinstance(user, dict):
        return None
    return {
        "name": user.get("name") or "Dashboard",
        "provider": "manual_token",
    }


def _interaction_session_id():
    session_id = session.get("interaction_session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        session["interaction_session_id"] = session_id
        session.permanent = True
    return session_id


def _auth_error():
    return jsonify({"error": "Nao autenticado.", "request_id": request.request_id}), 401


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _auth_payload():
            return _auth_error()
        return fn(*args, **kwargs)

    return wrapper


def _verify_dashboard_token(token: str):
    candidate = str(token or "").strip()
    if not candidate:
        raise ValueError("Token de acesso obrigatorio.")
    if candidate != DASHBOARD_ACCESS_TOKEN:
        raise PermissionError("Token de acesso invalido.")
    return {
        "name": "Administrador",
    }


def _system_health_payload():
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    cpu_pct = psutil.cpu_percent(interval=0.2)
    mem_pct = round(vm.percent, 1)
    disk_pct = round((disk.used / disk.total) * 100, 1) if disk.total else None
    gib = 1024 ** 3
    return {
        "cpu_percent": round(cpu_pct, 1),
        "memory_percent": mem_pct,
        "memory_used_gb": round(vm.used / gib, 2),
        "memory_total_gb": round(vm.total / gib, 2),
        "disk_percent": disk_pct,
        "disk_used_gb": round(disk.used / gib, 2),
        "disk_total_gb": round(disk.total / gib, 2),
        "host": os.getenv("HOSTNAME") or os.getenv("COMPUTERNAME") or "",
        "ts": _now_iso(),
    }


def _postgres_ready() -> bool:
    return bool(
        POSTGRES_ENABLED
        and psycopg2 is not None
        and PGHOST
        and PGDATABASE
        and PGUSER
        and PGPASSWORD
    )


def _db_conn():
    if not _postgres_ready():
        return None
    return psycopg2.connect(
        host=PGHOST,
        port=PGPORT,
        dbname=PGDATABASE,
        user=PGUSER,
        password=PGPASSWORD,
        sslmode=PGSSLMODE,
    )


def _ensure_db_schema():
    global _DB_INIT_DONE
    if not _postgres_ready() or _DB_INIT_DONE:
        return
    with _DB_INIT_LOCK:
        if _DB_INIT_DONE:
            return
        conn = _db_conn()
        if conn is None:
            return
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS usability_sessions (
                            session_id UUID PRIMARY KEY,
                            consent_accepted BOOLEAN NOT NULL,
                            started_at TIMESTAMPTZ,
                            finished_at TIMESTAMPTZ,
                            status TEXT NOT NULL,
                            privacy_mode TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS usability_chat_logs (
                            id UUID PRIMARY KEY,
                            session_id UUID NOT NULL REFERENCES usability_sessions(session_id) ON DELETE CASCADE,
                            timestamp TIMESTAMPTZ,
                            user_message TEXT NOT NULL,
                            assistant_response TEXT NOT NULL,
                            response_time_ms DOUBLE PRECISION,
                            route_or_intent TEXT,
                            had_rephrase BOOLEAN NOT NULL DEFAULT FALSE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS usability_surveys (
                            id UUID PRIMARY KEY,
                            session_id UUID NOT NULL REFERENCES usability_sessions(session_id) ON DELETE CASCADE,
                            clarity_score INTEGER NOT NULL CHECK (clarity_score BETWEEN 1 AND 5),
                            usefulness_score INTEGER NOT NULL CHECK (usefulness_score BETWEEN 1 AND 5),
                            adequacy_score INTEGER NOT NULL CHECK (adequacy_score BETWEEN 1 AND 5),
                            ease_of_use_score INTEGER NOT NULL CHECK (ease_of_use_score BETWEEN 1 AND 5),
                            satisfaction_score INTEGER NOT NULL CHECK (satisfaction_score BETWEEN 1 AND 5),
                            comment TEXT,
                            submitted_at TIMESTAMPTZ NOT NULL
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_interactions (
                            id UUID PRIMARY KEY,
                            ts TEXT,
                            session_id TEXT,
                            user_id TEXT,
                            message TEXT NOT NULL,
                            expected_intent TEXT,
                            response TEXT,
                            intent TEXT,
                            passed BOOLEAN,
                            sensitivity_labels JSONB,
                            engine TEXT,
                            latency_ms DOUBLE PRECISION,
                            decision_source TEXT,
                            reason TEXT,
                            llm_ms DOUBLE PRECISION,
                            llm_new_tokens INTEGER,
                            llm_stop_reason TEXT,
                            entrada_norm TEXT,
                            raw_output TEXT,
                            final_output TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_usability_chat_logs_session_id ON usability_chat_logs(session_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_usability_surveys_session_id ON usability_surveys(session_id)")
                    cur.execute("ALTER TABLE user_interactions ADD COLUMN IF NOT EXISTS session_id TEXT")
                    cur.execute("ALTER TABLE user_interactions ALTER COLUMN user_id DROP NOT NULL")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_interactions_session_id ON user_interactions(session_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_interactions_user_id ON user_interactions(user_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_interactions_intent ON user_interactions(intent)")
            _DB_INIT_DONE = True
        finally:
            conn.close()


def _upsert_usability_session_db(rec: dict):
    if not _postgres_ready():
        return
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usability_sessions (
                        session_id, consent_accepted, started_at, finished_at, status, privacy_mode
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        consent_accepted = COALESCE(EXCLUDED.consent_accepted, usability_sessions.consent_accepted),
                        started_at = COALESCE(usability_sessions.started_at, EXCLUDED.started_at),
                        finished_at = COALESCE(EXCLUDED.finished_at, usability_sessions.finished_at),
                        status = EXCLUDED.status,
                        privacy_mode = COALESCE(EXCLUDED.privacy_mode, usability_sessions.privacy_mode),
                        updated_at = NOW()
                    """,
                    (
                        rec["session_id"],
                        rec.get("consent_accepted"),
                        rec.get("started_at"),
                        rec.get("finished_at"),
                        rec.get("status"),
                        rec.get("privacy_mode"),
                    ),
                )
    finally:
        conn.close()


def _finish_usability_session_db(session_id: str, finished_at: str):
    if not _postgres_ready():
        return
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE usability_sessions SET finished_at = %s, status = 'finished' WHERE session_id = %s",
                    (finished_at, session_id),
                )
    except Exception as e:
        logger.warning("_finish_usability_session_db failed: %s", e)
    finally:
        conn.close()


def _insert_usability_chat_log_db(rec: dict):
    if not _postgres_ready():
        return
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usability_chat_logs (
                        id, session_id, timestamp, user_message, assistant_response,
                        response_time_ms, route_or_intent, had_rephrase, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        rec["id"],
                        rec["session_id"],
                        rec.get("timestamp"),
                        rec["user_message"],
                        rec["assistant_response"],
                        rec.get("response_time_ms"),
                        rec.get("route_or_intent"),
                        rec.get("had_rephrase", False),
                    ),
                )
    finally:
        conn.close()


def _insert_usability_survey_db(rec: dict):
    if not _postgres_ready():
        return
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usability_surveys (
                        id, session_id, clarity_score, usefulness_score, adequacy_score,
                        ease_of_use_score, satisfaction_score, comment, submitted_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        rec["id"],
                        rec["session_id"],
                        rec["clarity_score"],
                        rec["usefulness_score"],
                        rec["adequacy_score"],
                        rec["ease_of_use_score"],
                        rec["satisfaction_score"],
                        rec.get("comment"),
                        rec["submitted_at"],
                    ),
                )
    finally:
        conn.close()


def _insert_user_interaction_db(rec: dict):
    if not _postgres_ready():
        return
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_interactions (
                        id, ts, session_id, user_id, message, expected_intent, response, intent, passed,
                        sensitivity_labels, engine, latency_ms, decision_source, reason, llm_ms,
                        llm_new_tokens, llm_stop_reason, entrada_norm, raw_output, final_output
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        rec["id"],
                        rec.get("ts"),
                        rec.get("session_id"),
                        rec.get("user_id"),
                        rec["message"],
                        rec.get("expected_intent"),
                        rec.get("response"),
                        rec.get("intent"),
                        rec.get("passed"),
                        json.dumps(rec.get("sensitivity_labels")) if rec.get("sensitivity_labels") is not None else None,
                        rec.get("engine"),
                        rec.get("latency_ms"),
                        rec.get("decision_source"),
                        rec.get("reason"),
                        rec.get("llm_ms"),
                        rec.get("llm_new_tokens"),
                        rec.get("llm_stop_reason"),
                        rec.get("entrada_norm"),
                        rec.get("raw_output"),
                        rec.get("final_output"),
                    ),
                )
    finally:
        conn.close()


def _fetch_user_logs_db(limit: int, q_session: str = "", q_intent: str = "", q_passed: str = ""):
    if not _postgres_ready():
        return None
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return None
    try:
        where = []
        params = []
        if q_session:
            where.append("COALESCE(session_id, user_id) = %s")
            params.append(q_session)
        if q_intent:
            where.append("UPPER(COALESCE(intent, '')) = %s")
            params.append(q_intent)
        if q_passed in {"true", "false"}:
            where.append("COALESCE(passed, FALSE) = %s")
            params.append(q_passed == "true")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT
                ts, COALESCE(session_id, user_id) AS session_id, user_id, message, expected_intent, response, intent, passed,
                sensitivity_labels, engine, latency_ms, decision_source, reason, llm_ms,
                llm_new_tokens, llm_stop_reason, entrada_norm, raw_output, final_output
            FROM user_interactions
            {clause}
            ORDER BY created_at DESC
            LIMIT %s
        """
        params.append(limit)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]
            rows.reverse()
            return rows
    finally:
        conn.close()


# ── Admin phones ────��────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Remove tudo que nao e digito."""
    return re.sub(r"\D", "", str(phone or ""))


def _list_admin_phones_db():
    """Retorna lista de dicts ou None se DB indisponivel."""
    if not _postgres_ready():
        return None
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT phone_number, name, active, created_at::text FROM admin_phones ORDER BY created_at"
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning("_list_admin_phones_db failed: %s", e)
        return None
    finally:
        conn.close()


def _add_admin_phone_db(phone: str, name: str = "") -> bool:
    if not _postgres_ready():
        return False
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_phones (phone_number, name, active)
                    VALUES (%s, %s, TRUE)
                    ON CONFLICT (phone_number) DO UPDATE
                        SET name = EXCLUDED.name, active = TRUE
                    """,
                    (phone, name),
                )
        return True
    except Exception as e:
        logger.warning("_add_admin_phone_db failed: %s", e)
        return False
    finally:
        conn.close()


def _remove_admin_phone_db(phone: str) -> bool:
    if not _postgres_ready():
        return False
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE admin_phones SET active = FALSE WHERE phone_number = %s",
                    (phone,),
                )
                return cur.rowcount > 0
    except Exception as e:
        logger.warning("_remove_admin_phone_db failed: %s", e)
        return False
    finally:
        conn.close()


def _is_admin_phone(phone: str) -> bool:
    """Retorna True se o numero (normalizado) e admin ativo."""
    normalized = _normalize_phone(phone)
    if not normalized:
        return False
    if _postgres_ready():
        conn = _db_conn()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM admin_phones WHERE phone_number = %s AND active = TRUE",
                        (normalized,),
                    )
                    return cur.fetchone() is not None
            except Exception:
                pass
            finally:
                conn.close()
    for rec in _read_jsonl(ADMIN_PHONES_PATH):
        if isinstance(rec, dict) and rec.get("active") and _normalize_phone(rec.get("phone_number", "")) == normalized:
            return True
    return False


def _list_admin_phones_jsonl():
    return _read_jsonl(ADMIN_PHONES_PATH)


def _aggregate_results_data_db():
    logs = _fetch_user_logs_db(limit=1000000)
    if logs is None:
        return None
    return _build_results_payload(logs)


def _build_results_payload(rows):
    items = [r for r in rows if isinstance(r, dict) and r.get("expected_intent") and r.get("intent")]
    labels = ["PREVISAO", "ESTACOES_RT", "GENERICO"]
    label_set = set(labels)

    y_true = []
    y_pred = []
    latencies = []
    source_counts = {}
    for r in items:
        exp = str(r.get("expected_intent")).upper()
        pred = str(r.get("intent")).upper()
        if exp not in label_set or pred not in label_set:
            continue
        y_true.append(exp)
        y_pred.append(pred)
        if r.get("latency_ms") is not None:
            try:
                latencies.append(float(r.get("latency_ms")))
            except Exception:
                pass
        src = r.get("decision_source") or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1

    n = len(y_true)
    accuracy = None
    if n:
        accuracy = round(sum(1 for a, b in zip(y_true, y_pred) if a == b) / n, 4)

    idx = {lab: i for i, lab in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for a, b in zip(y_true, y_pred):
        matrix[idx[a]][idx[b]] += 1

    f1s = []
    for lab in labels:
        i = idx[lab]
        tp = matrix[i][i]
        fp = sum(matrix[r][i] for r in range(len(labels)) if r != i)
        fn = sum(matrix[i][c] for c in range(len(labels)) if c != i)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        f1s.append(f1)
    macro_f1 = round(sum(f1s) / len(f1s), 4) if f1s else None

    latency_mean = round(sum(latencies) / len(latencies), 2) if latencies else None
    lat_sorted = sorted(latencies)
    def _pct(p):
        if not lat_sorted:
            return None
        k = int(round((p / 100.0) * (len(lat_sorted) - 1)))
        return round(lat_sorted[k], 2)
    p50 = _pct(50)
    p95 = _pct(95)

    bins = []
    if lat_sorted:
        min_v = min(lat_sorted)
        max_v = max(lat_sorted)
        if max_v == min_v:
            edges = [min_v, max_v + 1]
        else:
            step = max(1.0, (max_v - min_v) / 8.0)
            edges = [min_v + i * step for i in range(9)]
        counts = [0 for _ in range(len(edges) - 1)]
        for v in lat_sorted:
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1]:
                    counts[i] += 1
                    break
        for i in range(len(counts)):
            label = f"{int(edges[i])}-{int(edges[i+1])}"
            bins.append({"label": label, "count": counts[i]})

    return {
        "metrics": {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "latency_mean_ms": latency_mean,
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
            "n": n,
        },
        "confusion": {
            "labels": labels,
            "matrix": matrix,
        },
        "latency": {
            "bins": bins
        },
        "source_dist": {
            "items": [{"source": k, "count": v} for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)]
        }
    }


def _get_session_state_db(session_id: str):
    if not _postgres_ready():
        return None
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT session_id, consent_accepted, started_at, finished_at, status, privacy_mode
                FROM usability_sessions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def _aggregate_usability_db():
    if not _postgres_ready():
        return None
    _ensure_db_schema()
    conn = _db_conn()
    if conn is None:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*)::int AS n,
                    ROUND(AVG(clarity_score)::numeric, 3) AS clarity_score,
                    ROUND(AVG(usefulness_score)::numeric, 3) AS usefulness_score,
                    ROUND(AVG(adequacy_score)::numeric, 3) AS adequacy_score,
                    ROUND(AVG(ease_of_use_score)::numeric, 3) AS ease_of_use_score,
                    ROUND(AVG(satisfaction_score)::numeric, 3) AS satisfaction_score
                FROM usability_surveys
            """)
            summary = dict(cur.fetchone() or {})
            n = summary.get("n") or 0
            if n == 0:
                return {
                    "n": 0,
                    "averages": {},
                    "distributions": {},
                    "comments": [],
                    "sessions": {
                        "started": 0,
                        "finished": 0,
                        "completion_rate": None,
                        "avg_chat_turns": None,
                    },
                    "routes": [],
                }

            distribution_fields = [
                "clarity_score",
                "usefulness_score",
                "adequacy_score",
                "ease_of_use_score",
                "satisfaction_score",
            ]
            distributions = {}
            for field in distribution_fields:
                cur.execute(
                    f"""
                    SELECT {field} AS score, COUNT(*)::int AS count
                    FROM usability_surveys
                    GROUP BY {field}
                    ORDER BY {field}
                    """
                )
                counts = {i: 0 for i in range(1, 6)}
                for row in cur.fetchall():
                    counts[int(row["score"])] = int(row["count"])
                distributions[field] = [
                    {
                        "score": score,
                        "count": counts[score],
                        "pct": round((counts[score] / n) * 100, 2) if n else 0.0,
                    }
                    for score in range(1, 6)
                ]

            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE started_at IS NOT NULL)::int AS started,
                    COUNT(*) FILTER (WHERE finished_at IS NOT NULL)::int AS finished,
                    ROUND(AVG(turns.turn_count)::numeric, 2) AS avg_chat_turns
                FROM usability_sessions s
                LEFT JOIN (
                    SELECT session_id, COUNT(*)::int AS turn_count
                    FROM usability_chat_logs
                    GROUP BY session_id
                ) turns ON turns.session_id = s.session_id
            """)
            session_stats = dict(cur.fetchone() or {})
            started = session_stats.get("started") or 0
            finished = session_stats.get("finished") or 0
            completion_rate = round((finished / started) * 100, 2) if started else None

            cur.execute("""
                SELECT COALESCE(UPPER(route_or_intent), 'UNKNOWN') AS route, COUNT(*)::int AS count
                FROM usability_chat_logs
                GROUP BY COALESCE(UPPER(route_or_intent), 'UNKNOWN')
                ORDER BY count DESC, route
            """)
            routes = [dict(row) for row in cur.fetchall()]

            cur.execute("""
                SELECT session_id::text, comment, submitted_at::text
                FROM usability_surveys
                WHERE comment IS NOT NULL AND BTRIM(comment) <> ''
                ORDER BY submitted_at DESC
                LIMIT 10
            """)
            comments = [dict(row) for row in cur.fetchall()]

            return {
                "n": n,
                "averages": {
                    "clarity_score": summary.get("clarity_score"),
                    "usefulness_score": summary.get("usefulness_score"),
                    "adequacy_score": summary.get("adequacy_score"),
                    "ease_of_use_score": summary.get("ease_of_use_score"),
                    "satisfaction_score": summary.get("satisfaction_score"),
                },
                "distributions": distributions,
                "comments": comments,
                "sessions": {
                    "started": started,
                    "finished": finished,
                    "completion_rate": completion_rate,
                    "avg_chat_turns": session_stats.get("avg_chat_turns"),
                },
                "routes": routes,
            }
    finally:
        conn.close()


def _get_session_state(session_id: str):
    row = _get_session_state_db(session_id)
    if row:
        return row
    rows = _read_jsonl(USABILITY_SESSIONS_PATH)
    current = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("session_id") != session_id:
            continue
        event = r.get("event")
        if event == "start":
            current = dict(r)
        elif event == "finish" and current is not None:
            current["finished_at"] = r.get("finished_at")
            current["status"] = r.get("status", "finished")
    return current


def _tail_last_event_for_prompt(log_path: str, entrada_norm: str):
    rows = _read_jsonl(log_path)
    entrada_norm = _sanitize(entrada_norm)
    for ev in reversed(rows):
        if not isinstance(ev, dict):
            continue
        if ev.get("type") in {"meta_start", "error"}:
            continue
        if _sanitize(ev.get("entrada_norm", "")) == entrada_norm:
            return ev
    return None


def _apply_env(envs: dict):
    for k, v in envs.items():
        os.environ[str(k)] = str(v)


def _env_for_mode(mode: str) -> dict:
    m = (mode or "").strip().lower()
    base = {
        "ORCH_USE_LLM": "1",
        "ORCH_STRICT_LLM": "0",
        "ORCH_ENABLE_RT_OVERRIDE": "0",
        "ORCH_ENABLE_PV_OVERRIDE": "0",
    }
    if m == "llm_only":
        base.update({
            "ORCH_USE_LLM": "1",
            "ORCH_STRICT_LLM": "1",
            "ORCH_ENABLE_RT_OVERRIDE": "0",
            "ORCH_ENABLE_PV_OVERRIDE": "0",
        })
    elif m == "kw_only":
        base.update({
            "ORCH_USE_LLM": "0",
            "ORCH_STRICT_LLM": "0",
            "ORCH_ENABLE_RT_OVERRIDE": "0",
            "ORCH_ENABLE_PV_OVERRIDE": "0",
        })
    elif m == "hybrid":
        base.update({
            "ORCH_USE_LLM": "1",
            "ORCH_STRICT_LLM": "0",
            "ORCH_ENABLE_RT_OVERRIDE": "1",
            "ORCH_ENABLE_PV_OVERRIDE": "1",
        })
    return base


def _env_for_cfg(cfg: str) -> dict:
    c = (cfg or "").strip().lower()
    if c == "t14_tok64_quant1":
        return {
            "HF_NUM_THREADS": "14",
            "HF_NUM_INTEROP": "1",
            "OMP_NUM_THREADS": "14",
            "MKL_NUM_THREADS": "14",
            "ORCH_MAX_NEW_TOKENS": "84",
            "ORCH_JSON_RETRIES": "7",
            "ORCH_SLOW_MODE": "1",
            "ORCH_QUANT_DYNAMIC": "1",
        }
    if c == "t14_tok64_quant0":
        return {
            "HF_NUM_THREADS": "14",
            "HF_NUM_INTEROP": "1",
            "OMP_NUM_THREADS": "14",
            "MKL_NUM_THREADS": "14",
            "ORCH_MAX_NEW_TOKENS": "84",
            "ORCH_JSON_RETRIES": "7",
            "ORCH_SLOW_MODE": "1",
            "ORCH_QUANT_DYNAMIC": "0",
        }
    if c == "t12_tok48":
        return {
            "HF_NUM_THREADS": "12",
            "HF_NUM_INTEROP": "1",
            "ORCH_MAX_NEW_TOKENS": "48",
            "ORCH_JSON_RETRIES": "3",
            "ORCH_SLOW_MODE": "0",
        }
    if c == "robust":
        return _env_for_cfg("t14_tok64_quant1")
    if c == "light":
        return _env_for_cfg("t12_tok48")
    return {}


def _init_orchestrator():
    global orch
    print("Inicializando o orquestrador...")
    orch = Orchestrator()
    orch.meta_start()
    if os.getenv("ORCH_SKIP_WARMUP", "0") == "1":
        print("Warmup inicial desabilitado por ORCH_SKIP_WARMUP=1.")
    else:
        print(f"Pre-carregando modelo HF: {os.getenv('HF_MODEL_ID', 'google/gemma-2-2b-it')} ...")
        _warmup()
    print("Orquestrador e modelo prontos.")


# Carrega o orquestrador uma unica vez quando a aplicacao inicia
orch = None
_init_orchestrator()

INDEX_HTML = """<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Orquestrador Meteo</title>
    <style>
      :root {
        --bg: #f5f7fb;
        --card: #ffffff;
        --text: #0f172a;
        --muted: #5b6473;
        --accent: #2563eb;
        --border: #e5e7eb;
        --ok: #16a34a;
        --fail: #dc2626;
      }
      * { box-sizing: border-box; }
      body {
        font-family: "Space Grotesk", system-ui, sans-serif;
        margin: 0;
        color: var(--text);
        background: var(--bg);
        padding: 22px;
      }
      .wrap { max-width: 980px; margin: 0 auto; }
      .nav {
        display: flex;
        gap: 10px;
        margin-bottom: 14px;
      }
      .nav a {
        text-decoration: none;
        color: var(--text);
        background: var(--card);
        border: 1px solid var(--border);
        padding: 8px 14px;
        border-radius: 999px;
        font-size: 14px;
      }
      .nav a.active { background: var(--accent); color: #fff; border-color: var(--accent); }
      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 10px 24px rgba(15,23,42,.08);
      }
      h1 { margin: 0 0 6px; font-size: 24px; letter-spacing: .3px; }
      p { color: var(--muted); margin-top: 4px; }
      label { display: block; margin-top: 12px; font-weight: 600; font-size: 13px; color: var(--muted); }
      input, textarea, select {
        width: 100%;
        padding: 10px 12px;
        margin-top: 6px;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: #fff;
        color: var(--text);
        outline: none;
      }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
      button {
        padding: 10px 16px;
        border: 0;
        border-radius: 10px;
        background: var(--accent);
        color: #fff;
        cursor: pointer;
        font-weight: 700;
      }
      button.secondary { background: #111827; color: #fff; }
      pre {
        background: #0b1224;
        color: #e5e7eb;
        padding: 12px;
        border-radius: 12px;
        border: 1px solid var(--border);
        overflow: auto;
        font-size: 12px;
      }
      table { width: 100%; border-collapse: collapse; margin-top: 10px; }
      th, td { border-bottom: 1px solid var(--border); padding: 8px; text-align: left; font-size: 12px; }
      th { background: #f3f4f6; color: var(--muted); }
      .pill.ok { color: var(--ok); font-weight: 700; }
      .pill.fail { color: var(--fail); font-weight: 700; }
      @media (max-width: 720px) {
        .row { grid-template-columns: 1fr; }
        body { padding: 14px; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
    <div class="nav">
      <a href="/" class="active">Chat</a>
      <a href="/settings">Parametros</a>
      <a href="/logs">Logs</a>
      <a href="/results">Resultados</a>
    </div>
    <div class="card">
      <h1>Orquestrador Meteo</h1>
      <p>Teste o chat localmente.</p>
      <div class="row">
        <div>
          <label for="user_id">User ID</label>
          <input id="user_id" value="usuario_demo_123"/>
        </div>
        <div>
          <label for="expected_intent">Intent esperada</label>
          <select id="expected_intent">
            <option value="">Selecione...</option>
            <option value="PREVISAO" selected>PREVISAO</option>
            <option value="ESTACOES_RT">ESTACOES_RT</option>
            <option value="GENERICO">GENERICO</option>
          </select>
        </div>
      </div>
      <label for="message">Mensagem</label>
      <textarea id="message" rows="4" placeholder="Ex: previsao para amanha"></textarea>
      <div class="btns">
        <button id="send" type="button" onclick="sendMessage()">Enviar</button>
        <button id="load" class="secondary" type="button" onclick="goLogs()">Ver logs</button>
      </div>
      <p id="js_status" style="font-size:12px;color:#6b7280;margin-top:6px;">JS: aguardando...</p>
      <h3>Resposta</h3>
      <pre id="out">...</pre>
      <p>Visualize logs na aba dedicada.</p>
    </div>
    </div>
    </div>
    <script>
      const setJsStatus = (txt) => {
        const el = document.getElementById('js_status');
        if (el) el.textContent = txt;
      };
      setJsStatus('JS: carregado');

      const sendMessage = async () => {
        const user_id = document.getElementById('user_id').value.trim();
        const message = document.getElementById('message').value.trim();
        const expected_intent = document.getElementById('expected_intent').value.trim();
        const out = document.getElementById('out');
        if (!message) {
          out.textContent = 'digite uma mensagem antes de enviar';
          return;
        }
        if (!expected_intent) {
          out.textContent = 'selecione a intent esperada antes de enviar';
          return;
        }
        out.textContent = 'enviando...';
        try {
          const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id, message, expected_intent })
          });
          if (!res.ok) {
            const t = await res.text();
            out.textContent = `erro HTTP ${res.status}: ${t}`;
            return;
          }
          const data = await res.json();
          if (data && data.error) {
            out.textContent = `Erro: ${data.error}`;
            return;
          }
          const lines = [];
          const passText = data.passed === true ? "OK" : (data.passed === false ? "FAIL" : "-");
          lines.push(`Status: ${passText}`);
          lines.push("");
          lines.push("Resposta:");
          lines.push(`${data.answer || ""}`);
          lines.push("");
          lines.push("Resumo:");
          lines.push(`- Intent detectada: ${data.intent || ""}`);
          lines.push(`- Intent esperada: ${data.expected_intent || ""}`);
          lines.push(`- Engine: ${data.engine || ""}`);
          const lat = (data.latency_ms !== undefined && data.latency_ms !== null) ? data.latency_ms : "";
          lines.push(`- Latencia: ${lat} ms`);
          if (data.decision_source) lines.push(`- Fonte decisao: ${data.decision_source}`);
          if (data.reason) lines.push(`- Motivo: ${data.reason}`);
          if (data.llm_ms !== undefined && data.llm_ms !== null) lines.push(`- LLM ms: ${data.llm_ms}`);
          if (data.llm_new_tokens !== undefined && data.llm_new_tokens !== null) lines.push(`- LLM tokens: ${data.llm_new_tokens}`);
          if (Array.isArray(data.sensitivity_labels) && data.sensitivity_labels.length) {
            lines.push(`- Rotulos sensiveis: ${data.sensitivity_labels.join(", ")}`);
          }
          out.textContent = lines.join("\\n");
        } catch (e) {
          out.textContent = 'erro ao enviar';
        }
      };
      const goLogs = () => { window.location.href = '/logs'; };
      window.sendMessage = sendMessage;
      window.goLogs = goLogs;
    </script>
  </body>
</html>
"""

SETTINGS_HTML_TEMPLATE = """<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Parametros</title>
    <style>
      :root {
        --bg: #f5f7fb;
        --card: #ffffff;
        --text: #0f172a;
        --muted: #5b6473;
        --accent: #2563eb;
        --border: #e5e7eb;
      }
      * { box-sizing: border-box; }
      body {
        font-family: "Space Grotesk", system-ui, sans-serif;
        margin: 0;
        color: var(--text);
        background: var(--bg);
        padding: 22px;
      }
      .wrap { max-width: 980px; margin: 0 auto; }
      .nav { display: flex; gap: 10px; margin-bottom: 14px; }
      .nav a {
        text-decoration: none;
        color: var(--text);
        background: var(--card);
        border: 1px solid var(--border);
        padding: 8px 14px;
        border-radius: 999px;
        font-size: 14px;
      }
      .nav a.active { background: var(--accent); color: #fff; border-color: var(--accent); }
      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 10px 24px rgba(15,23,42,.08);
      }
      label { display: block; margin-top: 12px; font-weight: 600; font-size: 13px; color: var(--muted); }
      input, textarea, select {
        width: 100%;
        padding: 10px 12px;
        margin-top: 6px;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: #fff;
        color: var(--text);
        outline: none;
      }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .vars { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 6px; }
      button {
        margin-top: 12px;
        padding: 10px 16px;
        border: 0;
        border-radius: 10px;
        background: var(--accent);
        color: #fff;
        cursor: pointer;
        font-weight: 700;
      }
      pre {
        background: #0b1224;
        color: #e5e7eb;
        padding: 12px;
        border-radius: 12px;
        border: 1px solid var(--border);
        overflow: auto;
        font-size: 12px;
      }
      @media (max-width: 720px) {
        .row { grid-template-columns: 1fr; }
        body { padding: 14px; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
    <div class="nav">
      <a href="/">Chat</a>
      <a href="/settings" class="active">Parametros</a>
      <a href="/logs">Logs</a>
      <a href="/results">Resultados</a>
    </div>
    <div class="card">
      <h1>Parametros do Modulo</h1>
      <div class="row">
        <div>
          <label for="mode">Modo</label>
          <input id="mode" value="hybrid" placeholder="llm_only | kw_only | hybrid"/>
        </div>
        <div>
          <label for="cfg">Preset</label>
          <input id="cfg" value="robust" placeholder="robust | light | t14_tok64_quant1"/>
        </div>
      </div>
      <label>Variaveis</label>
      <div class="vars">
        <div>
          <label for="HF_NUM_THREADS">HF_NUM_THREADS</label>
          <input id="HF_NUM_THREADS" class="var-input" value="%%HF_NUM_THREADS%%"/>
        </div>
        <div>
          <label for="HF_NUM_INTEROP">HF_NUM_INTEROP</label>
          <input id="HF_NUM_INTEROP" class="var-input" value="%%HF_NUM_INTEROP%%"/>
        </div>
        <div>
          <label for="OMP_NUM_THREADS">OMP_NUM_THREADS</label>
          <input id="OMP_NUM_THREADS" class="var-input" value="%%OMP_NUM_THREADS%%"/>
        </div>
        <div>
          <label for="MKL_NUM_THREADS">MKL_NUM_THREADS</label>
          <input id="MKL_NUM_THREADS" class="var-input" value="%%MKL_NUM_THREADS%%"/>
        </div>
        <div>
          <label for="ORCH_MAX_NEW_TOKENS">ORCH_MAX_NEW_TOKENS</label>
          <input id="ORCH_MAX_NEW_TOKENS" class="var-input" value="%%ORCH_MAX_NEW_TOKENS%%"/>
        </div>
        <div>
          <label for="ORCH_JSON_RETRIES">ORCH_JSON_RETRIES</label>
          <input id="ORCH_JSON_RETRIES" class="var-input" value="%%ORCH_JSON_RETRIES%%"/>
        </div>
        <div>
          <label for="ORCH_LLM_TIMEOUT_S">ORCH_LLM_TIMEOUT_S</label>
          <input id="ORCH_LLM_TIMEOUT_S" class="var-input" value="%%ORCH_LLM_TIMEOUT_S%%"/>
        </div>
        <div>
          <label for="ORCH_INCLUDE_LLM_RAW">ORCH_INCLUDE_LLM_RAW</label>
          <input id="ORCH_INCLUDE_LLM_RAW" class="var-input" value="%%ORCH_INCLUDE_LLM_RAW%%"/>
        </div>
        <div>
          <label for="ORCH_LLM_RAW_MAXCHARS">ORCH_LLM_RAW_MAXCHARS</label>
          <input id="ORCH_LLM_RAW_MAXCHARS" class="var-input" value="%%ORCH_LLM_RAW_MAXCHARS%%"/>
        </div>
        <div>
          <label for="ORCH_SLOW_MODE">ORCH_SLOW_MODE</label>
          <input id="ORCH_SLOW_MODE" class="var-input" value="%%ORCH_SLOW_MODE%%"/>
        </div>
        <div>
          <label for="ORCH_CLS_MAX_NEW_TOKENS">ORCH_CLS_MAX_NEW_TOKENS</label>
          <input id="ORCH_CLS_MAX_NEW_TOKENS" class="var-input" value="%%ORCH_CLS_MAX_NEW_TOKENS%%"/>
        </div>
        <div>
          <label for="ORCH_ENABLE_RT_OVERRIDE">ORCH_ENABLE_RT_OVERRIDE</label>
          <input id="ORCH_ENABLE_RT_OVERRIDE" class="var-input" value="%%ORCH_ENABLE_RT_OVERRIDE%%"/>
        </div>
        <div>
          <label for="ORCH_ENABLE_PV_OVERRIDE">ORCH_ENABLE_PV_OVERRIDE</label>
          <input id="ORCH_ENABLE_PV_OVERRIDE" class="var-input" value="%%ORCH_ENABLE_PV_OVERRIDE%%"/>
        </div>
        <div>
          <label for="ORCH_USE_LLM">ORCH_USE_LLM</label>
          <input id="ORCH_USE_LLM" class="var-input" value="%%ORCH_USE_LLM%%"/>
        </div>
        <div>
          <label for="ORCH_STRICT_LLM">ORCH_STRICT_LLM</label>
          <input id="ORCH_STRICT_LLM" class="var-input" value="%%ORCH_STRICT_LLM%%"/>
        </div>
        <div>
          <label for="ORCH_QUANT_DYNAMIC">ORCH_QUANT_DYNAMIC</label>
          <input id="ORCH_QUANT_DYNAMIC" class="var-input" value="%%ORCH_QUANT_DYNAMIC%%"/>
        </div>
      </div>
      <button id="apply">Aplicar parametros</button>
      <pre id="apply_out">...</pre>
    </div>
    </div>
    <script>
      const applyBtn = document.getElementById('apply');
      applyBtn.onclick = async () => {
        const out = document.getElementById('apply_out');
        out.textContent = 'aplicando...';
        const mode = document.getElementById('mode').value.trim();
        const cfg = document.getElementById('cfg').value.trim();
        let overrides = {};
        document.querySelectorAll('.var-input').forEach(el => {
          const v = el.value.trim();
          if (v !== '') overrides[el.id] = v;
        });
        try {
          const res = await fetch('/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, cfg, overrides })
          });
          const data = await res.json();
          out.textContent = JSON.stringify(data, null, 2);
        } catch (e) {
          out.textContent = 'erro ao aplicar parametros';
        }
      };
    </script>
  </body>
</html>
"""

SETTINGS_HTML = (
    SETTINGS_HTML_TEMPLATE
    .replace("%%HF_NUM_THREADS%%", os.getenv("HF_NUM_THREADS", "12"))
    .replace("%%HF_NUM_INTEROP%%", os.getenv("HF_NUM_INTEROP", "1"))
    .replace("%%OMP_NUM_THREADS%%", os.getenv("OMP_NUM_THREADS", os.getenv("HF_NUM_THREADS", "12")))
    .replace("%%MKL_NUM_THREADS%%", os.getenv("MKL_NUM_THREADS", os.getenv("HF_NUM_THREADS", "12")))
    .replace("%%ORCH_MAX_NEW_TOKENS%%", os.getenv("ORCH_MAX_NEW_TOKENS", "76"))
    .replace("%%ORCH_JSON_RETRIES%%", os.getenv("ORCH_JSON_RETRIES", "7"))
    .replace("%%ORCH_LLM_TIMEOUT_S%%", os.getenv("ORCH_LLM_TIMEOUT_S", "25"))
    .replace("%%ORCH_INCLUDE_LLM_RAW%%", os.getenv("ORCH_INCLUDE_LLM_RAW", "1"))
    .replace("%%ORCH_LLM_RAW_MAXCHARS%%", os.getenv("ORCH_LLM_RAW_MAXCHARS", "4000"))
    .replace("%%ORCH_SLOW_MODE%%", os.getenv("ORCH_SLOW_MODE", "1"))
    .replace("%%ORCH_CLS_MAX_NEW_TOKENS%%", os.getenv("ORCH_CLS_MAX_NEW_TOKENS", "36"))
    .replace("%%ORCH_ENABLE_RT_OVERRIDE%%", os.getenv("ORCH_ENABLE_RT_OVERRIDE", "0"))
    .replace("%%ORCH_ENABLE_PV_OVERRIDE%%", os.getenv("ORCH_ENABLE_PV_OVERRIDE", "0"))
    .replace("%%ORCH_USE_LLM%%", os.getenv("ORCH_USE_LLM", "1"))
    .replace("%%ORCH_STRICT_LLM%%", os.getenv("ORCH_STRICT_LLM", "0"))
    .replace("%%ORCH_QUANT_DYNAMIC%%", os.getenv("ORCH_QUANT_DYNAMIC", "0"))
)

LOGS_HTML = """<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Logs</title>
    <style>
      :root {
        --bg: #f5f7fb;
        --card: #ffffff;
        --text: #0f172a;
        --muted: #5b6473;
        --accent: #2563eb;
        --border: #e5e7eb;
        --ok: #16a34a;
        --fail: #dc2626;
      }
      * { box-sizing: border-box; }
      body { font-family: "Space Grotesk", system-ui, sans-serif; margin: 0; color: var(--text); background: var(--bg); padding: 22px; }
      .wrap { max-width: 980px; margin: 0 auto; }
      .nav { display: flex; gap: 10px; margin-bottom: 14px; }
      .nav a { text-decoration: none; color: var(--text); background: var(--card); border: 1px solid var(--border); padding: 8px 14px; border-radius: 999px; font-size: 14px; }
      .nav a.active { background: var(--accent); color: #fff; border-color: var(--accent); }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: 0 10px 24px rgba(15,23,42,.08); }
      label { display: block; margin-top: 12px; font-weight: 600; font-size: 13px; color: var(--muted); }
      input, select {
        width: 100%; padding: 10px 12px; margin-top: 6px; border: 1px solid var(--border);
        border-radius: 10px; background: #fff; color: var(--text);
      }
      .row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
      .btns { display: flex; gap: 8px; margin-top: 10px; }
      button { padding: 10px 16px; border: 0; border-radius: 10px; background: var(--accent); color: #fff; cursor: pointer; font-weight: 700; }
      pre { background: #0b1224; color: #e5e7eb; padding: 12px; border-radius: 12px; border: 1px solid var(--border); overflow: auto; font-size: 12px; }
      table { width: 100%; border-collapse: collapse; margin-top: 10px; }
      th, td { border-bottom: 1px solid var(--border); padding: 8px; text-align: left; font-size: 12px; }
      th { background: #f3f4f6; color: var(--muted); }
      .pill.ok { color: var(--ok); font-weight: 700; }
      .pill.fail { color: var(--fail); font-weight: 700; }
      @media (max-width: 720px) {
        .row { grid-template-columns: 1fr; }
        body { padding: 14px; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
    <div class="nav">
      <a href="/">Chat</a>
      <a href="/settings">Parametros</a>
      <a href="/logs" class="active">Logs</a>
    </div>
    <div class="card">
      <h1>Logs</h1>
      <div class="row">
        <div>
          <label for="log_user">Filtrar user_id</label>
          <input id="log_user" placeholder="usuario_demo_123"/>
        </div>
        <div>
          <label for="log_intent">Filtrar intent</label>
          <input id="log_intent" placeholder="PREVISAO | ESTACOES_RT | GENERICO"/>
        </div>
        <div>
          <label for="log_pass">Filtrar pass</label>
          <select id="log_pass">
            <option value="">Todos</option>
            <option value="true">OK</option>
            <option value="false">FAIL</option>
          </select>
        </div>
      </div>
      <div class="btns">
        <button id="load">Carregar</button>
        <button id="export" class="secondary">Exportar CSV</button>
      </div>
      <div id="logs_table"></div>
      <pre id="logs">...</pre>
    </div>
    </div>
    <script>
      const logBtn = document.getElementById('load');
      const exportBtn = document.getElementById('export');
      const buildParams = () => {
        const user = document.getElementById('log_user').value.trim();
        const intent = document.getElementById('log_intent').value.trim();
        const passed = document.getElementById('log_pass').value.trim();
        const params = new URLSearchParams({ limit: '1000' });
        if (user) params.set('user_id', user);
        if (intent) params.set('intent', intent);
        if (passed) params.set('passed', passed);
        return params;
      };
      logBtn.onclick = async () => {
        const logs = document.getElementById('logs');
        const table = document.getElementById('logs_table');
        logs.textContent = 'carregando...';
        try {
          const params = buildParams();
          params.set('limit', '50');
          const res = await fetch('/logs-data?' + params.toString());
          const data = await res.json();
          logs.textContent = JSON.stringify(data, null, 2);
          if (Array.isArray(data) && data.length) {
            const rows = data.map(r => `
              <tr>
                <td>${r.ts || ''}</td>
                <td>${r.user_id || ''}</td>
                <td>${r.expected_intent || ''}</td>
                <td>${r.intent || ''}</td>
                <td>${r.passed === true ? '<span class="pill ok">OK</span>' : (r.passed === false ? '<span class="pill fail">FAIL</span>' : '')}</td>
                <td>${r.decision_source || ''}</td>
                <td>${r.latency_ms || ''}</td>
                <td>${(r.message || '').slice(0, 40)}</td>
                <td>${(r.response || '').slice(0, 40)}</td>
              </tr>
            `).join('');
            table.innerHTML = `
              <table>
                <thead>
                  <tr>
                    <th>ts</th><th>user</th><th>exp</th><th>intent</th><th>pass</th><th>source</th><th>ms</th><th>msg</th><th>resp</th>
                  </tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            `;
          } else {
            table.innerHTML = '';
          }
        } catch (e) {
          logs.textContent = 'erro ao carregar logs';
        }
      };
      exportBtn.onclick = async () => {
        const params = buildParams();
        const url = '/logs-csv?' + params.toString();
        window.location.href = url;
      };
    </script>
  </body>
</html>
"""

RESULTS_HTML = """<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Resultados</title>
    <style>
      :root {
        --bg: #f5f7fb;
        --card: #ffffff;
        --text: #0f172a;
        --muted: #5b6473;
        --accent: #2563eb;
        --border: #e5e7eb;
        --ok: #16a34a;
        --fail: #dc2626;
      }
      * { box-sizing: border-box; }
      body { font-family: "Space Grotesk", system-ui, sans-serif; margin: 0; color: var(--text); background: var(--bg); padding: 22px; }
      .wrap { max-width: 980px; margin: 0 auto; }
      .nav { display: flex; gap: 10px; margin-bottom: 14px; }
      .nav a { text-decoration: none; color: var(--text); background: var(--card); border: 1px solid var(--border); padding: 8px 14px; border-radius: 999px; font-size: 14px; }
      .nav a.active { background: var(--accent); color: #fff; border-color: var(--accent); }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: 0 10px 24px rgba(15,23,42,.08); }
      h1 { margin: 0 0 6px; }
      p { color: var(--muted); }
      table { width: 100%; border-collapse: collapse; margin-top: 10px; }
      th, td { border-bottom: 1px solid var(--border); padding: 8px; text-align: left; font-size: 12px; }
      th { background: #f3f4f6; color: var(--muted); }
      pre { background: #0b1224; color: #e5e7eb; padding: 12px; border-radius: 12px; border: 1px solid var(--border); overflow: auto; font-size: 12px; }
      @media (max-width: 720px) { body { padding: 14px; } }
    </style>
  </head>
  <body>
    <div class="wrap">
    <div class="nav">
      <a href="/">Chat</a>
      <a href="/settings">Parametros</a>
      <a href="/logs">Logs</a>
      <a href="/results" class="active">Resultados</a>
    </div>
    <div class="card">
      <h1>Resultados</h1>
      <p>Base: user_interactions.jsonl</p>
      <h3>Métricas</h3>
      <div id="metrics_table"></div>
      <h3>Matriz de confusão</h3>
      <div id="cm_table"></div>
      <h3>Heatmap</h3>
      <div id="cm_heatmap"></div>
      <h3>Histograma de latência</h3>
      <div id="lat_hist"></div>
      <h3>Distribuição por source</h3>
      <div id="source_dist"></div>
      <pre id="raw">...</pre>
    </div>
    </div>
    <script>
      const render = async () => {
        const raw = document.getElementById('raw');
        const metrics = document.getElementById('metrics_table');
        const cm = document.getElementById('cm_table');
        raw.textContent = 'carregando...';
        try {
          const res = await fetch('/results-data');
          const data = await res.json();
          raw.textContent = JSON.stringify(data, null, 2);
          if (data.metrics) {
            metrics.innerHTML = `
              <table>
                <thead>
                  <tr>
                    <th>Acuracia</th>
                    <th>Macro-F1</th>
                    <th>Latencia media (ms)</th>
                    <th>p50 (ms)</th>
                    <th>p95 (ms)</th>
                    <th>N</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>${data.metrics.accuracy ?? ''}</td>
                    <td>${data.metrics.macro_f1 ?? ''}</td>
                    <td>${data.metrics.latency_mean_ms ?? ''}</td>
                    <td>${data.metrics.latency_p50_ms ?? ''}</td>
                    <td>${data.metrics.latency_p95_ms ?? ''}</td>
                    <td>${data.metrics.n ?? ''}</td>
                  </tr>
                </tbody>
              </table>
            `;
          }
          if (data.confusion && data.confusion.labels) {
            const labels = data.confusion.labels;
            const rows = labels.map((lab, i) => {
              const cells = data.confusion.matrix[i].map(v => `<td>${v}</td>`).join('');
              return `<tr><th>${lab}</th>${cells}</tr>`;
            }).join('');
            const header = labels.map(l => `<th>${l}</th>`).join('');
            cm.innerHTML = `
              <table>
                <thead>
                  <tr><th>exp \\ pred</th>${header}</tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            `;

            const maxVal = Math.max(...data.confusion.matrix.flat(), 1);
            const heatRows = labels.map((lab, i) => {
              const cells = data.confusion.matrix[i].map(v => {
                const intensity = Math.round((v / maxVal) * 200);
                return `<td style="background: rgba(37,99,235,${intensity/255}); color:#fff;">${v}</td>`;
              }).join('');
              return `<tr><th>${lab}</th>${cells}</tr>`;
            }).join('');
            const heatHeader = labels.map(l => `<th>${l}</th>`).join('');
            document.getElementById('cm_heatmap').innerHTML = `
              <table>
                <thead>
                  <tr><th>exp \\ pred</th>${heatHeader}</tr>
                </thead>
                <tbody>${heatRows}</tbody>
              </table>
            `;
          }

          if (data.latency && data.latency.bins) {
            const bins = data.latency.bins;
            const maxCount = Math.max(...bins.map(b => b.count), 1);
            const rows = bins.map(b => {
              const width = Math.round((b.count / maxCount) * 100);
              return `
                <tr>
                  <td>${b.label}</td>
                  <td style="width:70%">
                    <div style="height:10px;background:#2563eb;width:${width}%;border-radius:6px;"></div>
                  </td>
                  <td>${b.count}</td>
                </tr>`;
            }).join('');
            document.getElementById('lat_hist').innerHTML = `
              <table>
                <thead>
                  <tr><th>Faixa (ms)</th><th>Distribuição</th><th>N</th></tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            `;
          }

          if (data.source_dist && data.source_dist.items) {
            const items = data.source_dist.items;
            const maxCount = Math.max(...items.map(b => b.count), 1);
            const rows = items.map(b => {
              const width = Math.round((b.count / maxCount) * 100);
              return `
                <tr>
                  <td>${b.source}</td>
                  <td style="width:70%">
                    <div style="height:10px;background:#10b981;width:${width}%;border-radius:6px;"></div>
                  </td>
                  <td>${b.count}</td>
                </tr>`;
            }).join('');
            document.getElementById('source_dist').innerHTML = `
              <table>
                <thead>
                  <tr><th>Source</th><th>Distribuição</th><th>N</th></tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            `;
          }
        } catch (e) {
          raw.textContent = 'erro ao carregar';
        }
      };
      render();
    </script>
  </body>
</html>
"""

USABILITY_HTML = """<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Avaliacao de Usabilidade</title>
    <style>
      :root {
        --bg: #f5f7fb;
        --card: #ffffff;
        --text: #0f172a;
        --muted: #5b6473;
        --accent: #2563eb;
        --border: #e5e7eb;
        --ok: #16a34a;
        --warn: #b45309;
        --err: #dc2626;
      }
      * { box-sizing: border-box; }
      body { font-family: "Space Grotesk", system-ui, sans-serif; margin: 0; color: var(--text); background: var(--bg); padding: 22px; }
      .wrap { max-width: 980px; margin: 0 auto; }
      .nav { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
      .nav a { text-decoration: none; color: var(--text); background: var(--card); border: 1px solid var(--border); padding: 8px 14px; border-radius: 999px; font-size: 14px; }
      .nav a.active { background: var(--accent); color: #fff; border-color: var(--accent); }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: 0 10px 24px rgba(15,23,42,.08); }
      h1 { margin: 0 0 6px; }
      h3 { margin: 8px 0; }
      p { color: var(--muted); }
      .muted { color: var(--muted); font-size: 13px; }
      .hidden { display: none; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      label { display: block; margin-top: 12px; font-weight: 600; font-size: 13px; color: var(--muted); }
      input, textarea, select {
        width: 100%; padding: 10px 12px; margin-top: 6px; border: 1px solid var(--border);
        border-radius: 10px; background: #fff; color: var(--text);
      }
      .btns { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
      button { padding: 10px 16px; border: 0; border-radius: 10px; background: var(--accent); color: #fff; cursor: pointer; font-weight: 700; }
      button.secondary { background: #111827; }
      button.warn { background: var(--warn); }
      button.err { background: var(--err); }
      .chat-box { border: 1px solid var(--border); border-radius: 12px; background: #fafafa; padding: 10px; min-height: 240px; max-height: 360px; overflow-y: auto; }
      .msg { margin: 8px 0; padding: 8px 10px; border-radius: 10px; }
      .msg.user { background: #e0ecff; }
      .msg.bot { background: #eaf8eb; }
      .msg .meta { font-size: 12px; color: #475569; margin-bottom: 4px; }
      .step { display: inline-block; padding: 5px 10px; background: #eef2ff; color: #3730a3; border-radius: 999px; font-size: 12px; margin-bottom: 8px; }
      .status { margin-top: 8px; font-size: 13px; color: #334155; white-space: pre-wrap; }
      @media (max-width: 720px) { .row { grid-template-columns: 1fr; } body { padding: 14px; } }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="nav">
        <a href="/">Chat</a>
        <a href="/settings">Parametros</a>
        <a href="/logs">Logs</a>
        <a href="/results">Resultados</a>
        <a href="/usability" class="active">Avaliacao</a>
      </div>
      <div class="card">
        <h1>Avaliacao de Usabilidade</h1>
        <p>Fluxo de pesquisa de risco minimo com dados anonimizados para analise agregada.</p>

        <section id="step-consent">
          <span class="step">Etapa 1 de 3</span>
          <h3>Consentimento (TCLE simplificado)</h3>
          <p>
            Voce esta convidado(a) a avaliar o assistente virtual. Nao coletamos nome completo, CPF ou e-mail neste fluxo.
            O uso e apenas para pesquisa academica, com analise agregada e risco minimo.
          </p>
          <div class="btns">
            <button type="button" id="btn-consent-yes">Aceito participar</button>
            <button type="button" class="err" id="btn-consent-no">Nao aceito</button>
          </div>
          <div id="consent-status" class="status"></div>
        </section>

        <section id="step-chat" class="hidden">
          <span class="step">Etapa 2 de 3</span>
          <h3>Interacao com o assistente</h3>
          <p class="muted">Converse normalmente e finalize quando terminar.</p>
          <div id="chat-history" class="chat-box"></div>
          <label for="chat-input">Mensagem</label>
          <textarea id="chat-input" rows="3" placeholder="Digite sua pergunta..."></textarea>
          <div class="btns">
            <button type="button" id="btn-chat-send">Enviar</button>
            <button type="button" class="warn" id="btn-chat-finish">Finalizar avaliacao</button>
          </div>
          <div id="chat-status" class="status"></div>
        </section>

        <section id="step-survey" class="hidden">
          <span class="step">Etapa 3 de 3</span>
          <h3>Questionario de usabilidade/satisfacao</h3>
          <div class="row">
            <div>
              <label for="q1">1) Clareza da resposta (1-5)</label>
              <select id="q1"><option value="">Selecione...</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select>
            </div>
            <div>
              <label for="q2">2) Utilidade da resposta (1-5)</label>
              <select id="q2"><option value="">Selecione...</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select>
            </div>
            <div>
              <label for="q3">3) Adequacao ao contexto (1-5)</label>
              <select id="q3"><option value="">Selecione...</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select>
            </div>
            <div>
              <label for="q4">4) Facilidade de uso (1-5)</label>
              <select id="q4"><option value="">Selecione...</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select>
            </div>
            <div>
              <label for="q5">5) Satisfacao geral (1-5)</label>
              <select id="q5"><option value="">Selecione...</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select>
            </div>
          </div>
          <label for="q-comment">Comentario opcional</label>
          <textarea id="q-comment" rows="4" placeholder="Se quiser, descreva observacoes ou sugestoes."></textarea>
          <div class="btns">
            <button type="button" id="btn-survey-send">Enviar avaliacao</button>
          </div>
          <div id="survey-status" class="status"></div>
        </section>

        <section id="step-end" class="hidden">
          <h3>Obrigado pela participacao.</h3>
          <p>Respostas enviadas com sucesso.</p>
        </section>
      </div>
    </div>

    <script>
      const STORAGE_KEY = "usability_flow_state_v1";
      const state = {
        session_id: null,
        consent_accepted: false,
        chat: [],
        survey: { q1: "", q2: "", q3: "", q4: "", q5: "", comment: "" }
      };

      const byId = (id) => document.getElementById(id);
      const show = (id) => byId(id).classList.remove("hidden");
      const hide = (id) => byId(id).classList.add("hidden");

      const saveState = () => {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
      };
      const loadState = () => {
        try {
          const raw = localStorage.getItem(STORAGE_KEY);
          if (!raw) return;
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object") {
            Object.assign(state, parsed);
          }
        } catch (e) {}
      };
      const clearState = () => {
        try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
      };

      const renderChat = () => {
        const box = byId("chat-history");
        box.innerHTML = "";
        state.chat.forEach((m) => {
          const div = document.createElement("div");
          div.className = `msg ${m.role}`;
          div.innerHTML = `<div class="meta">${m.role === "user" ? "Usuario" : "Assistente"} - ${m.ts || ""}</div><div>${m.text}</div>`;
          box.appendChild(div);
        });
        box.scrollTop = box.scrollHeight;
      };

      const stepToConsent = () => {
        show("step-consent"); hide("step-chat"); hide("step-survey"); hide("step-end");
      };
      const stepToChat = () => {
        hide("step-consent"); show("step-chat"); hide("step-survey"); hide("step-end");
      };
      const stepToSurvey = () => {
        hide("step-consent"); hide("step-chat"); show("step-survey"); hide("step-end");
      };
      const stepToEnd = () => {
        hide("step-consent"); hide("step-chat"); hide("step-survey"); show("step-end");
      };

      const initSurveyForm = () => {
        ["q1","q2","q3","q4","q5"].forEach((k) => { byId(k).value = state.survey[k] || ""; });
        byId("q-comment").value = state.survey.comment || "";
      };

      const postJson = async (url, payload) => {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload || {})
        });
        const text = await res.text();
        let data = {};
        try { data = JSON.parse(text); } catch (e) { data = { error: text }; }
        if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
        return data;
      };

      byId("btn-consent-yes").onclick = async () => {
        byId("consent-status").textContent = "Criando sessao...";
        try {
          const data = await postJson("/api/usability/session/start", { consent_accepted: true });
          state.session_id = data.session_id;
          state.consent_accepted = true;
          saveState();
          byId("consent-status").textContent = "Consentimento registrado.";
          stepToChat();
          renderChat();
        } catch (e) {
          byId("consent-status").textContent = `Erro ao iniciar sessao: ${e.message}`;
        }
      };

      byId("btn-consent-no").onclick = () => {
        byId("consent-status").textContent = "Fluxo encerrado. Obrigado.";
        clearState();
        state.session_id = null;
        state.chat = [];
        state.survey = { q1: "", q2: "", q3: "", q4: "", q5: "", comment: "" };
      };

      byId("btn-chat-send").onclick = async () => {
        const msg = byId("chat-input").value.trim();
        if (!msg) {
          byId("chat-status").textContent = "Digite uma mensagem antes de enviar.";
          return;
        }
        if (!state.session_id) {
          byId("chat-status").textContent = "Sessao invalida. Reinicie o fluxo.";
          stepToConsent();
          return;
        }
        byId("chat-status").textContent = "Enviando...";
        const userMsg = { role: "user", text: msg, ts: new Date().toISOString() };
        state.chat.push(userMsg);
        renderChat();
        saveState();
        byId("chat-input").value = "";
        try {
          const chatResp = await postJson("/chat", { user_id: `usability_${state.session_id.slice(0, 8)}`, message: msg });
          const assistantText = chatResp.answer || "Sem resposta";
          const assistantMsg = { role: "bot", text: assistantText, ts: new Date().toISOString() };
          state.chat.push(assistantMsg);
          renderChat();
          saveState();

          await postJson(`/api/usability/session/${state.session_id}/chat-log`, {
            timestamp: new Date().toISOString(),
            user_message: msg,
            assistant_response: assistantText,
            response_time_ms: chatResp.latency_ms || null,
            route_or_intent: chatResp.intent || null,
            had_rephrase: false
          });
          byId("chat-status").textContent = "Interacao registrada.";
        } catch (e) {
          byId("chat-status").textContent = `Erro no envio: ${e.message}`;
        }
      };

      byId("btn-chat-finish").onclick = () => {
        if (!state.chat.length) {
          byId("chat-status").textContent = "Realize ao menos uma interacao antes de finalizar.";
          return;
        }
        initSurveyForm();
        stepToSurvey();
      };

      ["q1","q2","q3","q4","q5","q-comment"].forEach((id) => {
        byId(id).addEventListener("change", () => {
          state.survey.q1 = byId("q1").value;
          state.survey.q2 = byId("q2").value;
          state.survey.q3 = byId("q3").value;
          state.survey.q4 = byId("q4").value;
          state.survey.q5 = byId("q5").value;
          state.survey.comment = byId("q-comment").value;
          saveState();
        });
      });

      byId("btn-survey-send").onclick = async () => {
        if (!state.session_id) {
          byId("survey-status").textContent = "Sessao invalida. Reinicie o fluxo.";
          stepToConsent();
          return;
        }
        const required = ["q1","q2","q3","q4","q5"];
        for (const r of required) {
          if (!byId(r).value) {
            byId("survey-status").textContent = "Preencha todas as perguntas obrigatorias (1 a 5).";
            return;
          }
        }
        state.survey.q1 = byId("q1").value;
        state.survey.q2 = byId("q2").value;
        state.survey.q3 = byId("q3").value;
        state.survey.q4 = byId("q4").value;
        state.survey.q5 = byId("q5").value;
        state.survey.comment = byId("q-comment").value.trim();
        saveState();

        byId("survey-status").textContent = "Enviando avaliacao...";
        try {
          await postJson(`/api/usability/session/${state.session_id}/survey`, {
            clarity_score: Number(state.survey.q1),
            usefulness_score: Number(state.survey.q2),
            adequacy_score: Number(state.survey.q3),
            ease_of_use_score: Number(state.survey.q4),
            satisfaction_score: Number(state.survey.q5),
            comment: state.survey.comment || null
          });
          await postJson(`/api/usability/session/${state.session_id}/finish`, {});
          byId("survey-status").textContent = "Avaliacao enviada com sucesso.";
          clearState();
          stepToEnd();
        } catch (e) {
          byId("survey-status").textContent = `Falha ao enviar: ${e.message}`;
        }
      };

      // bootstrap
      loadState();
      if (state.consent_accepted && state.session_id) {
        stepToChat();
        renderChat();
      } else {
        stepToConsent();
      }
    </script>
  </body>
</html>
"""

@app.route('/', methods=['GET'])
def index():
    return redirect('/app', code=302)


@app.route('/app', methods=['GET'])
@app.route('/app/<path:path>', methods=['GET'])
def react_app(path=None):
    if not os.path.isdir(FRONTEND_DIST_DIR):
        return jsonify({
            "error": "Frontend React nao buildado. Rode: cd frontend && npm install && npm run build"
        }), 404

    if path:
        candidate = os.path.join(FRONTEND_DIST_DIR, path)
        if os.path.isfile(candidate):
            return send_from_directory(FRONTEND_DIST_DIR, path)

    return send_from_directory(FRONTEND_DIST_DIR, "index.html")

@app.route('/assets/<path:path>', methods=['GET'])
def react_assets(path):
    assets_dir = os.path.join(FRONTEND_DIST_DIR, "assets")
    if not os.path.isdir(assets_dir):
        return jsonify({
            "error": "Assets do frontend React nao encontrados. Rode: cd frontend && npm install && npm run build"
        }), 404
    return send_from_directory(assets_dir, path)

@app.route('/settings', methods=['GET'])
def settings_page():
    return Response(SETTINGS_HTML, mimetype='text/html')

@app.route('/logs', methods=['GET'])
def logs_page():
    return Response(LOGS_HTML, mimetype='text/html')

@app.route('/results', methods=['GET'])
def results_page():
    return Response(RESULTS_HTML, mimetype='text/html')

@app.route('/usability', methods=['GET'])
def usability_page():
    return Response(USABILITY_HTML, mimetype='text/html')


@app.route('/api/auth/config', methods=['GET'])
def auth_config():
    return jsonify({
        "login_mode": "manual_token",
        "authenticated": bool(_auth_payload()),
    })


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    user = _auth_payload()
    if not user:
        return _auth_error()
    return jsonify({"user": user})


@app.route('/api/auth/token/login', methods=['POST'])
def auth_token_login():
    payload = request.get_json() or {}
    token = payload.get("token")
    try:
        user = _verify_dashboard_token(token)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    session["auth_user"] = user
    session.permanent = True
    return jsonify({"status": "ok", "user": _auth_payload()})


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.pop("auth_user", None)
    return jsonify({"status": "ok"})


@app.route('/api/system/health', methods=['GET'])
def system_health():
    return jsonify(_system_health_payload())


@app.route('/healthz', methods=['GET'])
def healthz():
    return jsonify({"ok": True, "ts": _now_iso()})


@app.route('/readyz', methods=['GET'])
def readyz():
    checks = {
        "config": {
            "ok": bool(app.secret_key),
        },
        "frontend_dist": {
            "ok": os.path.isfile(os.path.join(FRONTEND_DIST_DIR, "index.html")),
        },
        "orchestrator": {
            "ok": orch is not None,
        },
        "postgres": {
            "ok": (not POSTGRES_ENABLED) or _postgres_ready(),
            "enabled": POSTGRES_ENABLED,
        },
    }
    ready = all(item.get("ok") for item in checks.values())
    status = 200 if ready else 503
    return jsonify({"ready": ready, "checks": checks, "ts": _now_iso()}), status


@app.route('/api/system/version', methods=['GET'])
def system_version():
    return jsonify({
        "app": "guardian-weather-watch",
        "app_env": APP_ENV,
        "model_id": os.getenv("HF_MODEL_ID", ""),
        "orchestrator_version": ORCH_VERSION,
        "ts": _now_iso(),
    })


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    if 'message' not in data:
        return jsonify({
            "error": "Requisicao invalida. Forneca 'message'.",
            "request_id": request.request_id,
        }), 400

    msg = data['message']
    session_id = _interaction_session_id()
    user_id = data.get('user_id') or session_id
    expected_intent = (data.get('expected_intent') or "").strip().upper() or None

    try:
        t0 = time.time()
        resposta, intent, labels, engine = orch.route(msg, session_id)
        latency_ms = int((time.time() - t0) * 1000)

        audit = _tail_last_event_for_prompt(LOG_PATH, _sanitize(msg)) or {}
        passed = None
        if expected_intent:
            passed = (expected_intent == intent)

        log_entry = {
            "id": str(uuid.uuid4()),
            "ts": audit.get("ts"),
            "session_id": session_id,
            "user_id": user_id,
            "message": msg,
            "expected_intent": expected_intent,
            "response": resposta,
            "intent": intent,
            "passed": passed,
            "sensitivity_labels": labels,
            "engine": engine,
            "latency_ms": latency_ms,
            "decision_source": audit.get("decision_source"),
            "reason": audit.get("reason"),
            "llm_ms": audit.get("llm_ms"),
            "llm_new_tokens": audit.get("llm_new_tokens"),
            "llm_stop_reason": audit.get("llm_stop_reason"),
            "entrada_norm": audit.get("entrada_norm"),
            "raw_output": audit.get("raw_output"),
            "final_output": audit.get("final_output"),
        }
        write_jsonl(USER_LOG_PATH, log_entry)
        _insert_user_interaction_db(log_entry)

        return jsonify({
            "answer": resposta,
            "session_id": session_id,
            "intent": intent,
            "expected_intent": expected_intent,
            "passed": passed,
            "engine": engine,
            "latency_ms": latency_ms,
            "decision_source": log_entry.get("decision_source"),
            "reason": log_entry.get("reason"),
            "llm_ms": log_entry.get("llm_ms"),
            "llm_new_tokens": log_entry.get("llm_new_tokens"),
            "sensitivity_labels": labels,
        })
    except Exception as e:
        write_jsonl(LOG_PATH, {
            "type": "error",
            "orchestrator_version": ORCH_VERSION,
            "message": str(e),
        })
        return jsonify({"error": "Ocorreu um erro interno."}), 500


@app.route('/logs-data', methods=['GET'])
@require_auth
def logs():
    try:
        limit = int(request.args.get("limit", "50"))
    except Exception:
        limit = 50
    q_session = (request.args.get("session_id") or request.args.get("user_id") or "").strip()
    q_intent = (request.args.get("intent") or "").strip().upper()
    q_passed = (request.args.get("passed") or "").strip().lower()
    db_entries = _fetch_user_logs_db(limit=limit, q_session=q_session, q_intent=q_intent, q_passed=q_passed)
    if db_entries is not None:
        return jsonify(db_entries)
    entries = []
    if os.path.exists(USER_LOG_PATH):
        with open(USER_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if q_session and str(item.get("session_id") or item.get("user_id") or "") != q_session:
                        continue
                    if q_intent and str(item.get("intent", "")).upper() != q_intent:
                        continue
                    if q_passed in {"true", "false"} and str(item.get("passed")).lower() != q_passed:
                        continue
                    entries.append(item)
                except Exception:
                    continue
    return jsonify(entries[-limit:])


@app.route('/api/usability/session/start', methods=['POST'])
def usability_session_start():
    payload = request.get_json() or {}
    consent = bool(payload.get("consent_accepted"))
    if not consent:
        return jsonify({"error": "Consentimento obrigatorio para iniciar a sessao."}), 400

    session_id = str(uuid.uuid4())
    rec = {
        "event": "start",
        "session_id": session_id,
        "consent_accepted": True,
        "started_at": _now_iso(),
        "finished_at": None,
        "status": "started",
        # Pesquisa academica de risco minimo: nao armazenar identificadores pessoais diretos.
        "privacy_mode": "pseudonymous_minimal",
    }
    _append_jsonl(USABILITY_SESSIONS_PATH, rec)
    _upsert_usability_session_db(rec)
    return jsonify({"session_id": session_id, "status": "started"})


@app.route('/api/usability/session/<session_id>/chat-log', methods=['POST'])
def usability_chat_log(session_id):
    sess = _get_session_state(session_id)
    if not sess:
        return jsonify({"error": "Sessao nao encontrada."}), 404
    if sess.get("status") != "started":
        return jsonify({"error": "Sessao nao esta ativa."}), 400

    payload = request.get_json() or {}
    user_message = (payload.get("user_message") or "").strip()
    assistant_response = (payload.get("assistant_response") or "").strip()
    if not user_message or not assistant_response:
        return jsonify({"error": "Campos obrigatorios: user_message, assistant_response."}), 400

    rec = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "timestamp": payload.get("timestamp") or _now_iso(),
        "user_message": user_message,
        "assistant_response": assistant_response,
        "response_time_ms": payload.get("response_time_ms"),
        "route_or_intent": payload.get("route_or_intent"),
        "had_rephrase": bool(payload.get("had_rephrase", False)),
        "created_at": _now_iso(),
    }
    _append_jsonl(USABILITY_CHAT_LOGS_PATH, rec)
    _insert_usability_chat_log_db(rec)
    return jsonify({"status": "ok", "id": rec["id"]})


def _is_valid_score(v):
    return isinstance(v, int) and 1 <= v <= 5


@app.route('/api/usability/session/<session_id>/survey', methods=['POST'])
def usability_survey(session_id):
    sess = _get_session_state(session_id)
    if not sess:
        return jsonify({"error": "Sessao nao encontrada."}), 404
    if sess.get("status") != "started":
        return jsonify({"error": "Sessao nao esta ativa."}), 400

    payload = request.get_json() or {}
    fields = [
        "clarity_score",
        "usefulness_score",
        "adequacy_score",
        "ease_of_use_score",
        "satisfaction_score",
    ]
    for f in fields:
        if not _is_valid_score(payload.get(f)):
            return jsonify({"error": f"Campo invalido: {f}. Use inteiro de 1 a 5."}), 400

    rec = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "clarity_score": payload["clarity_score"],
        "usefulness_score": payload["usefulness_score"],
        "adequacy_score": payload["adequacy_score"],
        "ease_of_use_score": payload["ease_of_use_score"],
        "satisfaction_score": payload["satisfaction_score"],
        "comment": (payload.get("comment") or "").strip() or None,
        "submitted_at": _now_iso(),
    }
    _append_jsonl(USABILITY_SURVEYS_PATH, rec)
    _insert_usability_survey_db(rec)
    return jsonify({"status": "ok", "id": rec["id"]})


@app.route('/api/usability/session/<session_id>/finish', methods=['POST'])
def usability_finish(session_id):
    sess = _get_session_state(session_id)
    if not sess:
        return jsonify({"error": "Sessao nao encontrada."}), 404
    if sess.get("status") != "started":
        return jsonify({"error": "Sessao nao esta ativa."}), 400

    rec = {
        "event": "finish",
        "session_id": session_id,
        "finished_at": _now_iso(),
        "status": "finished",
    }
    _append_jsonl(USABILITY_SESSIONS_PATH, rec)
    _upsert_usability_session_db(rec)
    return jsonify({"status": "finished", "session_id": session_id})


@app.route('/api/usability/results/aggregate', methods=['GET'])
@require_auth
def usability_results_aggregate():
    db_result = _aggregate_usability_db()
    if db_result is not None:
        return jsonify(db_result)

    sessions = _read_jsonl(USABILITY_SESSIONS_PATH)
    chat_logs = _read_jsonl(USABILITY_CHAT_LOGS_PATH)
    surveys = _read_jsonl(USABILITY_SURVEYS_PATH)
    valid = [s for s in surveys if isinstance(s, dict) and s.get("session_id")]
    n = len(valid)
    if n == 0:
        return jsonify({
            "n": 0,
            "averages": {},
            "distributions": {},
            "comments": [],
            "sessions": {
                "started": 0,
                "finished": 0,
                "completion_rate": None,
                "avg_chat_turns": None,
            },
            "routes": [],
        })

    def avg(key):
        vals = [int(s[key]) for s in valid if isinstance(s.get(key), int)]
        return round(sum(vals) / len(vals), 3) if vals else None

    def distribution(key):
        counts = {score: 0 for score in range(1, 6)}
        for survey in valid:
            value = survey.get(key)
            if isinstance(value, int) and 1 <= value <= 5:
                counts[value] += 1
        return [
            {
                "score": score,
                "count": counts[score],
                "pct": round((counts[score] / n) * 100, 2) if n else 0.0,
            }
            for score in range(1, 6)
        ]

    started_sessions = set()
    finished_sessions = set()
    for row in sessions:
        if not isinstance(row, dict):
            continue
        session_id = row.get("session_id")
        if not session_id:
            continue
        if row.get("event") == "start":
            started_sessions.add(session_id)
        elif row.get("event") == "finish":
            finished_sessions.add(session_id)

    turns_by_session = {}
    route_counts = {}
    for row in chat_logs:
        if not isinstance(row, dict):
            continue
        session_id = row.get("session_id")
        if session_id:
            turns_by_session[session_id] = turns_by_session.get(session_id, 0) + 1
        route = (row.get("route_or_intent") or "unknown").upper()
        route_counts[route] = route_counts.get(route, 0) + 1

    avg_chat_turns = None
    if turns_by_session:
        avg_chat_turns = round(sum(turns_by_session.values()) / len(turns_by_session), 2)

    completion_rate = None
    if started_sessions:
        completion_rate = round((len(finished_sessions) / len(started_sessions)) * 100, 2)

    comments = []
    for survey in reversed(valid):
        comment = (survey.get("comment") or "").strip()
        if not comment:
            continue
        comments.append({
            "session_id": survey.get("session_id"),
            "comment": comment,
            "submitted_at": survey.get("submitted_at"),
        })
        if len(comments) >= 10:
            break

    return jsonify({
        "n": n,
        "averages": {
            "clarity_score": avg("clarity_score"),
            "usefulness_score": avg("usefulness_score"),
            "adequacy_score": avg("adequacy_score"),
            "ease_of_use_score": avg("ease_of_use_score"),
            "satisfaction_score": avg("satisfaction_score"),
        },
        "distributions": {
            "clarity_score": distribution("clarity_score"),
            "usefulness_score": distribution("usefulness_score"),
            "adequacy_score": distribution("adequacy_score"),
            "ease_of_use_score": distribution("ease_of_use_score"),
            "satisfaction_score": distribution("satisfaction_score"),
        },
        "comments": comments,
        "sessions": {
            "started": len(started_sessions),
            "finished": len(finished_sessions),
            "completion_rate": completion_rate,
            "avg_chat_turns": avg_chat_turns,
        },
        "routes": [
            {"route": route, "count": count}
            for route, count in sorted(route_counts.items(), key=lambda item: item[1], reverse=True)
        ],
    })


@app.route('/api/stations', methods=['GET'])
def stations_data():
    query = (request.args.get("q") or "").strip()
    try:
        from plugfield_client import get_station_reports
        reports = get_station_reports(query=query or None)
        return jsonify({
            "count": len(reports),
            "items": reports,
        })
    except Exception as e:
        return jsonify({"error": f"Falha ao carregar estacoes: {str(e)}"}), 500


@app.route('/results-data', methods=['GET'])
@require_auth
def results_data():
    db_result = _aggregate_results_data_db()
    if db_result is not None:
        return jsonify(db_result)
    rows = _read_jsonl(USER_LOG_PATH)
    return jsonify(_build_results_payload(rows))


@app.route('/logs-csv', methods=['GET'])
@require_auth
def logs_csv():
    try:
        limit = int(request.args.get("limit", "1000"))
    except Exception:
        limit = 1000
    q_session = (request.args.get("session_id") or request.args.get("user_id") or "").strip()
    q_intent = (request.args.get("intent") or "").strip().upper()
    q_passed = (request.args.get("passed") or "").strip().lower()
    db_entries = _fetch_user_logs_db(limit=limit, q_session=q_session, q_intent=q_intent, q_passed=q_passed)
    entries = []
    if db_entries is not None:
        entries = db_entries
    elif os.path.exists(USER_LOG_PATH):
        with open(USER_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if q_session and str(item.get("session_id") or item.get("user_id") or "") != q_session:
                        continue
                    if q_intent and str(item.get("intent", "")).upper() != q_intent:
                        continue
                    if q_passed in {"true", "false"} and str(item.get("passed")).lower() != q_passed:
                        continue
                    entries.append(item)
                except Exception:
                    continue
    headers = [
        "ts","session_id","message","expected_intent","intent","passed","engine",
        "latency_ms","decision_source","reason","llm_ms","llm_new_tokens",
        "llm_stop_reason","entrada_norm","raw_output","final_output"
    ]
    lines = [",".join(headers)]
    for it in entries[-limit:]:
        row = []
        for h in headers:
            v = it.get(h, "")
            s = str(v).replace('"', '""')
            if "," in s or "\n" in s:
                s = f'"{s}"'
            row.append(s)
        lines.append(",".join(row))
    csv_body = "\n".join(lines)
    return Response(csv_body, mimetype="text/csv")


@app.route('/settings', methods=['POST'])
@require_auth
def settings():
    global CURRENT_MODE, CURRENT_CFG
    payload = request.get_json() or {}
    mode = (payload.get("mode") or CURRENT_MODE).strip()
    cfg = (payload.get("cfg") or CURRENT_CFG).strip()
    overrides = payload.get("overrides") or {}

    with STATE_LOCK:
        envs = {}
        envs.update(_env_for_cfg(cfg))
        envs.update(_env_for_mode(mode))
        if isinstance(overrides, dict):
            envs.update({str(k): str(v) for k, v in overrides.items()})
        _apply_env(envs)
        CURRENT_MODE = mode
        CURRENT_CFG = cfg
        _init_orchestrator()

    return jsonify({
        "status": "ok",
        "mode": CURRENT_MODE,
        "cfg": CURRENT_CFG,
        "applied": envs,
    })


# ── Admin phones — rotas ─────────────────────────────────────────────────────

@app.route('/api/admin/phones', methods=['GET'])
@require_auth
def admin_phones_list():
    """Lista todos os numeros administradores cadastrados."""
    db_rows = _list_admin_phones_db()
    if db_rows is not None:
        return jsonify(db_rows)
    rows = _list_admin_phones_jsonl()
    return jsonify([r for r in rows if isinstance(r, dict)])


@app.route('/api/admin/phones', methods=['POST'])
@require_auth
def admin_phones_add():
    """Cadastra ou reativa um numero como administrador.
    Body JSON: {"phone_number": "5511999990000", "name": "Operador 1"}
    """
    payload = request.get_json(silent=True) or {}
    phone = _normalize_phone(payload.get("phone_number", ""))
    name  = str(payload.get("name") or "").strip()
    if not phone:
        return _json_error("Campo phone_number obrigatorio.", 400)
    ok = _add_admin_phone_db(phone, name)
    if ok:
        return jsonify({"phone_number": phone, "name": name, "active": True}), 201
    existing = [r for r in _list_admin_phones_jsonl()
                if isinstance(r, dict)
                and _normalize_phone(r.get("phone_number", "")) == phone
                and r.get("active")]
    if existing:
        return _json_error("Numero ja cadastrado.", 409)
    rec = {"phone_number": phone, "name": name, "active": True, "created_at": _now_iso()}
    _append_jsonl(ADMIN_PHONES_PATH, rec)
    return jsonify(rec), 201


@app.route('/api/admin/phones/<phone>', methods=['DELETE'])
@require_auth
def admin_phones_remove(phone):
    """Desativa (soft-delete) um numero administrador."""
    normalized = _normalize_phone(phone)
    if not normalized:
        return _json_error("Numero invalido.", 400)
    ok = _remove_admin_phone_db(normalized)
    if ok:
        return jsonify({"phone_number": normalized, "active": False})
    rows = _list_admin_phones_jsonl()
    found = False
    updated = []
    for r in rows:
        if isinstance(r, dict) and _normalize_phone(r.get("phone_number", "")) == normalized:
            r["active"] = False
            found = True
        updated.append(r)
    if not found:
        return _json_error("Numero nao encontrado.", 404)
    with open(ADMIN_PHONES_PATH, "w", encoding="utf-8") as fh:
        for r in updated:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return jsonify({"phone_number": normalized, "active": False})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))
