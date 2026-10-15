# CAPABILITY: evidence for the classifier — fetch a domain's homepage <title> + meta description.
# WHY: domain names mislead (e.g. chaizer.com "looks like AI chat", is a power-bank shop). Read-only GETs.
# SAFETY: domains come from kids' DNS logs, so they are untrusted. Only PUBLIC addresses are fetched (initial host
#         and every redirect) — autoguard runs on the home network and must never probe the router, NAS, etc.
#         TLS verification is off on purpose: we only read titles, and dodgy sites often have broken certs.
import html, ipaddress, re, socket, ssl, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
META = re.compile(r"<meta\s[^>]*(?:name|property)=[\"'](description|og:description|og:title|og:site_name)[\"'][^>]*>", re.I)
CONTENT = re.compile(r"content=[\"']([^\"']*)", re.I)
clean = lambda s, n: re.sub(r"\s+", " ", html.unescape(s or "")).strip()[:n]

def is_public(host):
    try: infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError): return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)

class PublicOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlparse(newurl).hostname
        if not host or not is_public(host): raise urllib.error.URLError(f"redirect to non-public host {host}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

OPENER = urllib.request.build_opener(PublicOnlyRedirect, urllib.request.HTTPSHandler(context=CTX))

def parse(body):
    meta = {}
    for m in META.finditer(body):
        c = CONTENT.search(m.group(0)); meta.setdefault(m.group(1).lower(), c.group(1) if c else "")
    t = TITLE.search(body)
    title = clean(meta.get("og:title") or meta.get("og:site_name") or (t.group(1) if t else ""), 160)
    return title or None, clean(meta.get("description") or meta.get("og:description"), 300) or None

def fetch(domain, timeout=6):
    err = "unreachable"
    for host in (domain, f"www.{domain}"):
        if not is_public(host): err = "no public address"; continue
        for scheme in ("https", "http"):
            try:
                req = urllib.request.Request(f"{scheme}://{host}/", headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en"})
                with OPENER.open(req, timeout=timeout) as r:
                    body = r.read(300_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
                title, desc = parse(body)
                return {"title": title, "description": desc, "fetch_error": None}
            except Exception as e:  # noqa: BLE001 — evidence is best-effort; the error itself is evidence
                err = f"{type(e).__name__}: {str(e)[:120]}"
    return {"title": None, "description": None, "fetch_error": err}

def fetch_many(domains, workers=16):
    with ThreadPoolExecutor(workers) as ex: return dict(zip(domains, ex.map(fetch, domains)))
