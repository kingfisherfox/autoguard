# CAPABILITY: parent decisions from the dashboard — block / unblock a domain on some or all devices, mark fine,
#             choose devices, edit topics, export.
# MEMORY: every decision is stored (blocks rows source=owner, domains.verdict owner_ok/owner_block) so scans never
#         undo it; owner_ok/owner_block domains are also shown to the AI as examples.
# OUTPUT: list of problems (empty = live NextDNS state verified to match). dry_run ⇒ DB only, NextDNS untouched.
from . import db, nextdns

def enabled_pids(con): return [r[0] for r in con.execute("SELECT id FROM profiles WHERE enabled=1 ORDER BY name")]

def set_devices(con, pids, actor):
    con.execute("UPDATE profiles SET enabled=0")
    con.executemany("UPDATE profiles SET enabled=1 WHERE id=?", [(p,) for p in pids])
    db.act(con, actor, "devices", detail=",".join(pids)); con.commit()

def _verify(nx, pid, domain, want, dry):
    if dry: return []
    have = nx.deny_entries(pid).get(domain) is True
    return [] if have == want else [f"{domain} on {pid}: expected {'blocked' if want else 'unblocked'}"]

def unblock(con, nx, domain, pids, actor, dry=False):
    probs = []
    for pid in pids:
        try:
            if not dry: nx.del_deny(pid, domain)
            probs += _verify(nx, pid, domain, False, dry)
        except nextdns.NextDNSError as e: probs.append(str(e)); continue
        db.set_block(con, domain, pid, "unblocked", "owner"); db.act(con, actor, "unblock", domain, pid)
    if not con.execute("SELECT count(*) FROM blocks WHERE domain=? AND state='blocked'", (domain,)).fetchone()[0]:
        con.execute("UPDATE domains SET verdict='owner_ok', decided_at=? WHERE domain=?", (db.now(), domain))   # fine for good
    con.commit(); return probs

def block(con, nx, domain, pids, actor, dry=False):
    db.ensure_domain(con, domain); probs = []
    for pid in enabled_pids(con):   # devices not chosen get an owner 'unblocked' row so scans don't spread it there
        if pid not in pids: con.execute("INSERT OR IGNORE INTO blocks VALUES (?,?,'unblocked','owner',?)", (domain, pid, db.now()))
    for pid in pids:
        try:
            if not dry: nx.add_deny(pid, domain, exists=domain in nx.deny_entries(pid))
            probs += _verify(nx, pid, domain, True, dry)
        except nextdns.NextDNSError as e: probs.append(str(e)); continue
        db.set_block(con, domain, pid, "blocked", "owner"); db.act(con, actor, "block", domain, pid)
    if con.execute("SELECT verdict FROM domains WHERE domain=?", (domain,)).fetchone()[0] != "block":
        con.execute("UPDATE domains SET verdict='owner_block', decided_at=? WHERE domain=?", (db.now(), domain))
    con.commit(); return probs

def mark_ok(con, domain, actor):
    con.execute("UPDATE domains SET verdict='owner_ok', decided_at=? WHERE domain=?", (db.now(), domain))
    db.act(con, actor, "mark_ok", domain); con.commit(); return []

def fine_add(con, domain, actor):
    """Parent says a site is fine before (or after) it shows up: never sent to the AI, never auto-blocked."""
    db.ensure_domain(con, domain)
    con.execute("UPDATE domains SET verdict='owner_ok', reason=NULL, decided_at=? WHERE domain=?", (db.now(), domain))
    db.act(con, actor, "fine_add", domain); con.commit(); return []

def unfine(con, domain, actor):
    """Off the fine list → judged again by the AI on the next check (if the children use it)."""
    con.execute("UPDATE domains SET verdict='pending', model=NULL, decided_at=? WHERE domain=? AND verdict='owner_ok' "
                "AND COALESCE(reason,'') != 'nextdns_allowlist'", (db.now(), domain))
    db.act(con, actor, "unfine", domain); con.commit(); return []

def bulk_ok(con, domains, actor):
    n = 0
    for d in domains:
        n += con.execute("UPDATE domains SET verdict='owner_ok', decided_at=? WHERE domain=? AND verdict='clean'", (db.now(), d)).rowcount
    db.act(con, actor, "bulk_ok", None, None, f"{n} sites"); con.commit(); return n

def hide(con, domain, actor):
    """Noise (load balancers, app back-ends…): hidden from every list and never sent to the AI again."""
    con.execute("UPDATE domains SET verdict='ignored', decided_at=? WHERE domain=? AND verdict IN ('clean','review','pending')", (db.now(), domain))
    db.act(con, actor, "hide", domain); con.commit(); return []

def unhide(con, domain, actor):
    """Back into Other sites: a hidden site, or a background service the parent wants to see."""
    con.execute("UPDATE domains SET verdict='clean', kind='website', decided_at=? WHERE domain=? AND verdict IN ('ignored','clean')", (db.now(), domain))
    db.act(con, actor, "unhide", domain); con.commit(); return []

def save_topic(con, tid, label, description, active, actor):
    tid = "".join(c for c in (tid or "").lower().strip().replace(" ", "_") if c.isalnum() or c == "_")[:40]
    if not tid or not (label or "").strip() or not (description or "").strip(): return ["A topic needs an id, a label and a description."]
    con.execute("INSERT INTO topics (id, label, description, active) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "label=excluded.label, description=excluded.description, active=excluded.active",
                (tid, label.strip(), description.strip(), 1 if active else 0))
    db.act(con, actor, "topic", None, None, f"{tid} active={bool(active)}"); con.commit(); return []

def export(con):
    """Per-device autoguard denylist (GET /api/denylist.json) — for scripts that manage NextDNS denylists themselves."""
    out = {pid: [] for pid in enabled_pids(con)}
    for r in con.execute("SELECT domain, profile FROM blocks WHERE state='blocked' ORDER BY domain"):
        out.setdefault(r["profile"], []).append(r["domain"])
    return out
