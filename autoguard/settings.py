# CAPABILITY: autoguard settings — key/value table + optional environment overrides + validation + safe display.
# PRECEDENCE: environment variable (set and non-empty) > database (setup wizard / Settings page) > default.
# SECRETS: nextdns_api_key, llm_api_key, api_token are never rendered back in full — masked() shows the last 4 chars.
import json, os, re, secrets
from zoneinfo import ZoneInfo

DEFAULT_GUIDANCE = ("Mainstream AI assistants (ChatGPT, Claude, Gemini, Copilot, Perplexity); messaging with known "
                    "contacts (WhatsApp, Messenger, LINE, Discord, Telegram, Signal); YouTube and streaming; games; "
                    "shopping; news; history, war and military history; school, homework and research sites.")

# Provider presets — any OpenAI-compatible /chat/completions endpoint works ("custom").
# json_mode: schema = strict json_schema · object = json_object · prompt = plain text, JSON parsed from the reply.
PRESETS = {
    "openai":     {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-5.4-mini", "extra": {},
                   "json_mode": "schema", "key_url": "https://platform.openai.com/api-keys"},
    "anthropic":  {"label": "Anthropic (Claude)", "base_url": "https://api.anthropic.com/v1", "model": "claude-haiku-4-5",
                   "extra": {"max_tokens": 8000}, "json_mode": "prompt", "key_url": "https://console.anthropic.com/settings/keys"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-5.4-mini",
                   "extra": {"provider": {"require_parameters": True}}, "json_mode": "auto", "key_url": "https://openrouter.ai/keys"},
    "cerebras":   {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "model": "qwen-3.8-27b",
                   "extra": {"reasoning_effort": "low"}, "json_mode": "schema", "key_url": "https://cloud.cerebras.ai/"},
    "ollama":     {"label": "Ollama (on your network)", "base_url": "http://host.docker.internal:11434/v1", "model": "qwen3:8b",
                   "extra": {}, "json_mode": "object", "key_url": "https://ollama.com/"},
    "custom":     {"label": "Other OpenAI-compatible", "base_url": "", "model": "", "extra": {}, "json_mode": "auto", "key_url": ""},
}

DEFAULTS = {
    "setup_done": "0", "setup_step": "account",
    "nextdns_api_key": "",
    "llm_provider": "openai", "llm_base_url": PRESETS["openai"]["base_url"], "llm_model": PRESETS["openai"]["model"],
    "llm_api_key": "", "llm_extra": "{}", "llm_json_mode": "schema", "llm_batch": "40",
    "block_at": "0.8", "review_at": "0.5", "max_blocks_per_run": "40",
    "scan_interval_hours": "4", "first_lookback_days": "7",
    "timezone": "UTC", "bedtime_start": "", "bedtime_end": "",
    "allowed_guidance": DEFAULT_GUIDANCE, "never_block_extra": "",
    "dry_run": "0", "api_token": "",
}
ENV = {"nextdns_api_key": "NEXTDNS_API_KEY", "llm_api_key": "LLM_API_KEY", "llm_base_url": "LLM_BASE_URL",
       "llm_model": "LLM_MODEL", "llm_extra": "LLM_EXTRA_JSON", "llm_json_mode": "LLM_JSON_MODE",
       "api_token": "AUTOGUARD_API_TOKEN", "timezone": "TZ"}
SECRET = {"nextdns_api_key", "llm_api_key", "api_token"}
FLOAT, BOOL = {"block_at", "review_at"}, {"setup_done", "dry_run"}
INT = {"llm_batch": (1, 200), "max_blocks_per_run": (1, 1000), "scan_interval_hours": (0, 168), "first_lookback_days": (1, 90)}
DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")

def env(key):
    name = ENV.get(key); return os.environ.get(name, "").strip() if name else ""

def get(con, key):
    if env(key): return env(key)
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else DEFAULTS.get(key, "")

def source(con, key):
    if env(key): return "environment"
    return "saved" if con.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone() else "default"

def put(con, key, value):
    if key not in DEFAULTS: raise KeyError(key)
    con.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

def masked(con, key):
    v = get(con, key); return f"••••{v[-4:]}" if len(v) > 8 else ("••••" if v else "")

def ensure_api_token(con):
    if not get(con, "api_token"): put(con, "api_token", secrets.token_urlsafe(32))

def snapshot(con):
    """Typed settings for one scan/request. Bad stored values fall back to defaults (never crash a scan)."""
    typed = lambda k, v: (float(v) if k in FLOAT else int(v) if k in INT else v == "1" if k in BOOL
                          else json.loads(v or "{}") if k == "llm_extra" else v)
    cfg = {}
    for k in DEFAULTS:
        try: cfg[k] = typed(k, get(con, k))
        except (ValueError, TypeError): cfg[k] = typed(k, DEFAULTS[k])
    cfg["never_block_extra"] = [d for d in cfg["never_block_extra"].split() if d]
    return cfg

def normalize_domain(raw):
    d = (raw or "").strip().lower()
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d).split("/")[0].split("?")[0].split("#")[0].split(":")[0].strip(".")
    return d if DOMAIN.match(d) else ""

def clean(key, raw):
    """Validate one user-entered value → (stored string, error|None)."""
    raw = (raw or "").strip()
    try:
        if key in FLOAT:
            v = float(raw); assert 0 < v <= 1, "must be between 0 and 1"; return str(v), None
        if key in INT:
            lo, hi = INT[key]; v = int(raw); assert lo <= v <= hi, f"must be {lo}–{hi}"; return str(v), None
        if key in BOOL: return ("1" if raw in ("1", "on", "true", "yes") else "0"), None
        if key in ("bedtime_start", "bedtime_end"):
            if not raw: return "", None
            assert re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", raw), "use HH:MM (24 h)"; return raw, None
        if key == "timezone": ZoneInfo(raw); return raw, None
        if key == "llm_extra":
            v = json.loads(raw or "{}"); assert isinstance(v, dict), "must be a JSON object"; return json.dumps(v), None
        if key == "llm_base_url":
            assert re.match(r"^https?://[^\s/]+", raw), "must start with http:// or https://"; return raw.rstrip("/"), None
        if key == "llm_json_mode":
            assert raw in ("auto", "schema", "object", "prompt"), "unknown mode"; return raw, None
        if key == "llm_provider":
            assert raw in PRESETS, "unknown provider"; return raw, None
        if key == "never_block_extra":
            ds = [normalize_domain(x) for x in re.split(r"[\s,]+", raw) if x]
            assert all(ds), "one domain per line, e.g. school.example.org"; return "\n".join(sorted(set(ds))), None
        if key == "llm_model": assert raw, "model name is required"; return raw, None
        return raw, None
    except (ValueError, AssertionError, KeyError, Exception) as e:  # noqa: BLE001 — every failure is a form error
        return None, str(e) or "invalid value"
