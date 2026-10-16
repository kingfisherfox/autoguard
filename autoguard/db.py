# CAPABILITY: autoguard SQLite — schema, additive migrations, seed topics, small write helpers.
# SHAPE: docs/schema.dbml (keep in sync).
# VERDICTS (domains.verdict): pending → skip | clean | review | block   (AI + guardrails)
#                             owner_ok | owner_block | ignored        (parent decisions — never reclassified)
#                             imported                                (already on a NextDNS denylist; shown, not owned)
# KIND (domains.kind): website | infrastructure (CDN, API, ads, telemetry, load balancer) — infrastructure is hidden
#                      from parents unless blocked or flagged.
# BLOCKS: one row per (domain, profile); state blocked|unblocked, source auto|owner|nextdns. Owner rows are memory: a
#         per-device unblock is never re-added by a scan. nextdns rows mirror the live NextDNS denylist (truth there).
import fcntl, os, sqlite3, time
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
  watermark TEXT, seen_at TEXT);
CREATE TABLE IF NOT EXISTS domains (domain TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
  hits INTEGER NOT NULL DEFAULT 0, resolved_hits INTEGER NOT NULL DEFAULT 0, bedtime_hits INTEGER NOT NULL DEFAULT 0,
  profiles TEXT NOT NULL DEFAULT '[]', samples TEXT NOT NULL DEFAULT '[]',
  title TEXT, description TEXT, fetch_error TEXT, fetched_at TEXT,
  verdict TEXT NOT NULL DEFAULT 'pending', topic TEXT, confidence REAL, reason TEXT, model TEXT, decided_at TEXT);
CREATE INDEX IF NOT EXISTS domains_verdict ON domains(verdict);
CREATE TABLE IF NOT EXISTS blocks (domain TEXT NOT NULL REFERENCES domains(domain), profile TEXT NOT NULL,
  state TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (domain, profile));
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT, started TEXT, finished TEXT,
  status TEXT, phase TEXT, logs_read INTEGER DEFAULT 0, new_domains INTEGER DEFAULT 0, classified INTEGER DEFAULT 0,
  blocked INTEGER DEFAULT 0, held INTEGER DEFAULT 0, writes INTEGER DEFAULT 0, errors INTEGER DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS actions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, domain TEXT, profile TEXT, detail TEXT);
"""
# (table, column, ALTER, follow-up) — additive only; databases from earlier versions upgrade in place.
MIGRATIONS = [
    ("profiles", "enabled", "ALTER TABLE profiles ADD COLUMN enabled INTEGER NOT NULL DEFAULT 0",
     "UPDATE profiles SET enabled=1"),   # pre-1.0 installs managed every profile
    ("runs", "phase", "ALTER TABLE runs ADD COLUMN phase TEXT", None),
    ("domains", "kind", "ALTER TABLE domains ADD COLUMN kind TEXT", None),
    ("domains", "last_blocked", "ALTER TABLE domains ADD COLUMN last_blocked INTEGER NOT NULL DEFAULT 0", None),
    ("domains", "kind_by", "ALTER TABLE domains ADD COLUMN kind_by TEXT",   # ai | guess — guesses on AI-checkable rows get redone
     "UPDATE domains SET kind=NULL WHERE verdict IN ('clean','imported')"),
    ("domains", "category", "ALTER TABLE domains ADD COLUMN category TEXT", None),   # CATEGORIES id — display grouping only
    ("domains", "about", "ALTER TABLE domains ADD COLUMN about TEXT", None),         # AI one-liner: what it is, who runs it
]

# Display grouping for every list page. The AI picks one for each site it already sees; no rule reads it (never control
# flow). Sites the AI must never see (fine, hidden, big platforms) stay NULL → shown as "Not sorted". (id, label, AI hint)
CATEGORIES = [
    ("games", "Games", "games, game stores, mods, game wikis"),
    ("video", "Video & streaming", "video, live streaming, TV, films"),
    ("social", "Social & chat", "social networks, forums, messaging, chat"),
    ("ai", "AI tools", "AI chat, AI image or writing tools"),
    ("learning", "School & learning", "school, homework, courses, reference, encyclopedias"),
    ("news", "News & reading", "news, magazines, blogs, books, comics"),
    ("music", "Music & audio", "music, podcasts, audio"),
    ("shopping", "Shopping", "shops, marketplaces, deals"),
    ("hobbies", "Hobbies & lifestyle", "sport, food, travel, fashion, crafts, pets"),
    ("tools", "Everyday tools", "search, email, maps, office, banking, utilities"),
    ("adult", "Adult & risky", "porn, gambling, dating, piracy, hate"),
    ("ads", "Ads & tracking", "advertising, analytics, tracking, telemetry"),
    ("services", "App & device services", "CDNs, cloud, APIs, app back-ends, OS or device updates"),
    ("other", "Other", "anything else"),
]

# Seed topics — editable on "What to block". Deliberately narrow: the NextDNS categories already cover porn,
# gambling, dating, piracy; these are the gaps NextDNS has no category for. (id, label, description, active)
TOPICS = [
    ("uncensored_ai", "Uncensored / companion AI",
     "AI companion, girlfriend/boyfriend, character or roleplay chat (Character.AI, JanitorAI, Talkie, Chai, Zeta, "
     "Harpy, FlowGPT, SpicyChat, CrushOn), NSFW or 'uncensored' AI chat or image generators, nudify/undress/deepfake tools, and AI front-ends or "
     "model aggregators that let users bypass safety filters (OpenRouter, Poe, Venice). NOT mainstream assistants "
     "(ChatGPT, Claude, Gemini, Copilot, Perplexity, Meta AI) and NOT AI tools for school or design (Canva, "
     "Grammarly, homework helpers, translators)."),
    ("stranger_chat", "Stranger chat",
     "Random or anonymous chat with strangers: Omegle clones, video roulette, anonymous text chat, 'meet new "
     "people' chat sites and apps (Chatroulette, OmeTV, Monkey, Azar, Emerald Chat, CooMeet, LemonChat, Yap.Chat). "
     "NOT normal messaging with known contacts (WhatsApp, Messenger, LINE, Discord, Telegram)."),
    ("redpill", "Red pill / manosphere",
     "Red-pill, manosphere, incel, MGTOW, pickup-artist, 'alpha male' and looksmaxxing content; Andrew Tate and "
     "similar influencers' sites, courses and forums; misogynist communities and the streaming hosts they use "
     "(Kick, Rumble). NOT fitness, self-improvement without misogyny, war/military/history, or mainstream news."),
    ("adult", "Porn & adult content (backup)",
     "Pornography, explicit sexual images or video, nude/NSFW galleries, cam and escort sites, adult manga/hentai. A backup "
     "for NextDNS's own Porn category, which misses new sites. NOT sex education, health information, or swimwear shops.", 0),
]

now = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def connect(path=None):
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA foreign_keys=ON"); con.executescript(SCHEMA)
    for table, col, alter, follow in MIGRATIONS:
        if col not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
            con.execute(alter); follow and con.execute(follow)
    if not con.execute("SELECT 1 FROM topics LIMIT 1").fetchone():
        con.executemany("INSERT INTO topics (id, label, description, active) VALUES (?,?,?,?)", [(*t, 1)[:4] for t in TOPICS])
    con.commit()
    try: os.chmod(path, 0o600)   # holds API keys + password hashes
    except OSError: pass
    return con

def lock_path(): return (config.DB_PATH) + ".lock"

def reap_stale(con):
    """Mark 'running' scans as interrupted if no scan holds the lock (process died mid-run)."""
    with open(lock_path(), "w") as f:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        con.execute("UPDATE runs SET status='interrupted', finished=? WHERE status='running'", (now(),)); con.commit()
        fcntl.flock(f, fcntl.LOCK_UN)

def act(con, actor, action, domain=None, profile=None, detail=""):
    con.execute("INSERT INTO actions (ts, actor, action, domain, profile, detail) VALUES (?,?,?,?,?,?)",
                (now(), actor, action, domain, profile, detail))

def set_block(con, domain, profile, state, source):
    con.execute("INSERT INTO blocks (domain, profile, state, source, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(domain, profile) DO UPDATE SET state=excluded.state, source=excluded.source, "
                "updated_at=excluded.updated_at", (domain, profile, state, source, now()))

def ensure_domain(con, domain, seen=False):
    """Row for a domain known without a visit (import, manual block/fine): last_seen stays NULL until visited."""
    t = now(); con.execute("INSERT OR IGNORE INTO domains (domain, first_seen, last_seen) VALUES (?,?,?)", (domain, t, t if seen else None))
