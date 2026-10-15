# CAPABILITY: autoguard HTML — written for a NON-TECHNICAL parent: plain words, one decision per button, noise hidden.
#             Server-rendered, light theme, no external assets. Pure rendering + read queries; writes go via web.py.
# CONTEXT `ctx`: con, user {id, username, csrf} | None, q (query dict), msg (flash), path, result (page extras).
# VOCABULARY (keep it consistent): site · device · blocked · "to check" (review) · fine (owner_ok) · hidden (ignored or
#   background service) · check (scan). Never show parents: domain, DNS, profile id (except Settings), confidence %, verdict.
# DEFAULT VIEWS show only what may be a problem: Blocked + To check. Fine/clean/background sites are opt-in pages.
import html, json, math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from . import config, scheduler, settings as S

PAGE = 50
esc = lambda s: html.escape(str(s if s is not None else ""), quote=True)
REVIEW = "verdict='review' OR (verdict='block' AND NOT EXISTS (SELECT 1 FROM blocks b WHERE b.domain=domains.domain))"
OTHER = "verdict='clean' AND kind='website' AND last_blocked=0"
BACKGROUND = "verdict='clean' AND COALESCE(kind,'infrastructure')='infrastructure' AND last_blocked=0"
NEXTDNS_RULES = "verdict='clean' AND last_blocked=1"

def tzof(con):
    try: return ZoneInfo(S.get(con, "timezone") or "UTC")
    except Exception: return timezone.utc  # noqa: BLE001

def parse_ts(ts): return ts if isinstance(ts, datetime) else datetime.fromisoformat(ts.replace("Z", "+00:00"))
def fmt(ts, tz): return parse_ts(ts).astimezone(tz).strftime("%d %b %H:%M") if ts else "—"

def ago(ts):
    if not ts: return "never"
    s = (datetime.now(timezone.utc) - parse_ts(ts)).total_seconds()
    if s < 90: return "just now"
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= n: k = int(s // n); return f"{k} {unit}{'s' if k != 1 else ''} ago"

def when(due, tz):
    if not due: return "not scheduled"
    return "any moment now" if due <= datetime.now(timezone.utc) else f"at {parse_ts(due).astimezone(tz).strftime('%H:%M')}" \
        if due - datetime.now(timezone.utc) < timedelta(hours=20) else fmt(due, tz)

def sure(c):
    return "" if c is None else "very likely" if c >= .9 else "likely" if c >= .75 else "possibly"

CSS = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#f6f6f3;color:#1d1d1b}
a{color:#1d4ed8}header{background:#fff;border-bottom:1px solid #e4e4df;position:sticky;top:0;z-index:5}
.bar{max-width:1180px;margin:0 auto;padding:10px 24px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.brand{font-weight:700;font-size:17px;color:#1d1d1b;text-decoration:none;margin-right:6px}
nav{display:flex;gap:2px;flex-wrap:wrap;flex:1}nav a{color:#4b4b47;text-decoration:none;padding:6px 11px;border-radius:8px;font-size:14.5px}
nav a.on{background:#eef2ff;color:#1e3a8a;font-weight:600}nav a:hover{background:#f1f1ec}
.badge{display:inline-block;min-width:20px;padding:0 6px;border-radius:999px;background:#f79009;color:#fff;font-size:12px;font-weight:700;text-align:center}
.subnav{display:flex;gap:4px;flex-wrap:wrap;margin:-6px 0 18px}.subnav a{font-size:13.5px;padding:5px 11px;border-radius:999px;background:#ecece6;color:#3b3b37;text-decoration:none}
.subnav a.on{background:#1d4ed8;color:#fff}
.who{font-size:13px;color:#666;display:flex;gap:8px;align-items:center}
main{max-width:1180px;margin:0 auto;padding:22px 24px 70px}h1{font-size:23px;margin:0 0 4px}
p.lead{color:#5b5b56;margin:0 0 18px;max-width:780px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}
.card{background:#fff;border:1px solid #e4e4df;border-radius:12px;padding:14px 16px;text-decoration:none;color:inherit;display:block}
.card b{display:block;font-size:26px;font-weight:650}.card span{color:#66665f;font-size:13px}.card.hot{border-color:#fdb022;background:#fffcf5}
section{background:#fff;border:1px solid #e4e4df;border-radius:12px;padding:18px 20px;margin-bottom:18px}
section h2{font-size:16.5px;margin:0 0 6px}p.hint{color:#66665f;margin:0 0 12px;font-size:13.5px}
.tbl{overflow-x:auto}table{width:100%;border-collapse:collapse}
th{text-align:left;font-weight:600;color:#5b5b56;font-size:12.5px;border-bottom:1px solid #e4e4df;padding:7px 8px}
td{border-bottom:1px solid #f0f0eb;padding:9px 8px;vertical-align:top}td.dom{font-weight:600;overflow-wrap:anywhere;min-width:160px}
.what{max-width:300px}.mut{color:#85857e;font-size:12.5px}
.pill{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12.5px;border:1px solid;margin:0 4px 4px 0;cursor:pointer;background:#fff;font-family:inherit}
.on-b{color:#b42318;border-color:#f4b9b3;background:#fef3f2}.off-b{color:#067647;border-color:#a9dcc0;background:#ecfdf3}
.tag{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12.5px;background:#eef2ff;color:#3538cd;white-space:nowrap}
.tag.nd{background:#f1f1ec;color:#4b4b47}.st{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12.5px;background:#f1f1ec}
.st.ok{background:#ecfdf3;color:#067647}.st.bad{background:#fef3f2;color:#b42318}.st.run{background:#fffaeb;color:#b54708}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}.tabs a{font-size:13.5px;padding:5px 12px;border-radius:999px;border:1px solid #d3d3cd;color:#3b3b37;text-decoration:none;background:#fff}
.tabs a.on{background:#1d1d1b;border-color:#1d1d1b;color:#fff}
button,.btn{white-space:nowrap;font:inherit;font-size:13.5px;border:1px solid #d3d3cd;background:#fff;border-radius:8px;padding:6px 12px;cursor:pointer;color:#1d1d1b;text-decoration:none;display:inline-block}
button:hover,.btn:hover{background:#f6f6f3}button.primary,.btn.primary{background:#1d4ed8;border-color:#1d4ed8;color:#fff}
button.primary:hover{background:#1e40af}button.danger{color:#b42318;border-color:#f4b9b3}button.ok{color:#067647;border-color:#a9dcc0}
button.small{padding:3px 10px;font-size:12.5px}form.inline{display:inline}label{font-size:13.5px}
input[type=text],input[type=password],input[type=number],input[type=search],select,textarea{font:inherit;font-size:14.5px;border:1px solid #d3d3cd;border-radius:8px;padding:7px 10px;width:100%;background:#fff;color:#1d1d1b}
input:focus,textarea:focus,select:focus{outline:2px solid #bfdbfe;border-color:#1d4ed8}
.field{margin-bottom:14px}.field>label{display:block;font-weight:600;margin-bottom:4px}.field .mut{display:block;margin-top:3px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0 18px}
.banner{border-radius:12px;padding:13px 16px;margin-bottom:16px;border:1px solid}
.bad{background:#fef3f2;border-color:#f4b9b3;color:#7a271a}.good{background:#ecfdf3;border-color:#a9dcc0;color:#054f31}
.info{background:#eff6ff;border-color:#bfdbfe;color:#1e3a8a}.warn{background:#fffaeb;border-color:#fedf89;color:#7a2e0e}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.right{margin-left:auto}
.pager{display:flex;gap:8px;align-items:center;margin-top:12px;font-size:13.5px;color:#5b5b56}
.choices{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px;margin-bottom:14px}
.choice{border:1px solid #d3d3cd;border-radius:10px;padding:10px 12px;display:flex;gap:8px;align-items:flex-start;cursor:pointer;background:#fff}
.choice:has(input:checked){border-color:#1d4ed8;background:#eff6ff}.choice small{display:block;color:#66665f}
.setup{max-width:760px;margin:30px auto;padding:0 18px}.steps{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}
.steps span{font-size:12.5px;padding:4px 10px;border-radius:999px;background:#ecece6;color:#5b5b56}.steps span.on{background:#1d4ed8;color:#fff}
.steps span.done{background:#d1fadf;color:#05603a}code{background:#f1f1ec;border-radius:5px;padding:1px 5px;font-size:12.5px}
details summary{cursor:pointer;color:#4b4b47;font-weight:600}
@media (max-width:640px){main{padding:16px 12px 60px}.bar{padding:8px 12px}section{padding:14px}}
"""
NAV = [("/", "Home"), ("/blocked", "Blocked"), ("/review", "To check"), ("/checked", "Other sites"), ("/allowed", "Fine sites"), ("/settings", "Settings")]
SUB = [("/settings", "Connections"), ("/topics", "What to block"), ("/users", "People"), ("/hidden", "Hidden sites"),
       ("/activity", "History"), ("/runs", "Checks")]

def doc(title, body, refresh=0):
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'{meta}<meta name="robots" content="noindex"><title>{esc(title)} · Autoguard</title><style>{CSS}</style></head><body>{body}</body></html>')

def flash(ctx):
    m = ctx.get("msg") or ""
    return f'<div class="banner {"bad" if m.startswith("!") else "good"}">{esc(m.lstrip("!"))}</div>' if m else ""

def count(con, where, *a): return con.execute(f"SELECT count(*) FROM domains WHERE {where}", a).fetchone()[0]

def layout(ctx, title, body, active="", refresh=0):
    con, u = ctx["con"], ctx["user"]
    todo = count(con, f"({REVIEW})")
    top = "/settings" if active in {p for p, _ in SUB} else active
    nav = "".join(f'<a href="{p}" class="{"on" if p == top else ""}">{n}{f" <span class=badge>{todo}</span>" if p == "/review" and todo else ""}</a>'
                  for p, n in NAV)
    sub = ('<div class="subnav">' + "".join(f'<a href="{p}" class="{"on" if p == active else ""}">{n}</a>' for p, n in SUB) + "</div>") if top == "/settings" else ""
    who = (f'<div class="who">{esc(u["username"])}<form class="inline" method="post" action="/logout">{csrf(ctx)}'
           f'<button class="small">Log out</button></form></div>') if u else ""
    dry = ('<div class="banner warn"><b>Trial mode is on</b> — Autoguard shows what it <i>would</i> block but doesn’t block anything yet. '
           'Turn it off in <a href="/settings#schedule">Settings</a> when you’re happy.</div>') if S.get(con, "dry_run") == "1" else ""
    return doc(title, f'<header><div class="bar"><a class="brand" href="/">🛡️ Autoguard</a><nav>{nav}</nav>{who}</div></header>'
                      f'<main>{sub}{dry}{flash(ctx)}{body}</main>', refresh)

def csrf(ctx): return f'<input type="hidden" name="csrf" value="{esc((ctx.get("user") or {}).get("csrf", ""))}">'

def button(ctx, action, label, fields=(), cls="", title=""):
    hid = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in fields)
    return (f'<form class="inline" method="post" action="{action}">{csrf(ctx)}{hid}'
            f'<button class="{cls}" title="{esc(title)}">{label}</button></form>')

def paging(ctx):
    try: page = max(1, int(ctx["q"].get("page", "1")))
    except ValueError: page = 1
    return page, (ctx["q"].get("q") or "").strip().lower()

def pager(path, page, total, q, keep=None):
    pages = max(1, math.ceil(total / PAGE)); base = {**(keep or {}), **({"q": q} if q else {})}
    link = lambda p, t: f'<a class="btn" href="{path}?{urlencode({**base, "page": p})}">{t}</a>'
    return (f'<div class="pager">{link(page - 1, "← Previous") if page > 1 else ""}'
            f'<span>Page {min(page, pages)} of {pages} · {total} total</span>{link(page + 1, "Next →") if page < pages else ""}</div>')

def search(path, q, keep=None):
    hid = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in (keep or {}).items())
    return (f'<form method="get" action="{path}" class="row" style="margin-bottom:12px">{hid}<input type="search" name="q" value="{esc(q)}" '
            f'placeholder="Search for a site…" style="max-width:300px"><button>Search</button>{f"<a href={path}>clear</a>" if q else ""}</form>')

def tabs(path, current, options, q=""):
    return '<div class="tabs">' + "".join(
        f'<a class="{"on" if k == current else ""}" href="{path}?{urlencode({"show": k, **({"q": q} if q else {})})}">{esc(label)}</a>'
        for k, label in options) + "</div>"

def devices(con): return [dict(r) for r in con.execute("SELECT id, name FROM profiles WHERE enabled=1 ORDER BY name")]
def topic_labels(con): return {r["id"]: r["label"] for r in con.execute("SELECT id, label FROM topics")}

# ── row cells ───────────────────────────────────────────────────────────────
def site(r):
    s = [x for x in json.loads(r["samples"] or "[]") if x != r["domain"]]
    tip = f' title="{esc("Also looked up as: " + ", ".join(s[:5]))}"' if s else ""
    return f'<td class="dom"{tip}>{esc(r["domain"])}</td>'

def what(r):
    return (f'<td class="what">{esc(r["title"])}</td>' if r["title"]
            else '<td class="what"><span class="mut">No description available</span></td>')

def why(r, tl, src="auto"):
    lab = tl.get(r["topic"]) if r["topic"] else None
    if src == "nextdns":
        head = (f'<span class="tag">{esc(lab)}</span> ' if lab else "") + '<span class="tag nd">On your NextDNS block list</span>'
    elif src == "owner" or r["confidence"] is None:
        head = '<span class="tag nd">You blocked it</span>'
    else:
        head = f'<span class="tag">{esc(lab or "Flagged")}</span> <span class="mut">{sure(r["confidence"])}</span>'
    # the AI's note explains a MATCH; for a NextDNS-list entry it doesn't match it reads as nonsense ("…not stranger chat")
    reason = r["reason"] if r["reason"] and r["reason"] != "nextdns_allowlist" and src != "owner" and (src != "nextdns" or lab) else ""
    return f'<td>{head}{f"<div class=mut>{esc(reason)}</div>" if reason else ""}</td>'

def visited(r):
    if not r["last_seen"] or not r["hits"]: return '<td><span class="mut">Not visited recently</span></td>'
    n, b = r["hits"], r["bedtime_hits"]
    return f'<td>{ago(r["last_seen"])}<div class="mut">{n} time{"s" if n != 1 else ""}{f" · {b} at night" if b else ""}</div></td>'

def pills(ctx, d, profs, state, back):
    out = []
    for p in profs:
        on = state.get((d, p["id"])) == "blocked"
        out.append(button(ctx, "/action", f'{"⛔" if on else "✓"} {esc(p["name"])}',
                          [("op", "unblock" if on else "block"), ("domain", d), ("profile", p["id"]), ("back", back)],
                          f'pill {"on-b" if on else "off-b"}', f'{"Blocked" if on else "Allowed"} on {p["name"]} — click to {"allow" if on else "block"} it there'))
    return "".join(out)

# ── home ────────────────────────────────────────────────────────────────────
PLAIN = {"ok": "Done", "ai_busy": "AI was busy", "llm_error": "AI problem", "failed": "Failed", "partial": "Partly done", "running": "Running", "interrupted": "Interrupted"}

def overview(ctx):
    con, tz = ctx["con"], tzof(ctx["con"])
    n = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    running = con.execute("SELECT * FROM runs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
    last = con.execute("SELECT * FROM runs WHERE status!='running' ORDER BY id DESC LIMIT 1").fetchone()
    devs, todo = len(devices(con)), count(con, f"({REVIEW})")
    H = []
    if running:
        H.append(f'<div class="banner info"><b>Checking now…</b> {esc(running["phase"] or "")}. This page updates by itself.</div>')
    elif last and last["status"] in ("llm_error", "failed", "partial", "interrupted"):
        H.append(f'<div class="banner bad"><b>The last check had a problem</b> ({ago(last["started"])}): {esc(last["note"] or PLAIN.get(last["status"]))}'
                 f'<br>Everything already blocked stays blocked. <a href="/settings">Check your settings</a></div>')
    else:
        busy = " The AI service was busy last time, so a few sites are still waiting — they’ll be checked next time." if last and last["status"] == "ai_busy" else ""
        H.append(f'<div class="banner good">✅ <b>Autoguard is watching {devs} device{"s" if devs != 1 else ""}.</b> '
                 f'Last check {ago(last["started"]) if last else "— none yet"}. Next check {when(scheduler.next_due(con), tz)}.{busy}</div>')
    if todo:
        H.append(f'<div class="banner warn"><b>{todo} site{"s" if todo != 1 else ""} need{"s" if todo == 1 else ""} your decision.</b> '
                 f'Autoguard isn’t sure about {"it" if todo == 1 else "them"}. <a href="/review">Have a look →</a></div>')
    week = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cards = [("Sites blocked", n("SELECT count(DISTINCT domain) FROM blocks WHERE state='blocked'"), "/blocked", False),
             ("New blocks this week", n("SELECT count(DISTINCT domain) FROM actions WHERE actor='autoguard' AND action='block' AND ts>=?", week), "/blocked?show=auto", False),
             ("To check", todo, "/review", bool(todo)),
             ("Fine sites", count(con, "verdict='owner_ok'"), "/allowed", False)]
    H.append('<div class="cards">' + "".join(f'<a class="card{" hot" if hot else ""}" href="{h}"><b>{v}</b><span>{k}</span></a>' for k, v, h, hot in cards) + "</div>")
    rows = con.execute("""SELECT d.* FROM domains d WHERE EXISTS (SELECT 1 FROM blocks b WHERE b.domain=d.domain AND b.state='blocked' AND b.source='auto')
                          ORDER BY d.decided_at DESC LIMIT 8""").fetchall()
    tl = topic_labels(con)
    H.append('<section><div class="row"><h2>Recently blocked by Autoguard</h2><a class="right" href="/blocked">See everything blocked →</a></div>'
             '<div class="tbl"><table><tr><th>Site</th><th>What it is</th><th>Why</th><th>Last visited</th></tr>'
             + "".join(f"<tr>{site(r)}{what(r)}{why(r, tl)}{visited(r)}</tr>" for r in rows) + "</table></div>"
             + ("" if rows else '<p class="mut">Nothing new yet — that’s good news. Autoguard checks every new site your children visit.</p>') + "</section>")
    other = count(con, OTHER)
    H.append(f'<div class="row">{button(ctx, "/action", "Check now", [("op", "run")], "primary")}'
             f'<span class="mut">Autoguard checks by itself every {esc(S.get(con, "scan_interval_hours"))} hours. '
             f'{f"<a href=/checked>{other} other websites</a> were checked and look fine." if other else ""}</span></div>')
    return layout(ctx, "Home", "".join(H), "/", refresh=8 if running else 0)

# ── blocked ─────────────────────────────────────────────────────────────────
BLOCKED_TABS = [("all", "Everything"), ("auto", "Found by Autoguard"), ("owner", "Blocked by you"), ("nextdns", "On your NextDNS list")]

def blocked(ctx):
    con = ctx["con"]; page, q = paging(ctx); like = f"%{q}%"
    show = ctx["q"].get("show", "all"); show = show if show in dict(BLOCKED_TABS) else "all"
    cond, args = ("", []) if show == "all" else (" AND b.source=?", [show])
    base = f"FROM domains d WHERE EXISTS (SELECT 1 FROM blocks b WHERE b.domain=d.domain AND b.state='blocked'{cond}) AND d.domain LIKE ?"
    total = con.execute(f"SELECT count(*) {base}", (*args, like)).fetchone()[0]
    rows = con.execute(f"SELECT d.* {base} ORDER BY COALESCE(d.decided_at, d.first_seen) DESC, d.domain LIMIT ? OFFSET ?",
                       (*args, like, PAGE, (page - 1) * PAGE)).fetchall()
    profs, tl = devices(con), topic_labels(con)
    ds = [r["domain"] for r in rows]
    st = con.execute(f"SELECT domain, profile, state, source FROM blocks WHERE domain IN ({','.join('?' * len(ds))})", ds).fetchall() if ds else []
    state = {(r["domain"], r["profile"]): r["state"] for r in st}
    srcs = {}
    for r in st:
        if r["state"] == "blocked": srcs.setdefault(r["domain"], set()).add(r["source"])
    src = lambda d: next((s for s in ("auto", "owner", "nextdns") if s in srcs.get(d, ())), "auto")
    allp = [("profile", p["id"]) for p in profs]
    back = f"/blocked?{urlencode({'show': show, 'page': page, **({'q': q} if q else {})})}"
    body = ['<h1>Blocked sites</h1><p class="lead">These sites can’t be opened on your children’s devices. Each device is a button: '
            '<b>⛔ red = blocked there</b>, <b>✓ green = allowed there</b> — click to change it for that device only. '
            'Autoguard remembers what you choose.</p><section>', tabs("/blocked", show, BLOCKED_TABS, q),
            search("/blocked", q, {"show": show}),
            '<div class="tbl"><table><tr><th>Site</th><th>What it is</th><th>Why it’s blocked</th><th>Last visited</th><th>Devices</th><th></th></tr>']
    for r in rows:
        body.append(f'<tr>{site(r)}{what(r)}{why(r, tl, src(r["domain"]))}{visited(r)}<td>{pills(ctx, r["domain"], profs, state, back)}</td>'
                    f'<td>{button(ctx, "/action", "Allow everywhere", [("op", "unblock"), ("domain", r["domain"]), ("back", back)] + allp, "small")}</td></tr>')
    body.append("</table></div>" + ("" if rows else '<p class="mut">Nothing here.</p>') + pager("/blocked", page, total, q, {"show": show}) + "</section>")
    if show == "nextdns" or (show == "all" and any(src(d) == "nextdns" for d in ds)):
        body.append('<p class="mut">“On your NextDNS block list” means it was already blocked in your NextDNS account before Autoguard. '
                    'Allowing it here removes it from that list too.</p>')
    body.append(f'<section id="add"><h2>Block a site yourself</h2><p class="hint">Type the site’s address, for example <code>badsite.com</code>. '
                f'Its pages and sub-sites are blocked too.</p>'
                f'<form method="post" action="/action" class="row">{csrf(ctx)}<input type="hidden" name="op" value="add"><input type="hidden" name="back" value="/blocked">'
                f'<input type="text" name="domain" placeholder="badsite.com" style="max-width:260px" required>'
                + "".join(f'<label><input type="checkbox" name="profile" value="{esc(p["id"])}" checked> {esc(p["name"])}</label>' for p in profs)
                + '<button class="danger">Block</button></form></section>')
    return layout(ctx, "Blocked", "".join(body), "/blocked")

# ── list pages ──────────────────────────────────────────────────────────────
def simple_list(ctx, path, title, lead, where, order, cols, row, empty, top="", keep=None, wargs=()):
    con = ctx["con"]; page, q = paging(ctx); like = f"%{q}%"
    total = con.execute(f"SELECT count(*) FROM domains WHERE ({where}) AND domain LIKE ?", (*wargs, like)).fetchone()[0]
    rows = con.execute(f"SELECT * FROM domains WHERE ({where}) AND domain LIKE ? ORDER BY {order} LIMIT ? OFFSET ?",
                       (*wargs, like, PAGE, (page - 1) * PAGE)).fetchall()
    tl, profs = topic_labels(con), devices(con)
    body = (f'<h1>{title}</h1><p class="lead">{lead}</p><section>{top}{search(path, q, keep)}<div class="tbl"><table><tr>'
            + "".join(f"<th>{c}</th>" for c in cols) + "</tr>" + "".join(row(r, tl, profs) for r in rows) + "</table></div>"
            + ("" if rows else f'<p class="mut">{empty}</p>') + pager(path, page, total, q, keep) + "</section>")
    return layout(ctx, title, body, path), rows

def review(ctx):
    def row(r, tl, profs):
        allp = [("profile", p["id"]) for p in profs]; held = r["verdict"] == "block"
        return (f'<tr>{site(r)}{what(r)}{why(r, tl)}{visited(r)}<td class="row">'
                f'{button(ctx, "/action", "Block it", [("op", "block"), ("domain", r["domain"]), ("back", "/review")] + allp, "danger small")}'
                f'{button(ctx, "/action", "It’s fine", [("op", "ok"), ("domain", r["domain"]), ("back", "/review")], "ok small")}'
                f'{"<div class=mut>Will be blocked at the next check unless you say it’s fine.</div>" if held else ""}</td></tr>')
    return simple_list(ctx, "/review", "To check", "Autoguard thinks these <b>might</b> be a problem but isn’t sure enough to block them. "
                       "You decide: <b>Block it</b> (on every device) or <b>It’s fine</b>. Autoguard remembers and learns from your choices.",
                       REVIEW, "confidence DESC", ["Site", "What it is", "Why we’re asking", "Last visited", "Your decision"], row,
                       "Nothing to check — you’re all caught up. 🎉")[0]

def checked(ctx):
    def row(r, tl, profs):
        allp = [("profile", p["id"]) for p in profs]
        return (f'<tr>{site(r)}{what(r)}{visited(r)}<td class="row">'
                f'{button(ctx, "/action", "Block", [("op", "block"), ("domain", r["domain"]), ("back", "/checked")] + allp, "danger small")}'
                f'{button(ctx, "/action", "Fine", [("op", "ok"), ("domain", r["domain"]), ("back", "/checked")], "ok small", "Move to Fine sites")}'
                f'{button(ctx, "/action", "Hide", [("op", "hide"), ("domain", r["domain"]), ("back", "/checked")], "small", "Not a real website — never show it again")}</td></tr>')
    con = ctx["con"]; hidden = count(con, f"verdict IN ('ignored','skip') OR ({BACKGROUND}) OR ({NEXTDNS_RULES})")
    page_html, rows = simple_list(ctx, "/checked", "Other sites",
        "Websites your children visited that Autoguard checked and thinks are fine. <b>You don’t need to look at these.</b> "
        "If something catches your eye, <b>Block</b> it. Use <b>Fine</b> for sites you know, and <b>Hide</b> for things that aren’t real websites.",
        OTHER, "last_seen DESC", ["Site", "What it is", "Last visited", ""], row, "Nothing new here.",
        top=f'<p class="hint">{hidden} background services (ad servers, app back-ends, load balancers…) and big platforms are hidden. '
            f'<a href="/hidden">See them</a>.</p>')
    if rows:   # one click to clear the whole page into the Fine list
        hid = "".join(f'<input type="hidden" name="domain" value="{esc(r["domain"])}">' for r in rows)
        bulk = (f'<form method="post" action="/action" style="margin:0 0 14px">{csrf(ctx)}<input type="hidden" name="op" value="bulk_ok">'
                f'<input type="hidden" name="back" value="/checked">{hid}<button class="ok">✓ All {len(rows)} on this page look fine — clear them</button></form>')
        page_html = page_html.replace('<section><p class="hint">', f'<section>{bulk}<p class="hint">', 1)
    return page_html

HIDDEN_TABS = [("mine", "Hidden by you"), ("background", "Background services"), ("nextdns", "Blocked by your NextDNS rules"),
               ("builtin", "Big platforms")]

def hidden(ctx):
    show = ctx["q"].get("show", "background"); show = show if show in dict(HIDDEN_TABS) else "background"
    where = {"mine": "verdict='ignored'", "background": BACKGROUND, "nextdns": NEXTDNS_RULES, "builtin": "verdict='skip'"}[show]
    def row(r, tl, profs):
        act = "" if show in ("builtin", "nextdns") else button(ctx, "/action", "Show in Other sites", [("op", "unhide"), ("domain", r["domain"]), ("back", f"/hidden?show={show}")], "small")
        note = {"never_block": "Big platform — never blocked automatically", "already_blocked_in_nextdns": "Already blocked by your NextDNS list"}.get(r["reason"] or "", "")
        return f'<tr>{site(r)}{what(r) if show != "builtin" else f"<td class=mut>{note}</td>"}{visited(r)}<td>{act}</td></tr>'
    lead = ("Things Autoguard doesn’t bother you with: background services (ad and tracking servers, app back-ends, load balancers — "
            "not websites a person opens; Autoguard still checks them for problems), sites your NextDNS rules (porn, gambling, "
            "bedtime…) already block, and big platforms like Google or WhatsApp.")
    return simple_list(ctx, "/hidden", "Hidden sites", lead, where, "last_seen DESC", ["Site", "What it is", "Last visited", ""], row,
                       "Nothing here.", top=tabs("/hidden", show, HIDDEN_TABS), keep={"show": show})[0]

def allowed(ctx):
    def row(r, tl, profs):
        nd = r["reason"] == "nextdns_allowlist"
        act = ('<span class="mut">Remove it in NextDNS (Allowlist)</span>' if nd else
               button(ctx, "/action", "Remove", [("op", "unfine"), ("domain", r["domain"]), ("back", "/allowed")], "small", "Autoguard will check it again"))
        src = '<span class="tag nd">From your NextDNS allowlist</span>' if nd else "You said it’s fine"
        return (f'<tr>{site(r)}{what(r)}<td>{src}'
                f'<div class="mut">{ago(r["decided_at"])}</div></td><td>{act}</td></tr>')
    add = (f'<form method="post" action="/action" class="row" style="margin-bottom:14px">{csrf(ctx)}<input type="hidden" name="op" value="fine_add">'
           '<input type="hidden" name="back" value="/allowed"><input type="text" name="domain" placeholder="school-site.com" style="max-width:260px" required>'
           '<button class="ok">Add a site you know is fine</button></form>')
    return simple_list(ctx, "/allowed", "Fine sites", "Sites you’ve said are fine. Autoguard never blocks these and doesn’t ask the AI about them. "
                       "Add your children’s school sites, clubs and anything else you trust.", "verdict='owner_ok'", "decided_at DESC",
                       ["Site", "What it is", "Why it’s here", ""], row, "None yet.", top=add)[0]

ACT = {"block": "Blocked", "unblock": "Allowed", "mark_ok": "Marked fine", "fine_add": "Added to fine sites", "unfine": "Removed from fine sites",
       "bulk_ok": "Marked fine", "hide": "Hid", "unhide": "Unhid", "topic": "Changed what to block", "devices": "Changed devices",
       "settings": "Changed settings", "user_created": "Added a person", "setup_finished": "Finished setup",
       "nextdns_connected": "Connected NextDNS", "ai_connected": "Connected the AI"}

def activity(ctx):
    con, tz = ctx["con"], tzof(ctx["con"]); page, q = paging(ctx)
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM profiles")}
    total = con.execute("SELECT count(*) FROM actions WHERE COALESCE(domain,'') LIKE ?", (f"%{q}%",)).fetchone()[0]
    rows = con.execute("SELECT * FROM actions WHERE COALESCE(domain,'') LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?", (f"%{q}%", PAGE, (page - 1) * PAGE)).fetchall()
    dev = lambda a: names.get(a["profile"], "all devices" if a["action"] == "block" and a["actor"] == "autoguard" else "")
    body = ('<h1>History</h1><p class="lead">Everything Autoguard and the people in your family did.</p><section>' + search("/activity", q)
            + '<div class="tbl"><table><tr><th>When</th><th>Who</th><th>What</th><th>Site</th><th>Device</th></tr>'
            + "".join(f'<tr><td>{fmt(a["ts"], tz)}</td><td>{esc("Autoguard" if a["actor"] == "autoguard" else a["actor"])}</td>'
                      f'<td>{esc(ACT.get(a["action"], a["action"].replace("_", " ")))}{" <span class=mut>(" + esc(a["detail"]) + ")</span>" if a["action"] == "bulk_ok" else ""}</td>'
                      f'<td class="dom">{esc(a["domain"] or "")}</td><td>{esc(dev(a))}</td></tr>' for a in rows)
            + "</table></div>" + pager("/activity", page, total, q) + "</section>")
    return layout(ctx, "History", body, "/activity")

def held(r): return f' <span class="mut">(+{r["held"]} next time)</span>' if r["held"] else ""

def runs(ctx):
    con, tz = ctx["con"], tzof(ctx["con"]); page, _ = paging(ctx)
    total = con.execute("SELECT count(*) FROM runs").fetchone()[0]
    rows = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?", (PAGE, (page - 1) * PAGE)).fetchall()
    cls = {"ok": "ok", "running": "run", "ai_busy": "run"}
    body = (f'<h1>Checks</h1><p class="lead">Autoguard checks every {esc(S.get(con, "scan_interval_hours"))} hours '
            f'(next {when(scheduler.next_due(con), tz)}). Change it in <a href="/settings#schedule">Connections</a>.</p><section>'
            f'<div class="row" style="margin-bottom:10px">{button(ctx, "/action", "Check now", [("op", "run"), ("back", "/runs")], "primary")}</div>'
            '<div class="tbl"><table><tr><th>When</th><th>Started by</th><th>Result</th><th>Lookups read</th><th>New sites</th><th>Asked the AI</th>'
            '<th>Blocked</th><th>Note</th></tr>'
            + "".join(f'<tr><td>{fmt(r["started"], tz)}</td><td>{esc(r["trigger"])}</td><td><span class="st {cls.get(r["status"], "bad")}">{esc(PLAIN.get(r["status"], r["status"]))}</span>'
                      f'{"<div class=mut>" + esc(r["phase"]) + "</div>" if r["phase"] else ""}</td><td>{r["logs_read"]:,}</td><td>{r["new_domains"]:,}</td>'
                      f'<td>{r["classified"]:,}</td><td>{r["blocked"]}{held(r)}</td>'
                      f'<td class="mut">{esc(r["note"] or "")}</td></tr>' for r in rows)
            + "</table></div>" + ("" if rows else '<p class="mut">No checks yet.</p>') + pager("/runs", page, total, "") + "</section>")
    return layout(ctx, "Checks", body, "/runs", refresh=8 if any(r["status"] == "running" for r in rows) else 0)

# ── topics ──────────────────────────────────────────────────────────────────
def topic_form(ctx, t, action="/topics", extra=""):
    new = not t["id"]
    return (f'<form method="post" action="{action}" style="margin-bottom:16px">{csrf(ctx)}{extra}<div class="row">'
            f'<input type="text" name="tid" value="{esc(t["id"])}" placeholder="short_name" style="max-width:180px" {"" if new else "readonly"}>'
            f'<input type="text" name="label" value="{esc(t["label"])}" placeholder="Name you’ll see" style="max-width:280px">'
            f'<label><input type="checkbox" name="active" value="1" {"checked" if t["active"] else ""}> block this</label>'
            f'<button>{"Add" if new else "Save"}</button></div><textarea name="description" rows="3" style="margin-top:6px" '
            f'placeholder="Describe what counts — and what doesn’t. Give examples.">{esc(t["description"])}</textarea></form>')

def topics(ctx):
    ts = [dict(r) for r in ctx["con"].execute("SELECT * FROM topics ORDER BY id")]
    body = ('<h1>What to block</h1><p class="lead">The kinds of sites Autoguard looks for. The AI reads these descriptions word for word, '
            'so say what counts <b>and what doesn’t</b>, with examples. Untick “block this” to pause one. '
            '(Porn, gambling and dating sites are best blocked in NextDNS → Parental Control.)</p><section>'
            + "".join(topic_form(ctx, t) for t in ts) + '<h2>Add something else to block</h2>' + topic_form(ctx, {"id": "", "label": "", "description": "", "active": 1})
            + "</section>")
    return layout(ctx, "What to block", body, "/topics")

# ── users ───────────────────────────────────────────────────────────────────
def users(ctx):
    con, tz, me = ctx["con"], tzof(ctx["con"]), ctx["user"]
    from . import auth
    rows = auth.users(con)
    body = ('<h1>People</h1><p class="lead">Who can log in. Everyone here can see and change everything — add the other parent, not the children.</p>'
            '<section><div class="tbl"><table><tr><th>Name</th><th>Added</th><th>Last logged in</th><th></th></tr>'
            + "".join(f'<tr><td class="dom">{esc(u["username"])}{" (you)" if u["id"] == me["id"] else ""}</td><td>{fmt(u["created_at"], tz)}</td>'
                      f'<td>{ago(u["last_login"])}</td><td>{"" if u["id"] == me["id"] else button(ctx, "/users", "Remove", [("op", "delete"), ("uid", u["id"])], "danger small")}</td></tr>'
                      for u in rows) + "</table></div></section>"
            f'<section><h2>Add a person</h2><form method="post" action="/users">{csrf(ctx)}<input type="hidden" name="op" value="add"><div class="grid2">'
            '<div class="field"><label>Username</label><input type="text" name="username" required autocomplete="off"></div>'
            '<div class="field"><label>Password</label><input type="password" name="password" required minlength="10" autocomplete="new-password">'
            '<span class="mut">At least 10 characters. Tell them in person.</span></div></div><button class="primary">Add</button></form></section>'
            f'<section><h2>Change my password</h2><form method="post" action="/users">{csrf(ctx)}<input type="hidden" name="op" value="password"><div class="grid2">'
            '<div class="field"><label>New password</label><input type="password" name="password" required minlength="10" autocomplete="new-password"></div>'
            '<div class="field"><label>Repeat it</label><input type="password" name="confirm" required minlength="10" autocomplete="new-password"></div></div>'
            '<button>Change password</button><span class="mut"> You stay logged in here; other browsers are logged out.</span></form></section>')
    return layout(ctx, "People", body, "/users")

# ── shared connection forms (setup wizard + settings) ───────────────────────
def secret_field(con, key, label, help_html):
    if S.source(con, key) == "environment":
        return f'<div class="field"><label>{label}</label><div class="banner info" style="margin:0">Provided by the server environment (<code>{S.ENV[key]}</code>) — change it there.</div></div>'
    have = S.masked(con, key)
    return (f'<div class="field"><label>{label}</label><input type="password" name="{key}" autocomplete="off" '
            f'placeholder="{"Saved (" + have + ") — leave blank to keep" if have else "Paste your key"}">'
            f'<span class="mut">{help_html}</span></div>')

def env_or(con, key, inner):
    return (f'<div class="mut" style="margin:-8px 0 12px">Set by environment (<code>{S.ENV[key]}</code>).</div>' if S.source(con, key) == "environment" else "") + inner

def ai_fields(ctx):
    con = ctx["con"]; prov = S.get(con, "llm_provider")
    radios = "".join(f'<label class="choice"><input type="radio" name="llm_provider" value="{k}" {"checked" if k == prov else ""}>'
                     f'<span><b>{esc(p["label"])}</b><small>{esc(p["model"] or "any model")}</small></span></label>' for k, p in S.PRESETS.items())
    presets = json.dumps({k: {**p, "extra": json.dumps(p["extra"])} for k, p in S.PRESETS.items()})
    mode = S.get(con, "llm_json_mode")
    return (f'<div class="choices">{radios}</div><p class="hint" id="keyhint"></p>'
            + env_or(con, "llm_base_url", f'<div class="grid2"><div class="field"><label>API base URL</label><input type="text" name="llm_base_url" id="f_base" value="{esc(S.get(con, "llm_base_url"))}">'
                     '<span class="mut">Any OpenAI-compatible endpoint (the part before <code>/chat/completions</code>).</span></div>')
            + env_or(con, "llm_model", f'<div class="field"><label>Model</label><input type="text" name="llm_model" id="f_model" value="{esc(S.get(con, "llm_model"))}">'
                     '<span class="mut">A fast, cheap model is plenty — this is simple classification.</span></div></div>')
            + secret_field(con, "llm_api_key", "API key", "Stored only in this server's database. Never shown again in full.")
            + '<details><summary>Advanced</summary><div class="grid2" style="margin-top:10px">'
            + f'<div class="field"><label>JSON mode</label><select name="llm_json_mode" id="f_mode">'
            + "".join(f'<option value="{m}" {"selected" if m == mode else ""}>{t}</option>' for m, t in [
                ("auto", "Auto-detect"), ("schema", "Strict JSON schema"), ("object", "JSON object"), ("prompt", "Prompt only (parse reply)")])
            + '</select><span class="mut">Anthropic’s endpoint ignores schemas → “prompt only”.</span></div>'
            + f'<div class="field"><label>Extra request fields (JSON)</label><input type="text" name="llm_extra" id="f_extra" value="{esc(S.get(con, "llm_extra"))}">'
            '<span class="mut">e.g. <code>{"reasoning_effort": "low"}</code></span></div></div></details>'
            + f'<script>const P={presets};const set=(k)=>{{const p=P[k];if(!p)return;'
            'const h=document.getElementById("keyhint");h.innerHTML=p.key_url?("Get a key: <a target=_blank rel=noopener href=\\""+p.key_url+"\\">"+p.key_url+"</a>"):"";'
            'if(k==="custom")return;for(const [id,v] of [["f_base",p.base_url],["f_model",p.model],["f_extra",p.extra],["f_mode",p.json_mode]]){const e=document.getElementById(id);if(e)e.value=v;}};'
            'document.querySelectorAll("input[name=llm_provider]").forEach(r=>r.addEventListener("change",e=>set(e.target.value)));'
            'const c=document.querySelector("input[name=llm_provider]:checked");if(c){const p=P[c.value];document.getElementById("keyhint").innerHTML=p&&p.key_url?("Get a key: <a target=_blank rel=noopener href=\\""+p.key_url+"\\">"+p.key_url+"</a>"):"";}</script>')

def ai_result(res):
    if not res: return ""
    if not res["ok"]: return f'<div class="banner bad"><b>AI test failed</b> ({res.get("seconds", 0)} s): {esc(res.get("error", ""))}</div>'
    rows = "".join(f'<tr><td>{esc(r["domain"])}</td><td>{esc(r["expect"])}</td><td>{esc(r["got"][0])} ({r["got"][1]:.0%})</td><td class="mut">{esc(r["got"][2])}</td></tr>' for r in res["rows"])
    return (f'<div class="banner good"><b>AI connection works</b> — answered in {res["seconds"]} s using {esc(res["mode"])} mode; '
            f'{res["right"]}/3 test sites judged as expected.</div><div class="tbl"><table><tr><th>Test site</th><th>Expected</th><th>AI said</th><th>Reason</th></tr>{rows}</table></div>')

def device_rows(ctx, counts=None):
    rows = ctx["con"].execute("SELECT id, name, enabled FROM profiles ORDER BY name").fetchall()
    if not rows: return '<p class="mut">No NextDNS profiles found on this account.</p>'
    return "".join(f'<label class="choice"><input type="checkbox" name="profile" value="{esc(r["id"])}" {"checked" if r["enabled"] else ""}>'
                   f'<span><b>{esc(r["name"])}</b><small>profile {esc(r["id"])}'
                   f'{" · " + format(counts[r["id"]], ",") + " lookups in the last 7 days" if counts and r["id"] in counts else ""}</small></span></label>' for r in rows)

def pref_fields(ctx, include_lookback):
    con = ctx["con"]; v = lambda k: esc(S.get(con, k))
    opts = lambda key, choices: "".join(f'<option value="{a}" {"selected" if S.get(con, key) == str(a) else ""}>{b}</option>' for a, b in choices)
    return ('<div class="grid2">'
            + env_or(con, "timezone", f'<div class="field"><label>Time zone</label><input type="text" name="timezone" id="f_tz" value="{v("timezone")}">'
                     '<span class="mut">IANA name, e.g. <code>Europe/London</code>, <code>America/New_York</code>.</span></div>')
            + f'<div class="field"><label>Check every</label><select name="scan_interval_hours">{opts("scan_interval_hours", [(1, "hour"), (2, "2 hours"), (4, "4 hours"), (6, "6 hours"), (12, "12 hours"), (24, "day"), (0, "never (manual only)")])}</select></div>'
            + (f'<div class="field"><label>First check reads back</label><select name="first_lookback_days">{opts("first_lookback_days", [(1, "1 day"), (3, "3 days"), (7, "7 days"), (14, "14 days"), (30, "30 days")])}</select>'
               '<span class="mut">Limited by your NextDNS log retention.</span></div>' if include_lookback else "")
            + f'<div class="field"><label>Bedtime (optional)</label><div class="row"><input type="text" name="bedtime_start" value="{v("bedtime_start")}" placeholder="21:30" style="max-width:100px">'
            f'to<input type="text" name="bedtime_end" value="{v("bedtime_end")}" placeholder="07:00" style="max-width:100px"></div>'
            '<span class="mut">Only used to highlight late-night lookups. Set the actual bedtime blocks in NextDNS → Parental Control → Recreation time.</span></div></div>'
            f'<div class="field"><label>What’s fine in your family</label><textarea name="allowed_guidance" rows="3">{v("allowed_guidance")}</textarea>'
            '<span class="mut">Plain English, sent to the AI with every check. Anything listed here is never blocked by a topic.</span></div>'
            f'<div class="field"><label><input type="checkbox" name="dry_run" value="1" {"checked" if S.get(con, "dry_run") == "1" else ""}> '
            'Trial mode — record what would be blocked, but don’t change NextDNS</label></div>'
            "<script>const tz=document.getElementById('f_tz');if(tz&&tz.value==='UTC'){try{tz.value=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'}catch(e){}}</script>")

# ── settings ────────────────────────────────────────────────────────────────
def settings_page(ctx):
    con = ctx["con"]; r = ctx.get("result") or {}; v = lambda k: esc(S.get(con, k))
    sec = lambda sid, title, hint, inner, submit="Save": (
        f'<section id="{sid}"><h2>{title}</h2><p class="hint">{hint}</p><form method="post" action="/settings">{csrf(ctx)}'
        f'<input type="hidden" name="section" value="{sid}">{inner}<div class="row">{submit}</div></form></section>')
    nd = r.get("nextdns")
    body = ['<h1>Settings</h1><p class="lead">How Autoguard connects to NextDNS and the AI, and its rules. Keys are kept on this server only and never shown again in full.</p>']
    body.append(sec("nextdns", "NextDNS", 'Your API key is at <a target=_blank rel=noopener href="https://my.nextdns.io/account">my.nextdns.io/account</a> → API (bottom of the page).',
                    (f'<div class="banner {"good" if nd["ok"] else "bad"}">{esc(nd["msg"])}</div>' if nd else "")
                    + secret_field(con, "nextdns_api_key", "NextDNS API key", "Autoguard reads logs and adds/removes entries on the denylist of the devices you choose — nothing else."),
                    '<button class="primary" name="do" value="save">Save</button><button name="do" value="test">Test connection</button>'))
    body.append(sec("devices", "Devices", "Tick each child’s device (one NextDNS profile per device). Autoguard only reads and changes the ticked ones. "
                    "Unticking stops managing a device; blocks already on it stay until you remove them in NextDNS.",
                    f'<div class="choices">{device_rows(ctx, r.get("counts"))}</div>',
                    '<button class="primary" name="do" value="save">Save devices</button><button name="do" value="refresh">Reload list from NextDNS</button>'))
    body.append(sec("ai", "AI", "Any OpenAI-compatible API. Pick a provider to pre-fill the address and a sensible model, paste your key, then test.",
                    ai_result(r.get("ai")) + ai_fields(ctx),
                    '<button class="primary" name="do" value="save">Save</button><button name="do" value="test">Save &amp; test</button>'))
    body.append(sec("schedule", "Schedule &amp; preferences", "", pref_fields(ctx, include_lookback=False)))
    body.append(sec("rules", "Blocking rules", "The AI proposes, these rules decide.",
                    '<div class="grid2">'
                    f'<div class="field"><label>Block automatically at confidence ≥</label><input type="number" step="0.05" min="0.05" max="1" name="block_at" value="{v("block_at")}"></div>'
                    f'<div class="field"><label>Ask me to review at confidence ≥</label><input type="number" step="0.05" min="0.05" max="1" name="review_at" value="{v("review_at")}"></div>'
                    f'<div class="field"><label>Max new blocks per check</label><input type="number" min="1" max="1000" name="max_blocks_per_run" value="{v("max_blocks_per_run")}">'
                    '<span class="mut">A brake against a misbehaving AI. Extra matches wait for the next check.</span></div>'
                    f'<div class="field"><label>Sites per AI request</label><input type="number" min="1" max="200" name="llm_batch" value="{v("llm_batch")}"></div></div>'
                    f'<div class="field"><label>Never block these (one per line)</label><textarea name="never_block_extra" rows="4" placeholder="school.example.org">{v("never_block_extra")}</textarea>'
                    '<span class="mut">Added to the built-in list of big platforms (Google, Apple, Microsoft, Meta, WhatsApp, Discord, YouTube, ChatGPT …) and your NextDNS allowlist, which are never auto-blocked.</span></div>'))
    tok = r.get("token")
    body.append(sec("api", "API token", "For scripts: <code>GET /api/status.json</code> and <code>GET /api/denylist.json</code> with header "
                    "<code>Authorization: Bearer &lt;token&gt;</code>.",
                    (f'<div class="banner good">New token — copy it now, it won’t be shown again:<br><code style="user-select:all">{esc(tok)}</code></div>' if tok else
                     f'<p>Current token: <code>{esc(S.masked(con, "api_token") or "none")}</code>{" (from environment)" if S.source(con, "api_token") == "environment" else ""}</p>'),
                    '<button name="do" value="regenerate">Generate a new token</button>' if S.source(con, "api_token") != "environment" else ""))
    body.append(f'<p class="mut">Autoguard {config.VERSION}</p>')
    return layout(ctx, "Settings", "".join(body), "/settings")

# ── login + setup wizard ────────────────────────────────────────────────────
def card(title, inner, steps=""):
    return doc(title, f'<div class="setup"><h1 style="margin-bottom:14px">🛡️ Autoguard</h1>{steps}<section>{inner}</section></div>')

def login(next_url="/", err=""):
    return card("Log in", (f'<div class="banner bad">{esc(err)}</div>' if err else "")
                + f'<h2>Log in</h2><form method="post" action="/login"><input type="hidden" name="next" value="{esc(next_url)}">'
                '<div class="field"><label>Username</label><input type="text" name="username" autocomplete="username" required autofocus></div>'
                '<div class="field"><label>Password</label><input type="password" name="password" autocomplete="current-password" required></div>'
                '<button class="primary">Log in</button></form><p class="mut" style="margin-top:14px">Forgot it? On the server run '
                '<code>docker compose exec autoguard python -m autoguard reset-password &lt;username&gt;</code></p>')

STEPS = [("account", "Account"), ("nextdns", "NextDNS"), ("devices", "Devices"), ("ai", "AI"), ("prefs", "Preferences")]

def setup(ctx, step, err="", result=None):
    idx = [s for s, _ in STEPS].index(step)
    steps = '<div class="steps">' + "".join(f'<span class="{"on" if i == idx else "done" if i < idx else ""}">{i + 1}. {n}</span>' for i, (_, n) in enumerate(STEPS)) + "</div>"
    e = f'<div class="banner bad">{esc(err)}</div>' if err else ""
    con = ctx["con"]
    form = lambda inner, buttons: (f'<form method="post" action="/setup">{csrf(ctx)}<input type="hidden" name="step" value="{step}">{inner}'
                                   f'<div class="row" style="margin-top:6px">{buttons}</div></form>')
    back = lambda s: f'<a class="btn" href="/setup?step={s}">← Back</a>'
    if step == "account":
        inner = ('<h2>Welcome! Let’s set up Autoguard</h2><p class="hint">Autoguard watches the DNS lookups of your children’s devices in '
                 '<b>NextDNS</b>, asks an <b>AI</b> whether each new website is one of the topics you want gone (uncensored AI chat, '
                 'stranger chat, red-pill content by default) and blocks matches on every device. You review and undo anything from here.</p>'
                 '<p class="hint">You’ll need: a NextDNS account with each child’s device on its own profile, and an API key for an AI provider '
                 '(OpenAI, Anthropic, OpenRouter, Cerebras, or a local Ollama). Setup takes about five minutes.</p><h2>1. Create your login</h2>'
                 + form('<div class="field"><label>Username</label><input type="text" name="username" required autocomplete="username" autofocus></div>'
                        '<div class="grid2"><div class="field"><label>Password</label><input type="password" name="password" required minlength="10" autocomplete="new-password">'
                        '<span class="mut">At least 10 characters.</span></div><div class="field"><label>Repeat password</label>'
                        '<input type="password" name="confirm" required minlength="10" autocomplete="new-password"></div></div>',
                        '<button class="primary">Create account →</button>'))
    elif step == "nextdns":
        inner = ('<h2>2. Connect NextDNS</h2><p class="hint">Open <a target=_blank rel=noopener href="https://my.nextdns.io/account">my.nextdns.io/account</a>, '
                 'scroll to <b>API</b>, copy the key and paste it below. Each child’s device should already use its own NextDNS profile '
                 '(NextDNS → Setup guide). Autoguard needs logs switched on for those profiles (NextDNS → Settings → Logs).</p>'
                 + form(secret_field(con, "nextdns_api_key", "NextDNS API key", "Used to read logs and edit the denylist of the devices you choose."),
                        back("account") + '<button class="primary">Connect →</button>'))
    elif step == "devices":
        inner = ('<h2>3. Choose your children’s devices</h2><p class="hint">These are the profiles on your NextDNS account. Tick the ones your children use — '
                 'Autoguard reads their logs and blocks on all ticked devices. Leave your own profiles unticked. The lookup counts help you see which are in use.</p>'
                 + form(f'<div class="choices">{device_rows(ctx, result)}</div>', back("nextdns") + '<button class="primary">Continue →</button>'))
    elif step == "ai":
        inner = ('<h2>4. Connect an AI</h2><p class="hint">Autoguard sends the AI each new website’s name, page title and description (never page contents or '
                 'who visited). Pick a provider, paste a key, and test. A small, cheap model is enough — a typical home uses a few cents a day.</p>'
                 + ai_result(result) + form(ai_fields(ctx), back("devices") + '<button class="primary" name="do" value="test">Save &amp; test →</button>'
                                            '<button name="do" value="skip" class="right" title="Checks will collect sites but not block until the AI works">Skip for now</button>'))
    else:
        tps = "".join(f'<label class="choice"><input type="checkbox" name="topic" value="{esc(t["id"])}" {"checked" if t["active"] else ""}>'
                      f'<span><b>{esc(t["label"])}</b><small>{esc(t["description"][:150])}…</small></span></label>' for t in con.execute("SELECT * FROM topics ORDER BY id"))
        inner = ('<h2>5. What should Autoguard block?</h2><p class="hint">You can change the wording later (Settings → What to block). '
                 'When you finish, Autoguard also shows what’s already on your NextDNS block and allow lists.</p>'
                 + form(f'<div class="choices">{tps}</div>' + pref_fields(ctx, include_lookback=True),
                        back("ai") + '<button class="primary">Finish &amp; run first check</button>'))
    return card("Set up", e + inner, steps)
