# CAPABILITY: regenerate docs/images/*.png for the user guide from the DEMO (tools/demo.py) — invented data only.
# USAGE:  python3 tools/screenshots.py            needs Google Chrome/Chromium (CHROME=/path/to/chrome) + Pillow
# FLOW:   start demo server (fresh temp DB) → walk the setup wizard + every page with a cookie-keeping client →
#         save each page's HTML → headless Chrome renders it → Pillow trims the empty background.
import http.cookiejar, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, "docs", "images")
CHROME = os.environ.get("CHROME") or next((p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                                                       shutil.which("google-chrome") or "", shutil.which("chromium") or "") if p and os.path.exists(p)), None)
BG = (247, 248, 249)   # views.CSS --bg; the white sidebar (left 240px) is ignored when trimming

tmp = tempfile.mkdtemp(); os.environ["AUTOGUARD_DB"] = os.path.join(tmp, "demo.db")
from autoguard import config, auth  # noqa: E402
config.DB_PATH = os.environ["AUTOGUARD_DB"]; auth.ITER = 1000
import demo  # noqa: E402
demo.install()
from autoguard import web, scan  # noqa: E402
web.start_scan = lambda trigger: scan.run(trigger)          # synchronous: screenshots after the first check finishes

srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler); BASE = f"http://127.0.0.1:{srv.server_port}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
jar = http.cookiejar.CookieJar(); ua = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def req(path, data=None):
    body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
    try:
        with ua.open(urllib.request.Request(BASE + path, body, {"Origin": BASE} if body else {}), timeout=60) as r: return r.read().decode()
    except urllib.error.HTTPError as e: return e.read().decode()

csrf = lambda h: re.search(r'name="csrf" value="([^"]*)"', h).group(1)
html_dir = os.path.join(tmp, "html"); os.makedirs(html_dir)

def shot(name, html, height=1500, max_h=None, width=1280):
    f = os.path.join(html_dir, name + ".html"); open(f, "w").write(html.replace('http-equiv="refresh"', 'data-x="refresh"'))
    png = os.path.join(OUT, name + ".png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={width},{height}", f"--screenshot={png}", "file://" + f], capture_output=True, timeout=60)
    from PIL import Image
    im = Image.open(png).convert("RGB"); px = im.load(); w, h = im.size; bottom = h - 1
    while bottom > 200 and all(px[x, bottom] == BG for x in range(260, w, 7)): bottom -= 1
    floor = 620 if 'class="side"' in html else 0   # never cut the sidebar navigation in half
    im.crop((0, 0, w, min(max(bottom + 24, floor), max_h or h))).save(png, optimize=True)
    print("SHOT", name, Image.open(png).size)

def main():
    if not CHROME: sys.exit("Chrome not found — set CHROME=/path/to/chrome")
    os.makedirs(OUT, exist_ok=True)
    pw = "demo-password-123"
    shot("01-setup-account", req("/"), 900)
    h = req("/setup", {"step": "account", "username": "alex", "password": pw, "confirm": pw}); shot("02-setup-nextdns", h, 900)
    h = req("/setup", {"step": "nextdns", "csrf": csrf(h), "nextdns_api_key": "demo-nextdns-key-0000"})
    ticked = h
    for pid in ("a1b2c3", "d4e5f6", "0a9b8c"): ticked = ticked.replace(f'value="{pid}" >', f'value="{pid}" checked>')
    shot("03-setup-devices", ticked, 900)
    h = req("/setup", {"step": "devices", "csrf": csrf(h), "profile": ["a1b2c3", "d4e5f6", "0a9b8c"]}); shot("04-setup-ai", h, 1200)
    h = req("/setup", {"step": "ai", "csrf": csrf(h), "do": "test", "llm_provider": "openai", "llm_base_url": "https://api.openai.com/v1",
                       "llm_model": "gpt-5.4-mini", "llm_api_key": "demo-ai-key-0000", "llm_json_mode": "schema", "llm_extra": "{}"})
    shot("05-setup-preferences", h, 1600)
    h = req("/setup", {"step": "prefs", "csrf": csrf(h), "topic": ["uncensored_ai", "stranger_chat", "redpill"], "timezone": "Europe/London",
                       "scan_interval_hours": "4", "first_lookback_days": "7", "bedtime_start": "21:30", "bedtime_end": "07:00",
                       "allowed_guidance": "Mainstream AI assistants; messaging apps; YouTube; games; shopping; news; history and military history; school sites."})
    shot("06-home", req("/"), 1100)
    shot("07-blocked", req("/blocked"), 2200, 1700)
    shot("08-blocked-nextdns", req("/blocked?show=nextdns"), 1200)
    shot("09-to-check", req("/review"), 1000)
    shot("10-other-sites", req("/checked"), 1800, 1400)
    shot("11-fine-sites", req("/allowed"), 900)
    shot("12-hidden-sites", req("/hidden"), 1200)
    h = req("/blocked")
    shot("13-unblock-one-device", req("/action", {"op": "unblock", "domain": "character.ai", "profile": "d4e5f6", "back": "/blocked?device=d4e5f6", "csrf": csrf(h)}), 900, 760)
    h = req("/settings")
    shot("14-settings", h, 3200)
    shot("15-settings-ai-test", req("/settings", {"section": "ai", "do": "test", "csrf": csrf(h), "llm_provider": "openai",
                                                  "llm_base_url": "https://api.openai.com/v1", "llm_model": "gpt-5.4-mini",
                                                  "llm_json_mode": "schema", "llm_extra": "{}"}), 1500, 1250)
    shot("16-what-to-block", req("/topics"), 1500)
    shot("17-people", req("/users"), 1100)
    req("/action", {"op": "ok", "domain": "storyforge.example", "back": "/review", "csrf": csrf(h)})
    shot("18-history", req("/activity"), 1100)
    shot("19-checks", req("/runs"), 800)
    jar.clear(); shot("20-login", req("/login"), 700)
    srv.shutdown(); shutil.rmtree(tmp)

if __name__ == "__main__":
    main()
