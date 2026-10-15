# CAPABILITY: autoguard CLI.
#   python -m autoguard                     web dashboard + built-in scheduler (container default)
#   python -m autoguard scan                one scan now (for external cron, or debugging)
#   python -m autoguard create-user NAME    add a dashboard user (password prompted, or piped on stdin)
#   python -m autoguard reset-password NAME set a new password (signs that user out everywhere)
#   python -m autoguard backup  > file      consistent copy of the database to stdout (contains your API keys!)
#   python -m autoguard restore < file      replace the database with a backup (restart the container afterwards)
import getpass, os, sqlite3, sys, tempfile
from . import auth, db

def _password():
    if not sys.stdin.isatty(): return sys.stdin.readline().rstrip("\n")
    a, b = getpass.getpass("New password: "), getpass.getpass("Repeat it: ")
    if a != b: sys.exit("Passwords don't match.")
    return a

def main(argv):
    os.umask(0o077)   # database, WAL and lock files hold API keys + password hashes
    cmd = argv[0] if argv else "web"
    if cmd == "web":
        from . import web; web.main()
    elif cmd == "scan":
        from . import scan; sys.exit(0 if scan.run(argv[1] if len(argv) > 1 else "manual") else 1)
    elif cmd == "backup":
        from . import config
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "b.db"); dst = sqlite3.connect(out); sqlite3.connect(config.DB_PATH).backup(dst); dst.close()
            sys.stdout.buffer.write(open(out, "rb").read())
    elif cmd == "restore":
        from . import config
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "r.db"); open(src, "wb").write(sys.stdin.buffer.read())
            try: ok = sqlite3.connect(src).execute("SELECT count(*) FROM settings").fetchone() is not None
            except sqlite3.DatabaseError: ok = False
            if not ok: sys.exit("That file isn't an Autoguard backup.")
            sqlite3.connect(src).backup(sqlite3.connect(config.DB_PATH))
        print("OK: restored — now run: docker compose restart", file=sys.stderr)
    elif cmd in ("create-user", "reset-password") and len(argv) == 2:
        con = db.connect(); name = argv[1]
        if cmd == "create-user":
            _, p = auth.create_user(con, name, _password())
        else:
            r = con.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()
            p = auth.set_password(con, r["id"], _password()) if r else f"No user named {name}."
        sys.exit(p) if p else print(f"OK: {cmd} {name}")
    else:
        sys.exit("usage: python -m autoguard [web | scan | create-user NAME | reset-password NAME | backup | restore]")

if __name__ == "__main__":
    main(sys.argv[1:])
