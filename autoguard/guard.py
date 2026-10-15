# CAPABILITY: guardrails — deterministic, code-owned decisions. The AI proposes topic + confidence; only these
#             functions decide what may be blocked, at what key, and how many per scan.
# NEVER: big platforms + OS/app infrastructure are never auto-blocked whatever the AI says — one wrong verdict would
#        break a phone. Parents who want e.g. Discord gone use NextDNS's own Parental Control → Apps.
import re

NEVER = frozenset("""
google.com googleapis.com gstatic.com googleusercontent.com googlevideo.com gvt1.com gvt2.com gvt3.com ggpht.com
googletagmanager.com google-analytics.com googleadservices.com googlesyndication.com doubleclick.net
app-measurement.com firebaseio.com crashlytics.com android.com youtube.com ytimg.com youtu.be youtube-nocookie.com
apple.com icloud.com mzstatic.com cdn-apple.com microsoft.com live.com office.com bing.com msn.com windows.net
xboxlive.com skype.com amazon.com amazonaws.com cloudfront.net cloudflare.com cloudflare-dns.com akamaihd.net
akamaized.net akamai.net fastly.net azureedge.net jsdelivr.net unpkg.com
facebook.com facebook.net fbcdn.net fbsbx.com messenger.com meta.com whatsapp.com whatsapp.net instagram.com
line-apps.com line-scdn.net line.me naver.jp discord.com discord.gg discordapp.com discordapp.net discord.media
telegram.org t.me signal.org snapchat.com tiktok.com tiktokcdn.com
openai.com chatgpt.com oaistatic.com oaiusercontent.com oaistatsig.com claude.ai anthropic.com gemini.google.com
xiaomi.com xiaomi.net miui.com mi-img.com samsung.com samsungcloud.com huawei.com
wikipedia.org wikimedia.org ntp.org github.com zoom.us
nextdns.io home.arpa
""".split())

# Shared hosting: one tenant must not take down the whole platform → block key = tenant label + suffix.
SHARED = sorted("""
up.railway.app railway.app vercel.app netlify.app pages.dev workers.dev github.io gitlab.io herokuapp.com
onrender.com fly.dev glitch.me replit.app repl.co web.app firebaseapp.com appspot.com wixsite.com blogspot.com
wordpress.com tumblr.com fandom.com substack.com notion.site carrd.co myshopify.com azurewebsites.net itch.io
neocities.org weebly.com webflow.io framer.app framer.website hf.space translate.goog
""".split(), key=len, reverse=True)

def covered(domain, suffixes):
    return any(domain == s or domain.endswith("." + s) for s in suffixes)

def domain_key(fqdn, root=None):
    """Block unit for a queried hostname: NextDNS `root` (registrable domain), or tenant.<shared-suffix>."""
    f = fqdn.lower().rstrip(".")
    for s in SHARED:
        if f.endswith("." + s): return ".".join(f.split(".")[-(s.count(".") + 2):])
    return (root or ".".join(f.split(".")[-2:])).lower()

def never_block(domain, allow=(), extra=()):
    return (covered(domain, NEVER) or covered(domain, allow) or covered(domain, extra)
            or domain.endswith((".arpa", ".local", ".lan", ".internal", ".localhost")))

# A homepage title like these means "no real website here" → background service (CDN, API, tracker, load balancer).
NO_SITE = re.compile(r"^\s*(?:\d{3}\b|not found|page not found|forbidden|access denied|bad request|unauthori[sz]ed|error\b|"
                     r"service unavailable|welcome to nginx|index of\b|it works|test page|default (?:web )?page|apache2?\b.*default|"
                     r"iis windows server|site not found|domain (?:is )?(?:for sale|parked)|parked domain|untitled|document$|redirecting)", re.I)

def has_site(title): return bool(title) and not NO_SITE.match(title)

def kind_of(ai_kind, title):
    """website | infrastructure. No real homepage ⇒ infrastructure (a parent can't judge what they can't open);
    otherwise the AI may still demote it (an SDK vendor's marketing page is not where the child went)."""
    if not has_site(title): return "infrastructure"
    return "infrastructure" if ai_kind == "infrastructure" else "website"

def decide(topic, confidence, cfg):
    if not topic or topic == "none": return "clean"
    return "block" if confidence >= cfg["block_at"] else "review" if confidence >= cfg["review_at"] else "clean"

def split_cap(domains, cap):
    return domains[:cap], domains[cap:]
