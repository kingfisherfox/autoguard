# CAPABILITY: dashboard accounts — PBKDF2 password hashes, server-side sessions (hashed tokens + per-session CSRF
#             token), login throttling. Every user is an admin (parents share the household).
import hashlib, hmac, re, secrets, time
from datetime import datetime, timedelta, timezone
from . import db

ITER = 600_000            # OWASP 2023 guidance for PBKDF2-HMAC-SHA256
SESSION_DAYS = 30
USERNAME = re.compile(r"^[A-Za-z0-9._@-]{3,64}$")
_sha = lambda s: hashlib.sha256(s.encode()).hexdigest()

def hash_pw(pw, iters=None):
    salt = secrets.token_bytes(16); it = iters or ITER
    return f"pbkdf2_sha256${it}${salt.hex()}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, it).hex()}"

def check_pw(pw, stored):
    try: _, it, salt, h = stored.split("$")
    except ValueError: return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex(), h)

_DUMMY = None
def password_problem(pw, confirm=None):
    if len(pw) < 10: return "Password must be at least 10 characters."
    if confirm is not None and pw != confirm: return "The two passwords don't match."
    return None

def count(con): return con.execute("SELECT count(*) FROM users").fetchone()[0]
def users(con): return con.execute("SELECT id, username, created_at, last_login FROM users ORDER BY username").fetchall()

def create_user(con, username, pw, confirm=None):
    username = (username or "").strip()
    if not USERNAME.match(username): return None, "Username: 3–64 letters, numbers, . _ @ or -."
    if (p := password_problem(pw, confirm)): return None, p
    if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone(): return None, "That username is taken."
    uid = con.execute("INSERT INTO users (username, pw_hash, created_at) VALUES (?,?,?)",
                      (username, hash_pw(pw), db.now())).lastrowid
    db.act(con, username, "user_created", detail=username); con.commit(); return uid, None

def set_password(con, uid, pw, confirm=None):
    if (p := password_problem(pw, confirm)): return p
    con.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(pw), uid))
    con.execute("DELETE FROM sessions WHERE user_id=?", (uid,)); con.commit(); return None

def delete_user(con, uid, acting_uid):
    if uid == acting_uid: return "You can't delete yourself."
    if count(con) <= 1: return "Keep at least one user."
    con.execute("DELETE FROM sessions WHERE user_id=?", (uid,)); con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.commit(); return None

def verify(con, username, pw):
    global _DUMMY
    r = con.execute("SELECT id, pw_hash FROM users WHERE username=?", ((username or "").strip(),)).fetchone()
    if not r:   # same work as a real check → no username enumeration by timing
        _DUMMY = _DUMMY or hash_pw("x" * 12); check_pw(pw, _DUMMY); return None
    if not check_pw(pw, r["pw_hash"]): return None
    con.execute("UPDATE users SET last_login=? WHERE id=?", (db.now(), r["id"])); con.commit(); return r["id"]

def new_session(con, uid):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (_sha(token), uid, csrf, db.now(), exp)); con.commit()
    return token

def session_user(con, token):
    if not token: return None
    r = con.execute("SELECT u.id, u.username, s.csrf, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id "
                    "WHERE s.token_hash=?", (_sha(token),)).fetchone()
    if not r or r["expires_at"] < db.now(): return None
    return {"id": r["id"], "username": r["username"], "csrf": r["csrf"]}

def end_session(con, token):
    if token: con.execute("DELETE FROM sessions WHERE token_hash=?", (_sha(token),)); con.commit()

class Throttle:
    """≥ LIMIT failed logins for a key within WINDOW seconds ⇒ locked for the rest of the window."""
    LIMIT, WINDOW = 5, 900
    def __init__(self): self.fails = {}
    def locked(self, key):
        t = time.time(); self.fails[key] = [x for x in self.fails.get(key, []) if t - x < self.WINDOW]
        return len(self.fails[key]) >= self.LIMIT
    def fail(self, key): self.fails.setdefault(key, []).append(time.time())
    def ok(self, key): self.fails.pop(key, None)
