# CAPABILITY: AI topic classifier over ANY OpenAI-compatible /chat/completions API (OpenAI, Anthropic's
#             OpenAI-compat endpoint, OpenRouter, Cerebras, Ollama, LM Studio, vLLM …).
# JSON MODES (settings.llm_json_mode): schema = strict json_schema · object = json_object · prompt = none (JSON is
#   asked for in the prompt and parsed out of the reply) · auto = try schema → object → prompt on HTTP 400/422.
#   Anthropic's compat endpoint ignores response_format, so its preset uses prompt mode. The working combo per
#   (base_url, model) is cached for the process lifetime.
# INPUTS: domains + evidence, active topics, parent's guidance + past decisions.
# OUTPUT: {domain: (topic, conf, reason, kind|None)}.
#         Domains missing from the reply stay pending and are retried next scan.
import json, re, socket, sys, time, urllib.error, urllib.request
from . import config

class LLMError(Exception):
    def __init__(self, msg, code=None): super().__init__(msg); self.code = code

FIXED = ("Ads, analytics, CDNs, telemetry, app or OS infrastructure, and parked or unknown domains with no evidence are "
         "always none.")
SHAPE = ('Reply with ONLY a JSON object, no markdown or prose: {"results": [{"domain": "<domain>", "topic": "<topic id or '
         'none>", "confidence": <number 0-1>, "kind": "website|infrastructure", "reason": "<max 20 words citing the evidence>"}]} '
         '— one entry per domain.')
KIND = ('kind: "website" if it is a site or app a person would recognise and open; "infrastructure" if it is a background '
        'service — CDN, API, ads, analytics, tracking, telemetry, load balancer, update or app back-end server.')
_WORKS = {}   # (base_url, model) -> (mode, send_temperature)

def schema(topic_ids):
    item = {"type": "object", "additionalProperties": False, "required": ["domain", "topic", "confidence", "kind", "reason"],
            "properties": {"domain": {"type": "string"}, "topic": {"type": "string", "enum": [*topic_ids, "none"]},
                           "confidence": {"type": "number"}, "kind": {"type": "string", "enum": ["website", "infrastructure"]},
                           "reason": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["results"],
            "properties": {"results": {"type": "array", "items": item}}}

def messages(topics, items, guidance, ok=(), bl=()):
    sys_ = ("You classify internet domains from a child's DNS logs for a parent's content filter. For EVERY domain "
            "choose exactly one topic id from this list, or \"none\":\n"
            + "\n".join(f"- {t['id']}: {t['description']}" for t in topics)
            + f"\nThe parent says these are FINE (topic none): {guidance}\n{FIXED}\n"
            "Evidence order: page title/description first, then the sample hostnames; the domain name alone is weak "
            "evidence (names mislead). confidence = probability that the site's MAIN purpose is that topic. Be "
            "conservative: if unsure, lower the confidence.\n" + KIND)
    if ok: sys_ += "\nThe parent reviewed and ALLOWED: " + ", ".join(ok)
    if bl: sys_ += "\nThe parent manually BLOCKED: " + ", ".join(bl)
    rows = [{"domain": i["domain"], "hosts": list(i.get("samples") or [])[:3], "title": i.get("title"),
             "description": i.get("description"), "unreachable": bool(i.get("fetch_error"))} for i in items]
    return [{"role": "system", "content": sys_ + "\n" + SHAPE},
            {"role": "user", "content": "Classify every domain:\n" + json.dumps(rows, ensure_ascii=False)}]

def _errmsg(raw):
    try:
        d = json.loads(raw); e = d.get("error", d) if isinstance(d, dict) else d
        return (e.get("message") if isinstance(e, dict) else str(e))[:300]
    except ValueError: return raw[:300]

def _post(cfg, body, tries=4):
    url = cfg["llm_base_url"].rstrip("/") + "/chat/completions"
    hdr = {"Authorization": f"Bearer {cfg['llm_api_key']}", "Content-Type": "application/json", "User-Agent": config.UA}
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), hdr, method="POST"), timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()[:600].decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and n < tries - 1:
                wait = min(int(e.headers.get("retry-after") or 15 * (n + 1)), 90)
                print(f"AUTOGUARD_LLM_RETRY code={e.code} wait_s={wait}", file=sys.stderr, flush=True); time.sleep(wait); continue
            raise LLMError(f"HTTP {e.code}: {_errmsg(raw)}", e.code) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            if n == 0 and not isinstance(reason, socket.gaierror): time.sleep(5); continue   # one retry; DNS failure = fail fast
            raise LLMError(f"cannot reach {url}: {reason}") from None
        except ValueError: raise LLMError("AI endpoint returned non-JSON (is the base URL right?)") from None

def content(resp):
    try: c = resp["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError): raise LLMError(f"unexpected reply shape: {str(resp)[:150]}") from None
    if isinstance(c, list): c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""

def parse(text):
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
    cands = [t]
    if "{" in t: cands.append(t[t.find("{"): t.rfind("}") + 1])
    if "[" in t: cands.append(t[t.find("["): t.rfind("]") + 1])
    for c in cands:
        try: d = json.loads(c)
        except ValueError: continue
        if isinstance(d, list): return d
        if isinstance(d, dict):
            for k in ("results", "domains", "verdicts", "classifications"):
                if isinstance(d.get(k), list): return d[k]
            if "domain" in d: return [d]
    raise LLMError(f"AI reply was not the JSON we asked for: {t[:120]!r}")

def chat_json(cfg, msgs, sch):
    key = (cfg["llm_base_url"], cfg["llm_model"])
    mode = cfg.get("llm_json_mode") or "auto"
    combos = [_WORKS[key]] if key in _WORKS else [(m, True) for m in (["schema", "object", "prompt"] if mode == "auto" else [mode])]
    last, i = None, 0
    while i < len(combos):
        m, temp = combos[i]; i += 1
        body = {"model": cfg["llm_model"], "messages": msgs, **(cfg.get("llm_extra") or {})}
        if temp: body.setdefault("temperature", 0)
        if m == "schema": body["response_format"] = {"type": "json_schema", "json_schema": {"name": "verdicts", "strict": True, "schema": sch}}
        elif m == "object": body["response_format"] = {"type": "json_object"}
        try: resp = _post(cfg, body)
        except LLMError as e:
            rejected = e.code in (400, 422) or (e.code == 404 and "parameters" in str(e).lower())   # OpenRouter routing
            if not rejected: raise
            last = e; _WORKS.pop(key, None)
            if temp and "temperature" in str(e).lower(): combos.insert(i, (m, False))   # e.g. reasoning models
            continue
        out = parse(content(resp)); _WORKS[key] = (m, temp); return out, m
    raise last or LLMError("no request format was accepted")

def classify(items, topics, cfg, ok=(), bl=()):
    data, _ = chat_json(cfg, messages(topics, items, cfg["allowed_guidance"], ok, bl), schema([t["id"] for t in topics]))
    wanted, ok_topics = {i["domain"] for i in items}, {t["id"] for t in topics} | {"none"}
    out = {}
    for r in data:
        if not isinstance(r, dict): continue
        d = str(r.get("domain", "")).lower().strip()
        if d in wanted and r.get("topic") in ok_topics:
            try: c = max(0.0, min(1.0, float(r.get("confidence") or 0)))
            except (TypeError, ValueError): c = 0.0
            k = r.get("kind") if r.get("kind") in ("website", "infrastructure") else None
            out[d] = (r["topic"], c, str(r.get("reason", ""))[:300], k)
    return out

# Connection test: 3 synthetic sites with unambiguous evidence (no network fetch needed).
SAMPLES = [
    {"domain": "random-video-chat.example", "title": "Talk to Strangers! Free random video chat",
     "description": "Meet random people on webcam instantly — no sign up, anonymous", "expect": "stranger_chat"},
    {"domain": "wikipedia.example", "title": "Wikipedia, the free encyclopedia",
     "description": "The free encyclopedia that anyone can edit", "expect": "none"},
    {"domain": "ai-girlfriend.example", "title": "Your uncensored AI girlfriend — NSFW chat, no filters",
     "description": "Roleplay with AI companions without limits", "expect": "uncensored_ai"},
]

def test(cfg, topics):
    t0 = time.time()
    if not cfg.get("llm_api_key") and "localhost" not in cfg["llm_base_url"] and "host.docker.internal" not in cfg["llm_base_url"]:
        return {"ok": False, "error": "No API key entered.", "seconds": 0}
    try: res = classify([dict(s, samples=[s["domain"]]) for s in SAMPLES], topics, cfg)
    except LLMError as e: return {"ok": False, "error": str(e), "seconds": round(time.time() - t0, 1)}
    rows = [{"domain": s["domain"], "expect": s["expect"], "got": res.get(s["domain"], ("(no answer)", 0, ""))} for s in SAMPLES]
    ids = {t["id"] for t in topics}
    right = sum(1 for r in rows if r["got"][0] == r["expect"] or (r["expect"] not in ids and r["got"][0] == "none"))
    return {"ok": len(res) == len(SAMPLES), "seconds": round(time.time() - t0, 1), "rows": rows, "right": right,
            "mode": _WORKS.get((cfg["llm_base_url"], cfg["llm_model"]), ("?",))[0]}
