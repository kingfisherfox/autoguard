# CAPABILITY: in-app scheduler — runs a scan every `scan_interval_hours` (0 = off) once setup is done.
#             No host cron needed; `python -m autoguard scan` exists for people who prefer external cron.
import sys, threading
from datetime import datetime, timedelta, timezone
from . import db, scan, settings

def parse(ts): return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def next_due(con):
    """UTC datetime of the next scheduled scan, or None if scheduling is off / setup not finished."""
    cfg = settings.snapshot(con)
    if not cfg["setup_done"] or cfg["scan_interval_hours"] <= 0: return None
    last = con.execute("SELECT started FROM runs WHERE status != 'running' ORDER BY id DESC LIMIT 1").fetchone()
    if not last: return datetime.now(timezone.utc)
    return parse(last["started"]) + timedelta(hours=cfg["scan_interval_hours"])

def loop(stop):
    while not stop.wait(60):
        try:
            con = db.connect()
            due = next_due(con); busy = con.execute("SELECT 1 FROM runs WHERE status='running'").fetchone()
            con.close()
            if due and not busy and due <= datetime.now(timezone.utc): scan.run("schedule")
        except Exception as e:  # noqa: BLE001 — the scheduler must survive anything
            print(f"AUTOGUARD_SCHEDULER_ERROR err={e!r}", file=sys.stderr, flush=True)

def start():
    stop = threading.Event(); threading.Thread(target=loop, args=(stop,), daemon=True, name="scheduler").start(); return stop
