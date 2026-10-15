# CAPABILITY: one autoguard scan — import live NextDNS deny/allowlists → pull logs (enabled devices) → new domains →
#             enrich → AI (verdict + website/infrastructure) → guardrails → block on every enabled device →
#             reconcile + verify live denylists → record run (+ live progress).
# OWNERSHIP: rows Autoguard created (source auto|owner) are enforced (re-added if missing). Rows imported from
#            NextDNS (source nextdns) mirror NextDNS: removed there ⇒ shown as unblocked here, never re-added.
# CALLED BY: scheduler (every N hours), "Run scan now", setup finish (first scan), CLI `python -m autoguard scan`.
#            A file lock makes overlapping scans a no-op.
# LOGS: AUTOGUARD_* k=v lines on stderr (`docker logs autoguard`).
import fcntl, json, sys, traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from . import db, enrich, guard, llm, nextdns, settings

log = lambda ev, **kv: print(ev, *(f"{k}={v}" for k, v in kv.items()), file=sys.stderr, flush=True)
COUNTS = ("logs_read", "new_domains", "classified", "blocked", "held", "writes", "errors")

def night_checker(cfg):
    """ts → True if inside the parent's bedtime window (settings bedtime_start/end, local timezone)."""
    s, e = cfg["bedtime_start"], cfg["bedtime_end"]
    if not (s and e): return lambda ts: False
    try: tz = ZoneInfo(cfg["timezone"] or "UTC")
    except Exception: tz = ZoneInfo("UTC")  # noqa: BLE001
    hm = lambda x: tuple(int(p) for p in x.split(":")[:2]); s, e = hm(s), hm(e)
    def f(ts):
        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz); x = (t.hour, t.minute)
        return (x >= s or x < e) if s > e else (s <= x < e)
    return f

def progress(con, rid, phase, st):
    con.execute("UPDATE runs SET phase=?, logs_read=?, new_domains=?, classified=? WHERE id=?",
                (phase, st["logs_read"], st["new_domains"], st["classified"], rid)); con.commit()

# ── 1. pull ─────────────────────────────────────────────────────────────────
def pull(con, nx, profs, st, cfg, rid):
    agg, night = {}, night_checker(cfg)
    for p in profs:
        wm = (con.execute("SELECT watermark FROM profiles WHERE id=?", (p["id"],)).fetchone() or {"watermark": None})["watermark"]
        newest, n = wm, 0
        progress(con, rid, f"Reading DNS logs: {p['name']}", st)
        for l in nx.logs(p["id"], wm or f"-{cfg['first_lookback_days']}d"):
            ts = l["timestamp"]
            if wm and ts <= wm: continue
            newest, n = max(newest or ts, ts), n + 1
            a = agg.setdefault(guard.domain_key(l["domain"], l.get("root")),
                               {"hits": 0, "resolved": 0, "bed": 0, "profiles": set(), "samples": set(), "first": ts, "last": ts, "lb": 0})
            a["hits"] += 1; a["resolved"] += l.get("status") != "blocked"; a["bed"] += night(ts)
            a["profiles"].add(p["id"]); len(a["samples"]) < 5 and a["samples"].add(l["domain"])
            if ts >= a["last"]: a["lb"] = int(l.get("status") == "blocked")
            a["first"], a["last"] = min(a["first"], ts), max(a["last"], ts)
            if n % 5000 == 0: progress(con, rid, f"Reading DNS logs: {p['name']}", dict(st, logs_read=st["logs_read"] + n))
        con.execute("UPDATE profiles SET watermark=? WHERE id=?", (newest, p["id"])); st["logs_read"] += n
        log("AUTOGUARD_PULL", profile=p["id"], logs=n, since=wm or f"-{cfg['first_lookback_days']}d")
    for d, a in agg.items():
        cur = con.execute("SELECT profiles, samples FROM domains WHERE domain=?", (d,)).fetchone()
        if cur is None: st["new_domains"] += 1
        profs_ = sorted(set(json.loads(cur["profiles"]) if cur else []) | a["profiles"])
        samples = sorted(set(json.loads(cur["samples"]) if cur else []) | a["samples"])[:8]
        con.execute("""INSERT INTO domains (domain, first_seen, last_seen, hits, resolved_hits, bedtime_hits, profiles, samples, last_blocked)
            VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(domain) DO UPDATE SET
            last_blocked=CASE WHEN excluded.last_seen >= COALESCE(last_seen, '') THEN excluded.last_blocked ELSE last_blocked END,
            last_seen=max(COALESCE(last_seen, ''), excluded.last_seen),
            first_seen=min(COALESCE(first_seen, excluded.first_seen), excluded.first_seen), hits=hits+excluded.hits,
            resolved_hits=resolved_hits+excluded.resolved_hits, bedtime_hits=bedtime_hits+excluded.bedtime_hits,
            profiles=excluded.profiles, samples=excluded.samples""",
                    (d, a["first"], a["last"], a["hits"], a["resolved"], a["bed"], json.dumps(profs_), json.dumps(samples), a["lb"]))
    con.commit()

# ── 0. import what the parent already has in NextDNS ────────────────────────
def import_lists(con, profs, live):
    """Denylist entries → blocks(source nextdns) for that device only; allowlist entries → fine (owner_ok)."""
    added = 0
    for p in profs:
        pid = p["id"]; deny = {d for d, active in live[pid]["deny"].items() if active}
        rows = {r["domain"]: r for r in con.execute("SELECT domain, state, source FROM blocks WHERE profile=?", (pid,))}
        for d in deny:
            r = rows.get(d)
            if r is not None and r["state"] == "blocked": continue
            db.ensure_domain(con, d)
            con.execute("UPDATE domains SET verdict='imported', decided_at=? WHERE domain=? AND verdict IN ('pending','skip','clean','ignored')",
                        (db.now(), d))
            db.set_block(con, d, pid, "blocked", "nextdns"); added += 1
        for d, r in rows.items():   # removed in NextDNS directly → reflect it, don't fight it
            if r["source"] == "nextdns" and r["state"] == "blocked" and d not in deny: db.set_block(con, d, pid, "unblocked", "nextdns")
        for d in live[pid]["allow"]:
            db.ensure_domain(con, d)
            con.execute("UPDATE domains SET verdict='owner_ok', reason='nextdns_allowlist', decided_at=? WHERE domain=? "
                        "AND verdict IN ('pending','skip','clean','review','ignored')", (db.now(), d))
    con.commit(); return added

def backfill_kind(con):
    """Rows the AI will never see again (skipped, fine, hidden, flagged) get the title guess. 'clean' and 'imported'
    rows without a kind are left for the AI (classify_all re-asks them) — hidden from parents until then."""
    for r in con.execute("SELECT domain, title FROM domains WHERE kind IS NULL AND verdict NOT IN ('pending','clean','imported')").fetchall():
        con.execute("UPDATE domains SET kind=?, kind_by='guess' WHERE domain=?", (guard.kind_of(None, r["title"]), r["domain"]))
    for r in con.execute("SELECT domain, title FROM domains WHERE kind='website'").fetchall():   # rule change: no homepage ⇒ background
        if not guard.has_site(r["title"]): con.execute("UPDATE domains SET kind='infrastructure' WHERE domain=?", (r["domain"],))
    con.commit()

# ── 2. triage (code-owned) ──────────────────────────────────────────────────
def triage(con, live, cfg):
    allow = set().union(*(v["allow"] for v in live.values())) if live else set()
    manual = set().union(*({d for d, a in v["deny"].items() if a} for v in live.values())) if live else set()
    todo = []
    for r in con.execute("SELECT domain FROM domains WHERE verdict='pending' AND resolved_hits>0 ORDER BY hits DESC LIMIT 5000").fetchall():
        d = r["domain"]
        why = ("never_block" if guard.never_block(d, allow, cfg["never_block_extra"])
               else "already_blocked_in_nextdns" if guard.covered(d, manual) else None)
        if why: con.execute("UPDATE domains SET verdict='skip', reason=?, decided_at=? WHERE domain=?", (why, db.now(), d))
        else: todo.append(d)
    con.commit(); return todo

# ── 3. enrich + classify ────────────────────────────────────────────────────
def classify_all(con, todo, st, cfg, rid):
    # described for the parent (topic, reason, kind) — never re-decided: imported entries, and sites judged before
    # Autoguard knew websites from background services
    describe = [r[0] for r in con.execute("SELECT domain FROM domains WHERE (verdict='imported' AND model IS NULL) OR "
                                          "(verdict IN ('clean','imported') AND kind IS NULL) ORDER BY hits DESC LIMIT 400")]
    describe = [d for d in describe if d not in set(todo)]
    judge, todo = set(todo), list(todo) + describe
    need = [d for d in todo if not con.execute("SELECT fetched_at FROM domains WHERE domain=?", (d,)).fetchone()[0]]
    if need: progress(con, rid, f"Looking at {len(need)} websites", st)
    for d, e in enrich.fetch_many(need).items():
        con.execute("UPDATE domains SET title=?, description=?, fetch_error=?, fetched_at=? WHERE domain=?",
                    (e["title"], e["description"], e["fetch_error"], db.now(), d))
    con.commit(); log("AUTOGUARD_ENRICHED", n=len(need))
    topics = [dict(r) for r in con.execute("SELECT * FROM topics WHERE active=1")]
    if not topics or not todo: return
    mem = lambda v: [r[0] for r in con.execute("SELECT domain FROM domains WHERE verdict=? ORDER BY decided_at DESC LIMIT 40", (v,))]
    ok, bl, B = mem("owner_ok"), mem("owner_block"), cfg["llm_batch"]
    for i in range(0, len(todo), B):
        chunk = todo[i:i + B]
        progress(con, rid, f"Asking the AI: part {i // B + 1} of {(len(todo) + B - 1) // B}", st)
        batch = [dict(r) | {"samples": json.loads(r["samples"])} for r in
                 con.execute(f"SELECT * FROM domains WHERE domain IN ({','.join('?' * len(chunk))})", chunk)]
        res = llm.classify(batch, topics, cfg, ok, bl)    # LLMError → run marked llm_error; rest stays pending
        titles = {r["domain"]: r["title"] for r in batch}
        for d, (topic, conf, reason, *rest) in res.items():
            ai_kind = rest[0] if rest else None
            kind, by, t = guard.kind_of(ai_kind, titles.get(d)), "ai" if ai_kind else "guess", None if topic == "none" else topic
            if d not in judge:
                con.execute("UPDATE domains SET topic=?, confidence=?, reason=?, model=? WHERE domain=? AND verdict='imported'",
                            (t, conf, reason, cfg["llm_model"], d))
                con.execute("UPDATE domains SET kind=?, kind_by=? WHERE domain=? AND verdict IN ('clean','imported')", (kind, by, d)); continue
            v = guard.decide(topic, conf, cfg)
            con.execute("UPDATE domains SET verdict=?, topic=?, confidence=?, reason=?, kind=?, kind_by=?, model=?, decided_at=? WHERE domain=? AND verdict='pending'",
                        (v, t, conf, reason, kind, by, cfg["llm_model"], db.now(), d))
            if v != "clean": log("AUTOGUARD_VERDICT", domain=d, verdict=v, topic=topic, confidence=f"{conf:.2f}")
        st["classified"] += sum(1 for d in res if d in judge); con.commit()

# ── 4. apply to every enabled device + reconcile + verify ───────────────────
def apply(con, nx, profs, live, st, cfg):
    pids = [p["id"] for p in profs]
    fresh = [r[0] for r in con.execute("""SELECT domain FROM domains d WHERE verdict='block'
        AND NOT EXISTS (SELECT 1 FROM blocks b WHERE b.domain=d.domain) ORDER BY confidence DESC, hits DESC""")]
    go, held = guard.split_cap(fresh, cfg["max_blocks_per_run"]); st["blocked"], st["held"] = len(go), len(held)
    for d in go:
        r = con.execute("SELECT topic, confidence FROM domains WHERE domain=?", (d,)).fetchone()
        [db.set_block(con, d, pid, "blocked", "auto") for pid in pids]
        db.act(con, "autoguard", "block", d, None, f"topic={r['topic']} confidence={r['confidence']:.2f}")
    if held: log("AUTOGUARD_CAP_HIT", held=len(held), cap=cfg["max_blocks_per_run"])
    # master list → every enabled device, incl. newly enabled ones (owner per-device rows kept: INSERT OR IGNORE)
    for (d,) in con.execute("""SELECT DISTINCT b.domain FROM blocks b JOIN domains d ON d.domain=b.domain
                               WHERE d.verdict IN ('block','owner_block')""").fetchall():
        for pid in pids: con.execute("INSERT OR IGNORE INTO blocks VALUES (?,?,'blocked','auto',?)", (d, pid, db.now()))
    con.commit()
    touched = set()
    for r in con.execute("SELECT domain, profile FROM blocks WHERE state='blocked' AND source != 'nextdns'").fetchall():
        ent = live.get(r["profile"], {}).get("deny")
        if ent is None or ent.get(r["domain"]) is True: continue
        if cfg["dry_run"]: continue
        try: nx.add_deny(r["profile"], r["domain"], exists=r["domain"] in ent); touched.add(r["profile"]); st["writes"] += 1
        except nextdns.NextDNSError as e: st["errors"] += 1; log("AUTOGUARD_WRITE_FAILED", domain=r["domain"], profile=r["profile"], err=e)
    for pid in touched:
        ent = live[pid]["deny"] = nx.deny_entries(pid)
        miss = [r[0] for r in con.execute("SELECT domain FROM blocks WHERE state='blocked' AND source != 'nextdns' AND profile=?", (pid,))
                if ent.get(r[0]) is not True]
        if miss: st["errors"] += len(miss); log("AUTOGUARD_VERIFY_FAILED", profile=pid, missing=",".join(miss[:20]))
        else: log("AUTOGUARD_VERIFY_OK", profile=pid)

def sync_profiles(con, nx):
    """Upsert NextDNS profiles; new ones start DISABLED (the parent opts each child's device in)."""
    api = nx.profiles()
    for p in api:
        con.execute("INSERT INTO profiles (id, name, enabled, seen_at) VALUES (?,?,0,?) ON CONFLICT(id) DO UPDATE SET "
                    "name=excluded.name, seen_at=excluded.seen_at", (p["id"], p["name"], db.now()))
    con.commit(); return api

# ── run ─────────────────────────────────────────────────────────────────────
def run(trigger="schedule"):
    lock = open(db.lock_path(), "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: lock.close(); log("AUTOGUARD_SKIPPED", reason="scan_in_progress", trigger=trigger); return None
    con = db.connect(); cfg = settings.snapshot(con)
    if not cfg["setup_done"] or not cfg["nextdns_api_key"]:
        con.close(); fcntl.flock(lock, fcntl.LOCK_UN); lock.close(); log("AUTOGUARD_SKIPPED", reason="not_configured"); return None
    st = dict.fromkeys(COUNTS, 0)
    rid = con.execute("INSERT INTO runs (trigger, started, status, phase) VALUES (?,?,'running','Starting')", (trigger, db.now())).lastrowid
    con.commit(); status, note = "ok", ""
    log("AUTOGUARD_RUN_START", run=rid, trigger=trigger, model=cfg["llm_model"], dry_run=cfg["dry_run"])
    try:
        nx = nextdns.client(cfg["nextdns_api_key"])
        present = {p["id"] for p in sync_profiles(con, nx)}
        profs = [dict(r) for r in con.execute("SELECT id, name FROM profiles WHERE enabled=1 ORDER BY name") if r["id"] in present]
        if not profs: raise RuntimeError("No devices are ticked — Settings → Devices")
        live = {p["id"]: {"deny": nx.deny_entries(p["id"]), "allow": nx.allowlist(p["id"])} for p in profs}
        progress(con, rid, "Reading your NextDNS block and allow lists", st)
        imported = import_lists(con, profs, live)
        if imported: note = f"Added {imported} entries already on your NextDNS block lists."; log("AUTOGUARD_IMPORTED", entries=imported)
        backfill_kind(con)
        pull(con, nx, profs, st, cfg, rid)
        todo = triage(con, live, cfg)
        if not cfg["llm_api_key"] and not cfg["llm_base_url"].startswith(("http://host.docker.internal", "http://localhost", "http://127.")):
            status, note = "llm_error", "No AI key configured — Settings → AI. New sites wait until one is added."
        else:
            try: classify_all(con, todo, st, cfg, rid)
            except llm.LLMError as e:
                log("AUTOGUARD_LLM_FAILED", err=e)
                if e.code == 429: status, note = "ai_busy", "The AI service was busy. Sites still waiting will be checked next time."
                else: status, note = "llm_error", f"The AI ({cfg['llm_model']}) said: {e}"[:400]
        progress(con, rid, "Updating NextDNS", st)
        apply(con, nx, profs, live, st, cfg)
        if status == "ok" and st["errors"]: status = "partial"
    except Exception as e:  # noqa: BLE001 — a run must always be recorded
        status, note = "failed", f"{type(e).__name__}: {e}"[:400]; traceback.print_exc()
    finally:
        con.execute(f"UPDATE runs SET finished=?, status=?, note=?, phase=NULL, {', '.join(c + '=?' for c in COUNTS)} WHERE id=?",
                    (db.now(), status, note, *[st[k] for k in COUNTS], rid))
        con.commit(); con.close(); fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
        log("AUTOGUARD_RUN_END", run=rid, status=status, **st)
    return rid
