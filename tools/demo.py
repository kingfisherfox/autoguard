# CAPABILITY: run Autoguard with a FAKE NextDNS account, FAKE AI and invented family data — no keys, no network.
#             For trying the app, developing the UI, and producing the guide's screenshots (tools/screenshots.py).
# USAGE:  python3 tools/demo.py [--port 8199] [--db /tmp/autoguard-demo.db]
#         then open http://127.0.0.1:8199 — any NextDNS/AI key works in the setup wizard (type anything).
# SAFETY: nextdns.client, llm.classify and enrich.fetch_many are replaced before the server starts; nothing leaves
#         this machine. Every device name, site visit and timestamp below is made up.
import argparse, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOCAL = ZoneInfo("Europe/London")   # the demo family's time zone (matches tools/screenshots.py)
DEVICES = {"a1b2c3": "Sam’s phone", "d4e5f6": "Sam’s tablet", "0a9b8c": "Mia’s phone", "7f7f7f": "Parents’ laptop"}

# site → (title, topic|None, confidence, kind, reason)
SITES = {
    "character.ai":        ("Character.AI — chat with AI characters", "uncensored_ai", .96, "website", "AI character roleplay chat; companion bots."),
    "spicychat.ai":        ("SpicyChat — uncensored AI roleplay", "uncensored_ai", .98, "website", "Title advertises uncensored NSFW AI roleplay."),
    "ai-girlfriend.example": ("Your AI girlfriend, no filters", "uncensored_ai", .97, "website", "AI girlfriend app with no content filters."),
    "ome.tv":              ("OmeTV — random video chat", "stranger_chat", .97, "website", "Random video chat with strangers, Omegle alternative."),
    "chatroulette.com":    ("Chatroulette — meet strangers on cam", "stranger_chat", .96, "website", "Random webcam chat with strangers."),
    "talk-to-randoms.example": ("Talk to random people", "stranger_chat", .62, "website", "Anonymous chat; unclear if it pairs strangers."),
    "alpha-mindset.example": ("Escape the Matrix — alpha male course", "redpill", .91, "website", "Manosphere self-improvement course with misogynist framing."),
    "storyforge.example":  ("StoryForge — write stories with AI", "uncensored_ai", .58, "website", "AI story writing; mature mode mentioned."),
    "wikipedia.org":       ("Wikipedia, the free encyclopedia", None, .99, "website", "Encyclopedia."),
    "khanacademy.org":     ("Khan Academy | Free online courses", None, .99, "website", "School learning site."),
    "minecraft.net":       ("Minecraft", None, .98, "website", "Game."),
    "chess.com":           ("Chess.com — play chess online", None, .98, "website", "Online chess."),
    "duolingo.com":        ("Duolingo — learn a language for free", None, .99, "website", "Language learning."),
    "bbc.co.uk":           ("BBC — Home", None, .99, "website", "News."),
    "imperialwarmuseums.org.uk": ("Imperial War Museums", None, .97, "website", "History museum; war history is fine."),
    "scratch.mit.edu":     ("Scratch — imagine, program, share", None, .99, "website", "Kids' coding site."),
    "nationalgeographic.com": ("National Geographic", None, .99, "website", "Science and nature."),
    "lego.com":            ("LEGO.com", None, .99, "website", "Toys."),
    "cdn-edge-17.example": (None, None, .95, "infrastructure", "Content delivery network, no homepage."),
    "metrics-collector.example": ("404 Not Found", None, .95, "infrastructure", "Analytics endpoint."),
    "lb-eu-west.example":  (None, None, .95, "infrastructure", "Load balancer."),
    "ads-exchange.example": ("Ad exchange for publishers", None, .9, "infrastructure", "Advertising service."),
    "app-backend.example": ("Welcome to nginx!", None, .95, "infrastructure", "App back-end server."),
}
# site → (group, AI one-liner, homepage meta description) — what the parent sees under each address
ABOUT = {
    "character.ai": ("ai", "AI character chat app", "Chat with millions of AI characters, anytime."),
    "spicychat.ai": ("ai", "Uncensored AI roleplay chat", "No filters. Create and chat with any character."),
    "ai-girlfriend.example": ("ai", "AI girlfriend chat app", "She’s always there for you. No limits."),
    "ome.tv": ("social", "Random video chat with strangers", "Meet new people from all over the world on video."),
    "chatroulette.com": ("social", "Random webcam chat with strangers", "Chat with random people on camera."),
    "talk-to-randoms.example": ("social", "Anonymous text chat site", "Talk to someone new. No sign-up."),
    "alpha-mindset.example": ("hobbies", "Paid 'alpha male' self-help course", "Escape the matrix. Join 40,000 men."),
    "storyforge.example": ("ai", "AI story-writing tool", "Write stories together with AI. Mature mode available."),
    "wikipedia.org": ("learning", "Free online encyclopedia", "The free encyclopedia that anyone can edit."),
    "khanacademy.org": ("learning", "Free school lessons and practice", "Free courses for maths, science and more."),
    "minecraft.net": ("games", "Official Minecraft game site", "Explore, build and survive in Minecraft."),
    "chess.com": ("games", "Online chess games and lessons", "Play chess online with friends."),
    "duolingo.com": ("learning", "Language-learning app", "The free, fun way to learn a language."),
    "bbc.co.uk": ("news", "BBC news, TV and radio", "News, sport, TV, radio and more."),
    "imperialwarmuseums.org.uk": ("learning", "UK war history museums", "Museums telling the stories of war."),
    "scratch.mit.edu": ("learning", "Kids’ coding site from MIT", "Create stories, games and animations."),
    "nationalgeographic.com": ("news", "Science, nature and travel magazine", "Explore science, nature and history."),
    "lego.com": ("shopping", "Official LEGO shop and games", "Shop LEGO sets and play games."),
    "cdn-edge-17.example": ("services", "Content delivery servers for apps", None),
    "metrics-collector.example": ("ads", "App usage analytics service", None),
    "lb-eu-west.example": ("services", "Load balancer for a cloud provider", None),
    "ads-exchange.example": ("ads", "Advertising exchange for mobile games", "Monetise your app with programmatic ads."),
    "app-backend.example": ("services", "Back-end servers for a mobile game", None),
    "kick.com": ("video", "Live-streaming site", "Watch live streams."),
    "4chan.org": ("social", "Anonymous image forum", None),
}
VISITS = {   # device → [(site, hours_ago, times, at_night)]
    "a1b2c3": [("spicychat.ai", 3, 6, True), ("ome.tv", 5, 3, True), ("wikipedia.org", 2, 40, False), ("minecraft.net", 4, 22, False),
               ("alpha-mindset.example", 20, 4, False), ("talk-to-randoms.example", 7, 2, True), ("cdn-edge-17.example", 1, 90, False),
               ("chess.com", 6, 15, False), ("imperialwarmuseums.org.uk", 30, 3, False), ("metrics-collector.example", 1, 70, False)],
    "d4e5f6": [("character.ai", 9, 12, True), ("scratch.mit.edu", 26, 9, False), ("storyforge.example", 11, 3, False),
               ("lb-eu-west.example", 2, 55, False), ("lego.com", 50, 4, False), ("ads-exchange.example", 3, 30, False)],
    "0a9b8c": [("chatroulette.com", 14, 2, False), ("ai-girlfriend.example", 40, 1, True), ("duolingo.com", 8, 30, False),
               ("khanacademy.org", 10, 18, False), ("bbc.co.uk", 12, 7, False), ("nationalgeographic.com", 28, 5, False),
               ("app-backend.example", 2, 64, False)],
    "7f7f7f": [("bbc.co.uk", 1, 20, False)],
}
ALREADY_BLOCKED = {"a1b2c3": ["4chan.org", "kick.com"], "d4e5f6": ["4chan.org", "kick.com"], "0a9b8c": ["4chan.org"]}
ALREADY_ALLOWED = {"a1b2c3": ["myschool.example"], "d4e5f6": ["myschool.example"], "0a9b8c": ["myschool.example"]}
TITLES = {"4chan.org": "4chan", "kick.com": "Kick — live streaming", "myschool.example": "Hillside School — pupil portal"}

class DemoNextDNS:
    def __init__(self):
        now = datetime.now(timezone.utc); self.deny, self.allow, self.log = {}, {}, {}
        for pid in DEVICES:
            self.deny[pid] = {d: True for d in ALREADY_BLOCKED.get(pid, [])}; self.allow[pid] = set(ALREADY_ALLOWED.get(pid, []))
            rows = []
            for site, h, times, night in VISITS.get(pid, []):
                for k in range(times):
                    t = (now - timedelta(hours=h, minutes=k * 3)).astimezone(LOCAL)
                    if night: t = t.replace(hour=22, minute=k % 60)
                    elif t.hour < 8 or t.hour >= 21: t = t.replace(hour=16, minute=(k * 3) % 60)   # daytime visits stay daytime
                    while t > now: t -= timedelta(days=1)
                    t = t.astimezone(timezone.utc)
                    rows.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "domain": ("www." if k % 2 else "") + site,
                                 "root": site, "status": "blocked" if site in self.deny[pid] else "default"})
            self.log[pid] = sorted(rows, key=lambda r: r["timestamp"], reverse=True)
    def profiles(self): return [{"id": p, "name": n} for p, n in DEVICES.items()]
    def queries_7d(self, pid): return len(self.log[pid]) * 37
    def deny_entries(self, pid): return dict(self.deny[pid])
    def allowlist(self, pid): return set(self.allow[pid])
    def add_deny(self, pid, d, exists=False): self.deny[pid][d] = True
    def del_deny(self, pid, d): self.deny[pid].pop(d, None)
    def logs(self, pid, since): return [l for l in self.log[pid] if since.startswith("-") or l["timestamp"] > since]

def fake_classify(items, topics, cfg, ok=(), bl=()):
    ids, out = {t["id"] for t in topics}, {}
    for i in items:
        d = i["domain"]
        if d in SITES:
            _, topic, c, kind, why = SITES[d]
            out[d] = (topic if topic in ids else "none", c, why, kind)
        elif "video-chat" in d: out[d] = ("stranger_chat" if "stranger_chat" in ids else "none", .97, "Random video chat with strangers.", "website")
        elif "girlfriend" in d: out[d] = ("uncensored_ai" if "uncensored_ai" in ids else "none", .97, "Uncensored AI girlfriend.", "website")
        elif d == "4chan.org": out[d] = ("none", .7, "", "website")
        elif d == "kick.com": out[d] = ("redpill" if "redpill" in ids else "none", .8, "Streaming host used by manosphere influencers.", "website")
        else: out[d] = ("none", .95, "Encyclopedia." if "wikipedia" in d else "No evidence of a listed topic.", "website")
    return {d: (*v, *([None] * 4))[:4] + ABOUT.get(d, ("other", None, None))[:2] for d, v in out.items()}

def fake_fetch_many(domains):
    return {d: {"title": SITES.get(d, (TITLES.get(d),))[0], "description": ABOUT.get(d, (None, None, None))[2], "fetch_error": None}
            for d in domains}

def install():
    from autoguard import enrich, llm, nextdns
    demo = DemoNextDNS()
    nextdns.client = lambda key: demo
    llm.classify = fake_classify
    enrich.fetch_many = fake_fetch_many
    return demo

if __name__ == "__main__":
    a = argparse.ArgumentParser(); a.add_argument("--port", default="8199"); a.add_argument("--db", default="/tmp/autoguard-demo.db")
    o = a.parse_args(); os.environ["PORT"], os.environ["AUTOGUARD_DB"] = o.port, o.db
    from autoguard import config; config.PORT, config.DB_PATH = int(o.port), o.db
    install()
    print(f"DEMO: fake NextDNS + fake AI — open http://127.0.0.1:{o.port} (type any key in the wizard)", file=sys.stderr)
    from autoguard import web; web.main()
