# CAPABILITY: autoguard web server (stdlib) — routing, sessions, CSRF, setup wizard, settings/users/topics writes, API.
# FLOW GATES: no users → /setup (create account) · logged out → /login · setup unfinished → /setup · else dashboard.
# SECURITY: PBKDF2 passwords, HttpOnly SameSite=Lax session cookie (Secure behind https), per-session CSRF token on
#           every POST, same-origin check, login throttling, secrets never echoed. /healthz is the only open route.
# API: GET /api/status.json, /api/denylist.json — session or `Authorization: Bearer <api_token>`.
import hmac, json, sys, threading, traceback, urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import actions, auth, config, db, llm, nextdns, scan, scheduler, settings as S, views as V

COOKIE = "ag_session"
THROTTLE = auth.Throttle()
PAGES = {"/": V.overview, "/blocked": V.blocked, "/review": V.review, "/allowed": V.allowed, "/checked": V.checked, "/hidden": V.hidden,
         "/activity": V.activity, "/runs": V.runs, "/topics": V.topics, "/users": V.users, "/settings": V.settings_page}
STEP_ORDER = [s for s, _ in V.STEPS]

def start_scan(trigger):   # tests replace this with a synchronous call
    threading.Thread(target=scan.run, args=(trigger,), daemon=True, name=f"scan-{trigger}").start()

def safe_next(u): return u if u.startswith("/") and not u.startswith("//") else "/"

class Handler(BaseHTTPRequestHandler):
    server_version = "autoguard"
    protocol_version = "HTTP/1.1"

    def log_message(self, f, *a):
        if not self.path.startswith("/healthz"): print("AUTOGUARD_HTTP", f % a, file=sys.stderr, flush=True)

    # ── plumbing ────────────────────────────────────────────────────────────
    def send(self, code, body, ctype="text/html; charset=utf-8", headers=()):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Referrer-Policy", "same-origin")
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)

    def redirect(self, to, headers=()): self.send(303, "", "text/plain", [("Location", to), *headers])

    def back(self, default, msg=""):
        to = safe_next(self.f("back") or default)
        sep = "&" if "?" in to else "?"
        self.redirect(to + (sep + urllib.parse.urlencode({"msg": msg}) if msg else ""))

    def f(self, k, d=""): return (self.form.get(k) or [d])[0]
    def fl(self, k): return self.form.get(k, [])

    def cookie(self):
        c = SimpleCookie(self.headers.get("Cookie", "")); return c[COOKIE].value if COOKIE in c else ""

    def set_cookie(self, token, max_age):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
        return ("Set-Cookie", f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}")

    def same_origin(self):
        o = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not o: return True   # non-browser clients; browsers always send Origin on POST
        return urllib.parse.urlparse(o).netloc == self.headers.get("Host", "")

    def client_key(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def ctx(self, **kw):
        return {"con": self.con, "user": self.user, "q": self.query, "msg": self.query.get("msg", ""), "path": self.url_path, **kw}

    def do_GET(self): self.dispatch("GET")
    def do_POST(self): self.dispatch("POST")

    def dispatch(self, method):
        u = urllib.parse.urlparse(self.path); self.url_path = u.path
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/healthz": return self.send(200, "ok", "text/plain")
        self.con = db.connect()
        try: self.route(method, u.path)
        except Exception:  # noqa: BLE001
            traceback.print_exc(); self.send(500, V.doc("Error", '<main><h1>Something went wrong</h1><p>Check <code>docker logs autoguard</code>.</p></main>'))
        finally: self.con.close()

    # ── routing ─────────────────────────────────────────────────────────────
    def route(self, m, path):
        con = self.con; self.form = {}
        self.user = auth.session_user(con, self.cookie())
        if path.startswith("/api/"): return self.api(path)
        if m == "POST":
            if not self.same_origin(): return self.send(403, "Cross-site request refused.", "text/plain")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000: return self.send(413, "Too large.", "text/plain")
            self.form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)
        if path == "/logout" and m == "POST":
            auth.end_session(con, self.cookie()); return self.redirect("/login", [self.set_cookie("", 0)])
        if auth.count(con) == 0:
            return self.wizard(m) if path == "/setup" else self.redirect("/setup")
        if not self.user:
            if path == "/login": return self.login(m)
            return self.redirect("/login?" + urllib.parse.urlencode({"next": self.path if m == "GET" else "/"}))
        if m == "POST" and path != "/login" and not hmac.compare_digest(self.f("csrf"), self.user["csrf"]):
            return self.send(403, "This form expired — go back, reload the page and try again.", "text/plain")
        if path == "/login": return self.redirect("/")
        if S.get(con, "setup_done") != "1":
            return self.wizard(m) if path == "/setup" else self.redirect("/setup")
        if path == "/setup": return self.redirect("/")
        if m == "GET" and path in PAGES: return self.send(200, PAGES[path](self.ctx()))
        if m == "POST" and path in ("/action", "/settings", "/topics", "/users"):
            return getattr(self, "post_" + path.strip("/"))()
        self.send(404, V.layout(self.ctx(), "Not found", "<h1>Not found</h1>"))

    def api(self, path):
        tok = S.get(self.con, "api_token"); h = self.headers.get("Authorization", "")
        if not (self.user or (tok and hmac.compare_digest(h.encode(), f"Bearer {tok}".encode()))):
            return self.send(401, '{"error":"unauthorized"}', "application/json")
        if path == "/api/denylist.json": return self.send(200, json.dumps({"profiles": actions.export(self.con)}), "application/json")
        if path == "/api/status.json":
            r = self.con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            out = {"version": config.VERSION, "setup_done": S.get(self.con, "setup_done") == "1", "last_run": dict(r) if r else None,
                   "model": S.get(self.con, "llm_model"), "dry_run": S.get(self.con, "dry_run") == "1",
                   "verdicts": {v: n for v, n in self.con.execute("SELECT verdict, count(*) FROM domains GROUP BY verdict")}}
            return self.send(200, json.dumps(out), "application/json")
        self.send(404, '{"error":"not found"}', "application/json")

    # ── login ───────────────────────────────────────────────────────────────
    def login(self, m):
        nxt = safe_next(self.f("next") or self.query.get("next", "/"))
        if m == "GET": return self.send(200, V.login(nxt))
        key = self.client_key() + "|" + self.f("username").lower()
        if THROTTLE.locked(key): return self.send(429, V.login(nxt, "Too many attempts — wait 15 minutes."))
        uid = auth.verify(self.con, self.f("username"), self.f("password"))
        if not uid:
            THROTTLE.fail(key); print(f"AUTOGUARD_LOGIN_FAILED user={self.f('username')!r} ip={self.client_key()}", file=sys.stderr, flush=True)
            return self.send(401, V.login(nxt, "Wrong username or password."))
        THROTTLE.ok(key)
        self.redirect(nxt, [self.set_cookie(auth.new_session(self.con, uid), auth.SESSION_DAYS * 86400)])

    # ── setup wizard ────────────────────────────────────────────────────────
    def wizard(self, m):
        con = self.con
        cur = "account" if auth.count(con) == 0 else S.get(con, "setup_step")
        if cur == "account" and auth.count(con): cur = "nextdns"
        want = self.query.get("step", cur)
        view = want if want in STEP_ORDER and STEP_ORDER.index(want) <= STEP_ORDER.index(cur) and (want != "account" or not auth.count(con)) else cur
        if m == "GET":
            extra = self.device_counts() if view == "devices" else None
            return self.send(200, V.setup(self.ctx(), view, result=extra))
        step = self.f("step")
        if step not in STEP_ORDER or STEP_ORDER.index(step) > STEP_ORDER.index(cur): return self.redirect("/setup")
        advance = lambda nxt: (S.put(con, "setup_step", STEP_ORDER[max(STEP_ORDER.index(nxt), STEP_ORDER.index(cur))]), con.commit(),
                               self.redirect(f"/setup?step={nxt}"))
        err = lambda msg, result=None: self.send(400, V.setup(self.ctx(), step, msg, result))
        if step == "account":
            if auth.count(con): return self.redirect("/setup")
            uid, p = auth.create_user(con, self.f("username"), self.f("password"), self.f("confirm"))
            if p: return err(p)
            S.put(con, "setup_step", "nextdns"); con.commit()
            return self.redirect("/setup?step=nextdns", [self.set_cookie(auth.new_session(con, uid), auth.SESSION_DAYS * 86400)])
        if step == "nextdns":
            key = self.f("nextdns_api_key").strip() or S.get(con, "nextdns_api_key")
            if not key: return err("Paste your NextDNS API key.")
            try: profs = nextdns.client(key).profiles()
            except nextdns.NextDNSError as e: return err(f"NextDNS didn't accept that: {e}")
            if not profs: return err("Connected, but this NextDNS account has no profiles. Create one per child device first.")
            if S.source(con, "nextdns_api_key") != "environment": S.put(con, "nextdns_api_key", key)
            scan.sync_profiles(con, nextdns.client(key)); db.act(con, self.user["username"], "nextdns_connected", detail=f"{len(profs)} profiles")
            return advance("devices")
        if step == "devices":
            pids = [p for p in self.fl("profile") if con.execute("SELECT 1 FROM profiles WHERE id=?", (p,)).fetchone()]
            if not pids: return err("Tick at least one device.", self.device_counts())
            actions.set_devices(con, pids, self.user["username"]); return advance("ai")
        if step == "ai":
            if self.f("do") == "skip": return advance("prefs")
            problems = self.save_ai()
            if problems: return err("; ".join(problems))
            res = llm.test(S.snapshot(con), [dict(r) for r in con.execute("SELECT * FROM topics WHERE active=1")])
            if not res["ok"]: return err("", res)
            db.act(con, self.user["username"], "ai_connected", detail=f"{S.get(con, 'llm_model')} mode={res['mode']}"); con.commit()
            return advance("prefs")
        if step == "prefs":
            problems = self.save_keys(["timezone", "scan_interval_hours", "first_lookback_days", "bedtime_start", "bedtime_end", "allowed_guidance"], bools=["dry_run"])
            if problems: return err("; ".join(problems))
            chosen = set(self.fl("topic"))
            if not chosen: return err("Pick at least one topic.")
            con.execute("UPDATE topics SET active = 0"); con.executemany("UPDATE topics SET active=1 WHERE id=?", [(t,) for t in chosen])
            S.put(con, "setup_done", "1"); S.ensure_api_token(con); db.act(con, self.user["username"], "setup_finished"); con.commit()
            start_scan("first check")
            return self.redirect("/?" + urllib.parse.urlencode({"msg": "All set! Autoguard is doing its first check now — this page updates as it goes."}))

    def device_counts(self):
        try:
            c = nextdns.client(S.get(self.con, "nextdns_api_key"))
            return {r["id"]: c.queries_7d(r["id"]) for r in self.con.execute("SELECT id FROM profiles")}
        except nextdns.NextDNSError: return None

    # ── shared settings writers ─────────────────────────────────────────────
    def save_keys(self, keys, bools=()):
        problems, vals = [], {}
        for k in keys:
            if S.source(self.con, k) == "environment" or k not in self.form: continue
            v, e = S.clean(k, self.f(k))
            if e: problems.append(f"{k.replace('_', ' ')}: {e}")
            else: vals[k] = v
        for k in bools: vals[k] = "1" if self.f(k) else "0"
        if not problems:
            for k, v in vals.items(): S.put(self.con, k, v)
            self.con.commit()
        return problems

    def save_ai(self):
        p = self.save_keys(["llm_provider", "llm_base_url", "llm_model", "llm_json_mode", "llm_extra"])
        key = self.f("llm_api_key").strip()
        if not p and key and S.source(self.con, "llm_api_key") != "environment": S.put(self.con, "llm_api_key", key); self.con.commit()
        llm._WORKS.clear()
        return p

    # ── dashboard writes ────────────────────────────────────────────────────
    def post_action(self):
        con, who = self.con, self.user["username"]; op = self.f("op")
        typed = op in ("add", "fine_add")   # parent typed it: accept URLs, "www." means the whole site
        dom = S.normalize_domain(self.f("domain")) if typed or op == "block" else self.f("domain").strip().lower()
        if typed and dom.startswith("www."): dom = dom[4:]
        enabled = actions.enabled_pids(con); pids = [p for p in self.fl("profile") if p in enabled]
        dry = S.get(con, "dry_run") == "1"; nx = nextdns.client(S.get(con, "nextdns_api_key"))
        if op == "run":
            if con.execute("SELECT 1 FROM runs WHERE status='running'").fetchone(): return self.back("/", "A check is already running.")
            start_scan("dashboard"); return self.back("/", "Checking now — this takes a minute or two. Progress shows on Home.")
        if op in ("block", "add"):
            if not dom: return self.back("/blocked", "!That doesn't look like a website address (example: badsite.com).")
            if not pids: return self.back("/blocked", "!Tick at least one device.")
            probs = actions.block(con, nx, dom, pids, who, dry); msg = f"Blocked {dom} on {len(pids)} device(s)."
        elif op == "unblock" and dom and pids:
            probs = actions.unblock(con, nx, dom, pids, who, dry); msg = f"Unblocked {dom} on {len(pids)} device(s)."
        elif op == "ok" and dom: probs, msg = actions.mark_ok(con, dom, who), f"{dom} is on your Fine list — it won't be blocked."
        elif op == "fine_add":
            if not dom: return self.back("/allowed", "!That doesn't look like a website address (example: school.org).")
            probs, msg = actions.fine_add(con, dom, who), f"{dom} added to your Fine list."
        elif op == "unfine" and dom: probs, msg = actions.unfine(con, dom, who), f"{dom} removed — Autoguard will check it again if it's visited."
        elif op == "bulk_ok":
            n = actions.bulk_ok(con, [d.strip().lower() for d in self.fl("domain")][:500], who); probs, msg = [], f"{n} sites moved to Fine sites."
        elif op == "hide" and dom: probs, msg = actions.hide(con, dom, who), f"{dom} hidden. Find it under Settings → Hidden sites."
        elif op == "unhide" and dom: probs, msg = actions.unhide(con, dom, who), f"{dom} is back in Other sites."
        else: probs, msg = ["Nothing to do."], ""
        print(f"AUTOGUARD_ACTION op={op} domain={dom} profiles={','.join(pids)} by={who} problems={len(probs)}", file=sys.stderr, flush=True)
        self.back("/", ("!" + "; ".join(probs)) if probs else msg)

    def post_settings(self):
        con, sec, do = self.con, self.f("section"), self.f("do") or "save"
        result, msg = {}, "Saved."
        if sec == "nextdns":
            key = self.f("nextdns_api_key").strip()
            if key and S.source(con, "nextdns_api_key") != "environment":
                try: nextdns.client(key).profiles()
                except nextdns.NextDNSError as e: return self.send(400, V.settings_page(self.ctx(msg="!" + str(e))))
                S.put(con, "nextdns_api_key", key); con.commit()
            if do == "test":
                try: n = len(nextdns.client(S.get(con, "nextdns_api_key")).profiles()); result["nextdns"] = {"ok": True, "msg": f"Connected — {n} profiles on the account."}
                except nextdns.NextDNSError as e: result["nextdns"] = {"ok": False, "msg": str(e)}
                return self.send(200, V.settings_page(self.ctx(result=result)))
        elif sec == "devices":
            if do == "refresh":
                try: scan.sync_profiles(con, nextdns.client(S.get(con, "nextdns_api_key")))
                except nextdns.NextDNSError as e: return self.redirect("/settings?" + urllib.parse.urlencode({"msg": "!" + str(e)}) + "#devices")
                return self.send(200, V.settings_page(self.ctx(result={"counts": self.device_counts()}, msg="Device list reloaded from NextDNS.")))
            pids = [p for p in self.fl("profile") if con.execute("SELECT 1 FROM profiles WHERE id=?", (p,)).fetchone()]
            if not pids: return self.redirect("/settings?msg=" + urllib.parse.quote("!Tick at least one device.") + "#devices")
            actions.set_devices(con, pids, self.user["username"])
        elif sec == "ai":
            p = self.save_ai()
            if p: return self.send(400, V.settings_page(self.ctx(msg="!" + "; ".join(p))))
            if do == "test":
                result["ai"] = llm.test(S.snapshot(con), [dict(r) for r in con.execute("SELECT * FROM topics WHERE active=1")])
                return self.send(200, V.settings_page(self.ctx(result=result)))
        elif sec == "schedule":
            p = self.save_keys(["timezone", "scan_interval_hours", "bedtime_start", "bedtime_end", "allowed_guidance"], bools=["dry_run"])
            if p: return self.send(400, V.settings_page(self.ctx(msg="!" + "; ".join(p))))
        elif sec == "rules":
            p = self.save_keys(["block_at", "review_at", "max_blocks_per_run", "llm_batch", "never_block_extra"])
            if not p and float(S.get(con, "review_at")) > float(S.get(con, "block_at")): p = ["review level must be at or below the block level"]
            if p: return self.send(400, V.settings_page(self.ctx(msg="!" + "; ".join(p))))
        elif sec == "api" and do == "regenerate" and S.source(con, "api_token") != "environment":
            S.put(con, "api_token", ""); S.ensure_api_token(con); con.commit()
            return self.send(200, V.settings_page(self.ctx(result={"token": S.get(con, "api_token")}, msg="New API token generated.")))
        db.act(con, self.user["username"], "settings", detail=sec); con.commit()
        self.redirect("/settings?" + urllib.parse.urlencode({"msg": msg}) + f"#{sec}")

    def post_topics(self):
        p = actions.save_topic(self.con, self.f("tid"), self.f("label"), self.f("description"), self.f("active"), self.user["username"])
        self.redirect("/topics?" + urllib.parse.urlencode({"msg": ("!" + p[0]) if p else "Topic saved."}))

    def post_users(self):
        con, op, me = self.con, self.f("op"), self.user
        if op == "add": _, p = auth.create_user(con, self.f("username"), self.f("password")); msg = p or f"User {self.f('username')} added."
        elif op == "delete":
            try: p = auth.delete_user(con, int(self.f("uid")), me["id"])
            except ValueError: p = "Unknown user."
            msg = p or "User deleted."
        elif op == "password":
            p = auth.set_password(con, me["id"], self.f("password"), self.f("confirm"))
            if not p:   # set_password signs out every session — issue a fresh one for this browser
                return self.redirect("/users?msg=" + urllib.parse.quote("Password changed."),
                                     [self.set_cookie(auth.new_session(con, me["id"]), auth.SESSION_DAYS * 86400)])
            msg = p
        else: p, msg = "Nothing to do.", "Nothing to do."
        self.redirect("/users?" + urllib.parse.urlencode({"msg": ("!" + msg) if p else msg}))

def main():
    con = db.connect(); db.reap_stale(con); scan.backfill_kind(con); con.close()
    print(f"AUTOGUARD_WEB_START version={config.VERSION} port={config.PORT} db={config.DB_PATH}", file=sys.stderr, flush=True)
    scheduler.start()
    ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler).serve_forever()
