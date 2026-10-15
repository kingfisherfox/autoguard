# CAPABILITY: minimal NextDNS API client (stdlib). REF: https://nextdns.github.io/api/
# AUTH: X-Api-Key (parent's key from https://my.nextdns.io/account → API). A custom User-Agent is required:
#       api.nextdns.io sits behind Cloudflare, which 403s Python-urllib's default UA.
# WRITES: only per-domain denylist children — POST /denylist, PATCH|DELETE /denylist/<domain>. Never PUT the whole
#         list, so anything the parent added in NextDNS by hand is left alone.
import json, sys, urllib.error, urllib.parse, urllib.request
from . import config

API = "https://api.nextdns.io"

class NextDNSError(Exception):
    def __init__(self, msg, code=None): super().__init__(msg); self.code = code

class Client:
    def __init__(self, key): self.key = key

    def http(self, method, path, params=None, body=None):
        url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Api-Key": self.key, "User-Agent": config.UA, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read(); return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            hint = " — check the NextDNS API key" if e.code in (401, 403) else ""
            raise NextDNSError(f"NextDNS {method} {path}: HTTP {e.code}{hint}", e.code) from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise NextDNSError(f"NextDNS unreachable: {getattr(e, 'reason', e)}") from None

    def profiles(self):
        return [{"id": p["id"], "name": p.get("name") or p["id"]} for p in self.http("GET", "profiles")["data"]]

    def queries_7d(self, pid):
        return sum(x.get("queries", 0) for x in self.http("GET", f"profiles/{pid}/analytics/status", {"from": "-7d"})["data"])

    def deny_entries(self, pid):
        """{domain: active} — the live denylist of one profile."""
        return {x["id"]: x.get("active", True) for x in self.http("GET", f"profiles/{pid}/denylist")["data"]}

    def allowlist(self, pid):
        return {x["id"] for x in self.http("GET", f"profiles/{pid}/allowlist")["data"] if x.get("active", True)}

    def add_deny(self, pid, domain, exists=False):
        if exists: self.http("PATCH", f"profiles/{pid}/denylist/{domain}", body={"active": True})
        else: self.http("POST", f"profiles/{pid}/denylist", body={"id": domain, "active": True})

    def del_deny(self, pid, domain):
        try: self.http("DELETE", f"profiles/{pid}/denylist/{domain}")
        except NextDNSError as e:
            if e.code != 404: raise

    def logs(self, pid, since, max_pages=300):
        """Yield log entries newer than `since` (ISO timestamp or relative like -7d), newest first."""
        cursor = None
        for _ in range(max_pages):
            r = self.http("GET", f"profiles/{pid}/logs", {"from": since, "limit": 1000, **({"cursor": cursor} if cursor else {})})
            yield from r.get("data", [])
            cursor = ((r.get("meta") or {}).get("pagination") or {}).get("cursor")
            if not cursor: return
        print(f"AUTOGUARD_LOGS_TRUNCATED profile={pid} pages={max_pages}", file=sys.stderr)

def client(key):   # factory — tests swap this for a fake
    return Client(key)
