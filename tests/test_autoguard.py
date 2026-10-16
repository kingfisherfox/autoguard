# Tests encode the product rules, not implementation details:
#   R1 a match is blocked straight away on EVERY chosen device · R2 a parent's unblock (some or all devices) is
#   remembered and never undone · R3 big platforms / allowlists are never auto-blocked whatever the AI says ·
#   R4 runaway brake (cap) · R5 a newly chosen device gets the master list · R6 an AI outage never loses enforcement ·
#   R7 shared hosting blocks the tenant, not the platform · R8 what is already on the NextDNS block list is SHOWN
#   (per device, never spread, never re-decided) and NextDNS stays the truth for it · R9 export = currently blocked per
#   device · R10 unchosen profiles are never read or touched · R11 trial mode writes nothing · R12 the NextDNS allowlist
#   is "fine" · R13 hidden sites are never shown or sent to the AI again · R14 background services stay out of the
#   parent's view unless flagged · R15 one click clears a page of fine sites · WEB: setup wizard, auth, CSRF,
#   same-origin, pagination, secrets never rendered, API token.
# RUN: cd apps/autoguard && python3 -m unittest discover tests
import http.cookiejar, json, os, re, sys, tempfile, threading, unittest, urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from autoguard import actions, auth, config, db, enrich, guard, llm, nextdns, scan, settings as S, web  # noqa: E402

auth.ITER = 1000
ND_KEY, LLM_KEY = "nd-good-secret-0123456789", "llm-secret-abcdefghijkl"

class FakeNX:
    def __init__(self, pids):
        self.pids = list(pids); self.deny = {p: {} for p in pids}; self.allow = {p: set() for p in pids}; self.log = {p: [] for p in pids}
        self.writes = []
    def add_profile(self, pid): self.pids.append(pid); self.deny[pid] = {}; self.allow[pid] = set(); self.log[pid] = []
    def profiles(self): return [{"id": p, "name": f"Kid {p}"} for p in self.pids]
    def queries_7d(self, pid): return len(self.log[pid])
    def deny_entries(self, pid): return dict(self.deny[pid])
    def allowlist(self, pid): return set(self.allow[pid])
    def add_deny(self, pid, d, exists=False): self.writes.append(("add", pid, d)); self.deny[pid][d] = True
    def del_deny(self, pid, d): self.writes.append(("del", pid, d)); self.deny[pid].pop(d, None)
    def logs(self, pid, since): return [l for l in self.log[pid] if since.startswith("-") or l["timestamp"] > since]
    def visit(self, pid, fqdn, ts=None, status="default"):
        if ts is None: FakeNX.n = getattr(FakeNX, "n", 0) + 1; ts = f"2026-10-15T15:{FakeNX.n // 60 % 60:02d}:{FakeNX.n % 60:02d}.000Z"
        self.log[pid].insert(0, {"timestamp": ts, "domain": fqdn, "root": ".".join(fqdn.split(".")[-2:]), "status": status})

class BadNX:
    def __getattr__(self, name):
        def f(*a, **k): raise nextdns.NextDNSError("NextDNS GET profiles: HTTP 403 — check the NextDNS API key", 403)
        return f

def fake_llm(verdicts):
    calls = []
    def f(items, topics, cfg, ok=(), bl=()):
        calls.append([i["domain"] for i in items])
        return {i["domain"]: (*verdicts.get(i["domain"], ("none", 0.95)), "test") for i in items}
    f.calls = calls; return f

REAL = (llm.classify, llm.test, enrich.fetch_many)   # Base tests monkeypatch these; restored so test order never matters

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); config.DB_PATH = os.path.join(self.tmp.name, "ag.db")
        enrich.fetch_many = lambda ds: {d: {"title": None, "description": None, "fetch_error": None} for d in ds}
        self.nd = FakeNX(["aaa111", "bbb222"])
        nextdns.client = lambda key: self.nd if key.startswith("nd-good") else BadNX()
        for k in S.ENV.values(): os.environ.pop(k, None)
    def tearDown(self): self.tmp.cleanup(); llm.classify, llm.test, enrich.fetch_many = REAL
    def con(self): return db.connect()
    def configure(self, pids=("aaa111", "bbb222"), **extra):
        con = self.con()
        for k, v in {"setup_done": "1", "nextdns_api_key": ND_KEY, "llm_api_key": LLM_KEY, **extra}.items(): S.put(con, k, v)
        con.commit(); scan.sync_profiles(con, self.nd); actions.set_devices(con, list(pids), "test"); con.close()
    def blocked_on(self, d): return sorted(p for p in self.nd.pids if self.nd.deny[p].get(d) is True)

class TestRules(Base):
    def test_R1_match_blocked_on_every_device_even_if_seen_on_one(self):
        self.configure(); self.nd.visit("aaa111", "app.harpy.chat"); llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)})
        scan.run("test"); self.assertEqual(self.blocked_on("harpy.chat"), ["aaa111", "bbb222"])

    def test_R1_low_confidence_goes_to_review_not_blocked(self):
        self.configure(); self.nd.visit("aaa111", "maybe.chat"); llm.classify = fake_llm({"maybe.chat": ("stranger_chat", 0.6)})
        scan.run("test")
        self.assertEqual(self.blocked_on("maybe.chat"), [])
        self.assertEqual(self.con().execute("SELECT verdict FROM domains WHERE domain='maybe.chat'").fetchone()[0], "review")

    def test_R2_per_device_unblock_is_remembered_across_scans(self):
        self.configure(); self.nd.visit("aaa111", "lemonchat.app"); llm.classify = fake_llm({"lemonchat.app": ("stranger_chat", 0.95)})
        scan.run("test"); self.assertEqual(actions.unblock(self.con(), self.nd, "lemonchat.app", ["aaa111"], "mum"), [])
        self.nd.visit("bbb222", "lemonchat.app", ts="2026-10-15T19:00:00.000Z"); scan.run("test")
        self.assertEqual(self.blocked_on("lemonchat.app"), ["bbb222"])

    def test_R2_unblock_everywhere_marks_fine_and_is_never_reclassified(self):
        self.configure(); self.nd.visit("aaa111", "fableai.app"); f = llm.classify = fake_llm({"fableai.app": ("uncensored_ai", 0.9)})
        scan.run("test"); actions.unblock(self.con(), self.nd, "fableai.app", ["aaa111", "bbb222"], "mum")
        self.nd.visit("aaa111", "fableai.app", ts="2026-10-15T20:00:00.000Z"); scan.run("test")
        self.assertEqual(self.blocked_on("fableai.app"), [])
        self.assertEqual(sum(c.count("fableai.app") for c in f.calls), 1)
        self.assertEqual(self.con().execute("SELECT verdict FROM domains WHERE domain='fableai.app'").fetchone()[0], "owner_ok")

    def test_R2_owner_block_on_some_devices_does_not_spread(self):
        self.configure(); llm.classify = fake_llm({})
        actions.block(self.con(), self.nd, "example-stranger.com", ["bbb222"], "dad"); scan.run("test")
        self.assertEqual(self.blocked_on("example-stranger.com"), ["bbb222"])

    def test_R3_big_platforms_never_blocked_even_if_ai_says_so(self):
        self.configure()
        for d in ("chatgpt.com", "legy.line-apps.com", "web.whatsapp.com", "discord.com", "www.youtube.com"): self.nd.visit("aaa111", d)
        f = llm.classify = fake_llm({d: ("uncensored_ai", 0.99) for d in ("chatgpt.com", "line-apps.com", "whatsapp.com", "discord.com", "youtube.com")})
        scan.run("test")
        self.assertFalse(any(self.nd.deny[p] for p in self.nd.pids)); self.assertEqual(f.calls, [])

    def test_R3_nextdns_allowlist_and_parent_never_list_win(self):
        self.configure(never_block_extra="school-chat.example")
        self.nd.allow["aaa111"].add("canva-like.com")
        for d in ("canva-like.com", "school-chat.example"): self.nd.visit("aaa111", d)
        llm.classify = fake_llm({"canva-like.com": ("uncensored_ai", 0.99), "school-chat.example": ("stranger_chat", 0.99)})
        scan.run("test")
        self.assertEqual(self.blocked_on("canva-like.com") + self.blocked_on("school-chat.example"), [])

    def test_R4_cap_holds_excess_and_blocks_it_next_run(self):
        self.configure(max_blocks_per_run="2")
        ds = [f"bad{i}.chat" for i in range(3)]; [self.nd.visit("aaa111", d) for d in ds]
        llm.classify = fake_llm({d: ("uncensored_ai", 0.9) for d in ds})
        scan.run("test"); self.assertEqual(sum(bool(self.blocked_on(d)) for d in ds), 2)
        scan.run("test"); self.assertEqual(sum(bool(self.blocked_on(d)) for d in ds), 3)

    def test_R5_newly_chosen_device_gets_master_list(self):
        self.configure(); self.nd.visit("aaa111", "harpy.chat"); llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)}); scan.run("test")
        self.nd.add_profile("ccc333"); scan.run("test")
        self.assertEqual(self.blocked_on("harpy.chat"), ["aaa111", "bbb222"])        # not chosen yet → untouched
        actions.set_devices(self.con(), ["aaa111", "bbb222", "ccc333"], "mum"); scan.run("test")
        self.assertEqual(self.blocked_on("harpy.chat"), ["aaa111", "bbb222", "ccc333"])

    def test_R6_ai_outage_keeps_enforcing_and_retries_later(self):
        self.configure(); self.nd.visit("aaa111", "harpy.chat"); llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)}); scan.run("test")
        self.nd.deny["aaa111"].pop("harpy.chat")
        self.nd.visit("aaa111", "newsite.chat", ts="2026-10-15T21:00:00.000Z")
        def down(*a, **k): raise llm.LLMError("HTTP 401: bad key", 401)
        llm.classify = down; scan.run("test")
        con = self.con()
        self.assertEqual(self.blocked_on("harpy.chat"), ["aaa111", "bbb222"])
        self.assertEqual(con.execute("SELECT verdict FROM domains WHERE domain='newsite.chat'").fetchone()[0], "pending")
        self.assertEqual(con.execute("SELECT status FROM runs ORDER BY id DESC").fetchone()[0], "llm_error")

    def test_ai_rate_limit_is_calm_not_an_error(self):
        self.configure(); self.nd.visit("aaa111", "newsite.chat")
        def busy(*a, **k): raise llm.LLMError("HTTP 429: high traffic", 429)
        llm.classify = busy; scan.run("test")
        self.assertEqual(self.con().execute("SELECT status FROM runs ORDER BY id DESC").fetchone()[0], "ai_busy")

    def test_sites_judged_before_kind_existed_are_re_sorted_by_the_ai(self):
        self.configure(); self.nd.visit("aaa111", "sentry-like.example")
        llm.classify = fake_llm({}); scan.run("test")
        con = self.con(); con.execute("UPDATE domains SET kind=NULL, kind_by=NULL"); con.commit()
        f = llm.classify = lambda items, *a, **k: {i["domain"]: ("none", 0.9, "", "infrastructure") for i in items}
        scan.run("test")
        self.assertEqual(con.execute("SELECT verdict, kind, kind_by FROM domains WHERE domain='sentry-like.example'").fetchone()[:],
                         ("clean", "infrastructure", "ai"))

    def test_R7_shared_hosting_blocks_tenant_only(self):
        self.assertEqual(guard.domain_key("evil.up.railway.app", "railway.app"), "evil.up.railway.app")
        self.assertEqual(guard.domain_key("x.y.wixsite.com", "wixsite.com"), "y.wixsite.com")
        self.assertEqual(guard.domain_key("api.zeta-ai.io", "zeta-ai.io"), "zeta-ai.io")

    def test_R8_existing_nextdns_blocks_are_shown_per_device_and_nextdns_stays_the_truth(self):
        self.configure(); self.nd.deny["aaa111"]["kick.com"] = True; self.nd.visit("aaa111", "kick.com")
        llm.classify = fake_llm({"kick.com": ("redpill", 0.95)}); scan.run("test")
        con = self.con()
        self.assertEqual(con.execute("SELECT verdict, topic FROM domains WHERE domain='kick.com'").fetchone()[:], ("imported", "redpill"))
        self.assertEqual(self.blocked_on("kick.com"), ["aaa111"])                     # not spread to bbb222
        self.assertEqual(actions.export(con)["aaa111"], ["kick.com"])                 # manual policy apply keeps it
        self.nd.deny["aaa111"].pop("kick.com"); scan.run("test")                    # parent removed it in NextDNS
        self.assertEqual(self.blocked_on("kick.com"), [])
        self.assertEqual(con.execute("SELECT state FROM blocks WHERE domain='kick.com'").fetchone()[0], "unblocked")

    def test_R8_unblocking_an_imported_site_removes_it_from_nextdns(self):
        self.configure(); self.nd.deny["bbb222"]["rumble.com"] = True; llm.classify = fake_llm({}); scan.run("test")
        actions.unblock(self.con(), self.nd, "rumble.com", ["bbb222"], "mum"); scan.run("test")
        self.assertEqual(self.blocked_on("rumble.com"), [])

    def test_R9_export_lists_only_currently_blocked_per_device(self):
        self.configure(); self.nd.visit("aaa111", "harpy.chat"); llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)}); scan.run("test")
        actions.unblock(self.con(), self.nd, "harpy.chat", ["bbb222"], "mum")
        self.assertEqual(actions.export(self.con()), {"aaa111": ["harpy.chat"], "bbb222": []})

    def test_R10_unchosen_profile_is_never_read_or_touched(self):
        self.configure(pids=["aaa111"]); self.nd.visit("bbb222", "parents-only.chat")
        self.nd.visit("aaa111", "harpy.chat"); f = llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)})
        scan.run("test")
        self.assertEqual(self.blocked_on("harpy.chat"), ["aaa111"]); self.assertNotIn("parents-only.chat", sum(f.calls, []))

    def test_R11_trial_mode_writes_nothing_to_nextdns(self):
        self.configure(dry_run="1"); self.nd.visit("aaa111", "harpy.chat"); llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)})
        scan.run("test")
        self.assertEqual(self.nd.writes, [])
        self.assertEqual(self.con().execute("SELECT count(*) FROM blocks WHERE state='blocked'").fetchone()[0], 2)

    def test_R12_nextdns_allowlist_is_fine_and_never_sent_to_the_ai(self):
        self.configure(); self.nd.allow["aaa111"].add("school.example"); self.nd.visit("aaa111", "school.example")
        f = llm.classify = fake_llm({"school.example": ("stranger_chat", 0.99)}); scan.run("test")
        con = self.con()
        self.assertEqual(con.execute("SELECT verdict FROM domains WHERE domain='school.example'").fetchone()[0], "owner_ok")
        self.assertEqual(sum(f.calls, []), [])

    def test_R13_hidden_site_is_never_sent_to_the_ai_again(self):
        self.configure(); self.nd.visit("aaa111", "lb-1234.example"); f = llm.classify = fake_llm({}); scan.run("test")
        actions.hide(self.con(), "lb-1234.example", "mum")
        self.nd.visit("aaa111", "lb-1234.example", ts="2026-10-16T01:00:00.000Z"); scan.run("test")
        self.assertEqual(sum(c.count("lb-1234.example") for c in f.calls), 1)
        self.assertEqual(self.con().execute("SELECT verdict FROM domains WHERE domain='lb-1234.example'").fetchone()[0], "ignored")

    def test_R14_background_services_are_not_websites(self):
        self.assertEqual(guard.kind_of(None, None), "infrastructure")
        self.assertEqual(guard.kind_of(None, "404 Not Found"), "infrastructure")
        self.assertEqual(guard.kind_of(None, "Welcome to nginx!"), "infrastructure")
        self.assertEqual(guard.kind_of(None, "Alpha History"), "website")
        self.assertEqual(guard.kind_of("infrastructure", "Branch — deep links"), "infrastructure")
        self.assertEqual(guard.kind_of("website", None), "infrastructure")             # unreachable: parent can't judge it

    def test_not_configured_scan_is_a_noop(self):
        self.assertIsNone(scan.run("test"))

    def test_overlapping_runs_are_a_noop(self):
        import fcntl
        self.configure(); lock = open(db.lock_path(), "w"); fcntl.flock(lock, fcntl.LOCK_EX)
        self.assertIsNone(scan.run("test")); lock.close()

    def test_bedtime_window_crosses_midnight(self):
        f = scan.night_checker({"bedtime_start": "21:30", "bedtime_end": "07:00", "timezone": "Etc/GMT-7"})
        self.assertEqual([f("2026-10-15T15:00:00Z"), f("2026-10-15T23:30:00Z"), f("2026-10-15T05:00:00Z")], [True, True, False])

class TestLLM(unittest.TestCase):
    CFG = {"llm_base_url": "http://x/v1", "llm_model": "m", "llm_api_key": "k", "llm_extra": {}, "llm_json_mode": "auto",
           "allowed_guidance": "fine stuff"}
    def setUp(self): llm._WORKS.clear(); self._post = llm._post
    def tearDown(self): llm._post = self._post

    def test_parse_handles_fences_prose_think_and_bare_lists(self):
        good = [{"domain": "a.com", "topic": "none", "confidence": 1, "reason": "r"}]
        for t in ['```json\n{"results": %s}\n```' % json.dumps(good), 'Sure! Here you go: {"results": %s} hope that helps' % json.dumps(good),
                  "<think>hmm</think>%s" % json.dumps(good), json.dumps({"domains": good})]:
            self.assertEqual(llm.parse(t), good, t)
        with self.assertRaises(llm.LLMError): llm.parse("I cannot help with that.")

    def test_auto_mode_falls_back_when_provider_rejects_schema_and_temperature(self):
        seen = []
        def post(cfg, body):
            seen.append((body.get("response_format", {}).get("type"), "temperature" in body))
            if body.get("response_format", {}).get("type") == "json_schema": raise llm.LLMError("HTTP 400: response_format not supported", 400)
            if "temperature" in body: raise llm.LLMError("HTTP 400: Unsupported value: 'temperature'", 400)
            return {"choices": [{"message": {"content": '{"results": [{"domain": "a.com", "topic": "redpill", "confidence": 0.9, "reason": "x"}]}'}}]}
        llm._post = post
        out = llm.classify([{"domain": "a.com"}], [{"id": "redpill", "description": "d"}], self.CFG)
        self.assertEqual(out["a.com"][0], "redpill")
        self.assertEqual(seen, [("json_schema", True), ("json_object", True), ("json_object", False)])
        llm.classify([{"domain": "a.com"}], [{"id": "redpill", "description": "d"}], self.CFG)
        self.assertEqual(seen[-1], ("json_object", False))   # cached: no repeated failures per batch

    def test_openrouter_no_endpoint_for_parameters_falls_back(self):
        def post(cfg, body):
            if "response_format" in body: raise llm.LLMError("HTTP 404: No endpoints found that can handle the requested parameters.", 404)
            return {"choices": [{"message": {"content": '[{"domain": "a.com", "topic": "none", "confidence": 0.9, "reason": ""}]'}}]}
        llm._post = post
        self.assertEqual(llm.classify([{"domain": "a.com"}], [{"id": "redpill", "description": "d"}], self.CFG)["a.com"][0], "none")

    def test_model_not_found_is_not_retried_as_a_format_problem(self):
        calls = []
        def post(cfg, body): calls.append(1); raise llm.LLMError("HTTP 404: model not found", 404)
        llm._post = post
        with self.assertRaises(llm.LLMError): llm.classify([{"domain": "a.com"}], [{"id": "redpill", "description": "d"}], self.CFG)
        self.assertEqual(len(calls), 1)

    def test_unknown_topics_and_bad_confidence_are_dropped_or_clamped(self):
        llm._post = lambda cfg, body: {"choices": [{"message": {"content": json.dumps({"results": [
            {"domain": "a.com", "topic": "made_up", "confidence": 1, "reason": ""},
            {"domain": "b.com", "topic": "redpill", "confidence": "7", "reason": ""}]})}}]}
        out = llm.classify([{"domain": "a.com"}, {"domain": "b.com"}], [{"id": "redpill", "description": "d"}], dict(self.CFG, llm_json_mode="prompt"))
        self.assertEqual(out, {"b.com": ("redpill", 1.0, "", None, None, None)})

    def test_group_and_one_liner_are_parsed_and_unknown_groups_dropped(self):
        # display-only fields: a made-up group must not leak into the UI; the one-liner is trimmed to one short line
        llm._post = lambda cfg, body: {"choices": [{"message": {"content": json.dumps({"results": [
            {"domain": "a.com", "topic": "none", "confidence": 1, "kind": "infrastructure", "category": "ads",
             "about": "  Google's   advertising\nnetwork ", "reason": ""},
            {"domain": "b.com", "topic": "none", "confidence": 1, "category": "made_up", "reason": ""}]})}}]}
        out = llm.classify([{"domain": "a.com"}, {"domain": "b.com"}], [{"id": "redpill", "description": "d"}], dict(self.CFG, llm_json_mode="prompt"))
        self.assertEqual(out["a.com"][4:], ("ads", "Google's advertising network"))
        self.assertEqual(out["b.com"][4:], (None, None))

class TestDescriptions(Base):
    """Every site a parent sees says what it is; grouping comes from the AI only for sites the AI may already see."""
    def test_ai_group_and_one_liner_are_stored_and_an_ungrouped_answer_is_not_re_asked(self):
        self.configure(); self.nd.visit("aaa111", "ads-x.example"); self.nd.visit("aaa111", "plain.example")
        f = llm.classify = lambda items, *a, **k: f.log.append([i["domain"] for i in items]) or {
            i["domain"]: ("none", 0.9, "", "infrastructure", "ads" if i["domain"] == "ads-x.example" else None,
                          "Ad network" if i["domain"] == "ads-x.example" else None) for i in items}
        f.log = []; scan.run("test")
        con = self.con(); get = lambda d: tuple(con.execute("SELECT category, about FROM domains WHERE domain=?", (d,)).fetchone())
        self.assertEqual(get("ads-x.example"), ("ads", "Ad network"))
        self.assertEqual(get("plain.example"), ("other", None))       # answered without a group → "other", never re-asked
        scan.run("test"); self.assertEqual(len(f.log), 1)

    def test_sites_judged_before_groups_existed_are_described_once(self):
        self.configure(); self.nd.visit("aaa111", "old.example"); llm.classify = fake_llm({}); scan.run("test")
        con = self.con(); con.execute("UPDATE domains SET category=NULL"); con.commit()
        f = llm.classify = fake_llm({}); scan.run("test"); scan.run("test")
        self.assertEqual(sum(c.count("old.example") for c in f.calls), 1)
        self.assertEqual(self.con().execute("SELECT verdict FROM domains WHERE domain='old.example'").fetchone()[0], "clean")

    def test_fine_sites_get_their_homepage_described_without_asking_the_ai(self):
        self.configure(); con = self.con(); actions.fine_add(con, "myschool.example", "mum"); con.commit()
        enrich.fetch_many = lambda ds: {d: {"title": "Hillside School", "description": "Pupil portal", "fetch_error": None} for d in ds}
        f = llm.classify = fake_llm({}); scan.run("test")
        row = self.con().execute("SELECT title, description, category FROM domains WHERE domain='myschool.example'").fetchone()
        self.assertEqual(tuple(row), ("Hillside School", "Pupil portal", None))
        self.assertEqual(sum(f.calls, []), [])                       # R12 holds: fine sites never go to the AI

class TestSafety(unittest.TestCase):
    def test_enrich_never_fetches_private_addresses(self):
        for h in ("127.0.0.1", "192.168.1.1", "10.0.0.1", "localhost", "169.254.169.254"): self.assertFalse(enrich.is_public(h), h)

    def test_enrich_parse_meta_any_attribute_order(self):
        self.assertEqual(enrich.parse('<title>X</title><meta content="Chat with strangers" name="description">'), ("X", "Chat with strangers"))

    def test_backup_and_restore_round_trip(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "AUTOGUARD_DB": os.path.join(d, "a.db"), "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
            run = lambda *a, inp=None: subprocess.run([sys.executable, "-m", "autoguard", *a], input=inp, capture_output=True, env=env)
            c = db.connect(env["AUTOGUARD_DB"]); S.put(c, "llm_model", "kept-model"); c.commit(); c.close()
            blob = run("backup").stdout; self.assertTrue(blob.startswith(b"SQLite format 3"))
            c = db.connect(env["AUTOGUARD_DB"]); S.put(c, "llm_model", "changed"); c.commit(); c.close()
            self.assertEqual(run("restore", inp=blob).returncode, 0)
            self.assertEqual(S.get(db.connect(env["AUTOGUARD_DB"]), "llm_model"), "kept-model")
            self.assertNotEqual(run("restore", inp=b"not a database").returncode, 0)

    def test_password_hashing_and_throttle(self):
        h = auth.hash_pw("correct horse"); self.assertTrue(auth.check_pw("correct horse", h)); self.assertFalse(auth.check_pw("nope", h))
        t = auth.Throttle(); [t.fail("ip") for _ in range(5)]; self.assertTrue(t.locked("ip")); t.ok("ip"); self.assertFalse(t.locked("ip"))

    def test_settings_validation(self):
        self.assertEqual(S.clean("block_at", "0.9"), ("0.9", None)); self.assertIsNotNone(S.clean("block_at", "2")[1])
        self.assertIsNotNone(S.clean("timezone", "Mars/Base")[1]); self.assertEqual(S.clean("bedtime_start", "21:30"), ("21:30", None))
        self.assertEqual(S.normalize_domain("https://Bad.Example.com/path?x"), "bad.example.com"); self.assertEqual(S.normalize_domain("not a domain"), "")

class Web(Base):
    """Drives the real HTTP server like a browser would."""
    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler); self.base = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        web.start_scan = lambda trigger: scan.run(trigger)
        llm.classify = fake_llm({}); web.THROTTLE.fails.clear(); self.new_browser()
    def tearDown(self): self.srv.shutdown(); self.srv.server_close(); super().tearDown()
    def new_browser(self):
        self.jar = http.cookiejar.CookieJar(); self.ua = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
    def req(self, path, data=None, headers=None):
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        try:
            with self.ua.open(urllib.request.Request(self.base + path, body, headers or {}), timeout=10) as r:
                return r.status, r.geturl().replace(self.base, ""), r.read().decode()
        except urllib.error.HTTPError as e: return e.code, path, e.read().decode()
    def csrf(self, html): return re.search(r'name="csrf" value="([^"]*)"', html).group(1)
    def post(self, path, data, page="/settings"):
        return self.req(path, {**data, "csrf": self.csrf(self.req(page)[2])})

    def setup_all(self):
        self.req("/setup", {"step": "account", "username": "mum", "password": "long-enough-pw", "confirm": "long-enough-pw"})
        self.post("/setup", {"step": "nextdns", "nextdns_api_key": ND_KEY}, "/setup")
        self.post("/setup", {"step": "devices", "profile": ["aaa111", "bbb222"]}, "/setup")
        llm.test = lambda cfg, topics: {"ok": True, "seconds": 0.1, "rows": [], "right": 3, "mode": "schema"}
        self.post("/setup", {"step": "ai", "do": "test", "llm_provider": "openai", "llm_base_url": "https://api.openai.com/v1",
                             "llm_model": "gpt-x", "llm_api_key": LLM_KEY, "llm_json_mode": "schema", "llm_extra": "{}"}, "/setup")
        return self.post("/setup", {"step": "prefs", "topic": ["uncensored_ai", "stranger_chat", "redpill"], "timezone": "Europe/London",
                                    "scan_interval_hours": "4", "first_lookback_days": "7", "allowed_guidance": "chess sites"}, "/setup")

    def test_first_visit_goes_to_setup_and_wizard_finishes_with_a_first_scan(self):
        self.nd.visit("aaa111", "harpy.chat"); llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)})
        code, url, html = self.req("/")
        self.assertEqual(url, "/setup"); self.assertIn("Create your login", html)
        code, url, html = self.req("/setup", {"step": "account", "username": "mum", "password": "short", "confirm": "short"})
        self.assertEqual(code, 400); self.assertIn("at least 10", html)
        code, url, html = self.req("/setup", {"step": "account", "username": "mum", "password": "long-enough-pw", "confirm": "long-enough-pw"})
        self.assertIn("Connect NextDNS", html)
        code, _, html = self.post("/setup", {"step": "nextdns", "nextdns_api_key": "nd-bad-key"}, "/setup")
        self.assertEqual(code, 400); self.assertIn("didn", html)
        code, url, html = self.post("/setup", {"step": "nextdns", "nextdns_api_key": ND_KEY}, "/setup")
        self.assertIn("Kid aaa111", html); self.assertIn("Kid bbb222", html)
        code, _, html = self.post("/setup", {"step": "devices"}, "/setup"); self.assertEqual(code, 400)
        self.post("/setup", {"step": "devices", "profile": ["aaa111", "bbb222"]}, "/setup")
        llm.test = lambda cfg, topics: {"ok": False, "seconds": 0.1, "error": "HTTP 401: invalid key"}
        code, _, html = self.post("/setup", {"step": "ai", "do": "test", "llm_provider": "cerebras", "llm_base_url": "https://api.cerebras.ai/v1",
                                             "llm_model": "qwen", "llm_api_key": LLM_KEY, "llm_json_mode": "schema", "llm_extra": "{}"}, "/setup")
        self.assertIn("AI test failed", html); self.assertNotIn(LLM_KEY, html)
        code, url, html = self.setup_all()
        self.assertEqual(url.split("?")[0], "/"); self.assertIn("All set", html)
        self.assertEqual(self.blocked_on("harpy.chat"), ["aaa111", "bbb222"])            # first scan populated + blocked
        con = self.con(); self.assertEqual(S.get(con, "timezone"), "Europe/London"); self.assertTrue(S.get(con, "api_token"))

    def test_logged_out_users_must_log_in_and_throttle_kicks_in(self):
        self.setup_all(); self.new_browser()
        self.assertEqual(self.req("/blocked")[1].split("?")[0], "/login")
        for _ in range(5): self.assertEqual(self.req("/login", {"username": "mum", "password": "wrong-password"})[0], 401)
        self.assertEqual(self.req("/login", {"username": "mum", "password": "long-enough-pw"})[0], 429)
        web.THROTTLE.fails.clear()
        code, url, _ = self.req("/login", {"username": "mum", "password": "long-enough-pw", "next": "/blocked"})
        self.assertEqual((code, url), (200, "/blocked"))

    def test_secrets_are_never_rendered(self):
        self.setup_all(); con = self.con(); token = S.get(con, "api_token")
        for path in ("/settings", "/", "/blocked", "/runs", "/users", "/topics"):
            html = self.req(path)[2]
            for s in (ND_KEY, LLM_KEY, token): self.assertNotIn(s, html, path)

    def test_csrf_and_cross_origin_posts_are_refused(self):
        self.setup_all()
        self.assertEqual(self.req("/action", {"op": "run"})[0], 403)
        self.assertEqual(self.req("/action", {"op": "run", "csrf": self.csrf(self.req("/")[2])}, {"Origin": "http://evil.example"})[0], 403)

    def test_api_needs_token(self):
        self.setup_all(); token = S.get(self.con(), "api_token"); self.new_browser()
        self.assertEqual(self.req("/api/denylist.json")[0], 401)
        code, _, body = self.req("/api/denylist.json", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(code, 200); self.assertIn("aaa111", json.loads(body)["profiles"])

    def test_blocked_list_is_paginated(self):
        self.setup_all(); con = self.con()
        for i in range(120):
            d = f"site{i:03d}.chat"; db.ensure_domain(con, d); db.set_block(con, d, "aaa111", "blocked", "auto")
        con.commit()
        rows = lambda html: len(re.findall(r'<td class="dom">', html))
        self.assertEqual(rows(self.req("/blocked")[2]), 50)
        p3 = self.req("/blocked?page=3")[2]; self.assertEqual(rows(p3), 20); self.assertIn("Page 3 of 3", p3)
        self.assertEqual(rows(self.req("/blocked?q=site11")[2]), 10)

    def test_dashboard_unblock_on_one_device(self):
        self.nd.visit("aaa111", "harpy.chat"); llm.classify = fake_llm({"harpy.chat": ("uncensored_ai", 0.97)}); self.setup_all()
        self.post("/action", {"op": "unblock", "domain": "harpy.chat", "profile": "bbb222"}, "/blocked")
        self.assertEqual(self.blocked_on("harpy.chat"), ["aaa111"])

    def test_manual_block_of_www_url_blocks_whole_site(self):
        self.setup_all()
        self.post("/action", {"op": "add", "domain": "https://www.chatroulette.com/x", "profile": ["aaa111", "bbb222"]}, "/blocked")
        self.assertEqual(self.blocked_on("chatroulette.com"), ["aaa111", "bbb222"])

    def test_parent_views_show_problems_and_hide_noise(self):
        titles = {"realsite.example": "Chess Club — play chess online", "cdn-edge.example": None}
        enrich.fetch_many = lambda ds: {d: {"title": titles.get(d), "description": None, "fetch_error": None} for d in ds}
        self.nd.deny["aaa111"]["kick.com"] = True
        for d in ("realsite.example", "cdn-edge.example", "maybe.chat"): self.nd.visit("aaa111", d)
        llm.classify = fake_llm({"maybe.chat": ("stranger_chat", 0.6)}); self.setup_all()
        other, hidden = self.req("/checked")[2], self.req("/hidden?show=background")[2]
        self.assertIn("realsite.example", other); self.assertNotIn("cdn-edge.example", other); self.assertIn("cdn-edge.example", hidden)
        self.assertIn("maybe.chat", self.req("/review")[2]); self.assertIn('<span class=badge>1</span>', self.req("/")[2])
        blocked = self.req("/blocked?show=nextdns")[2]
        self.assertIn("kick.com", blocked); self.assertIn("On your NextDNS block list", blocked)
        visible = lambda h: re.sub(r"<[^>]+>", " ", h.split("</style>")[1]).lower()   # what a parent actually reads
        for page in (other, blocked, self.req("/")[2], self.req("/review")[2]):
            for bad in ("domain", "dns lookup", "verdict", "confidence", "profile"): self.assertNotIn(bad, visible(page))

    def test_R15_one_click_clears_a_page_of_fine_sites(self):
        enrich.fetch_many = lambda ds: {d: {"title": f"Site {d}", "description": None, "fetch_error": None} for d in ds}
        for i in range(3): self.nd.visit("aaa111", f"ok{i}.example")
        self.setup_all()
        code, url, html = self.post("/action", {"op": "bulk_ok", "back": "/checked", "domain": ["ok0.example", "ok1.example", "ok2.example"]}, "/checked")
        self.assertIn("3 sites moved to Fine sites", html); self.assertNotIn("ok1.example", self.req("/checked")[2])
        self.assertIn("ok1.example", self.req("/allowed")[2])

    def test_site_now_blocked_by_nextdns_rules_leaves_other_sites(self):
        enrich.fetch_many = lambda ds: {d: {"title": "Some Gifs", "description": None, "fetch_error": None} for d in ds}
        self.nd.visit("aaa111", "gifs.example", ts="2026-10-10T04:00:00.000Z"); self.setup_all()
        self.assertIn("gifs.example", self.req("/checked")[2])
        self.nd.visit("aaa111", "gifs.example", ts="2026-10-15T23:00:00.000Z", status="blocked")   # NextDNS porn category now
        self.post("/action", {"op": "run"}, "/")
        self.assertNotIn("gifs.example", self.req("/checked")[2]); self.assertIn("gifs.example", self.req("/hidden?show=nextdns")[2])

    def test_fine_list_add_and_remove(self):
        self.setup_all()
        self.post("/action", {"op": "fine_add", "domain": "https://www.myschool.example/login", "back": "/allowed"}, "/allowed")
        self.assertIn("myschool.example", self.req("/allowed")[2])
        self.post("/action", {"op": "unfine", "domain": "myschool.example", "back": "/allowed"}, "/allowed")
        self.assertNotIn("myschool.example", self.req("/allowed")[2])

    def test_env_key_shows_as_environment_and_is_used(self):
        os.environ["NEXTDNS_API_KEY"] = ND_KEY
        try:
            self.req("/setup", {"step": "account", "username": "mum", "password": "long-enough-pw", "confirm": "long-enough-pw"})
            html = self.req("/setup?step=nextdns")[2]; self.assertIn("Provided by the server environment", html); self.assertNotIn(ND_KEY, html)
            code, _, html = self.post("/setup", {"step": "nextdns"}, "/setup"); self.assertIn("Kid aaa111", html)
        finally: os.environ.pop("NEXTDNS_API_KEY")

    def test_blocked_sites_can_be_filtered_by_device(self):
        self.setup_all(); con = self.con()
        db.ensure_domain(con, "only-a.chat"); db.set_block(con, "only-a.chat", "aaa111", "blocked", "owner")
        db.ensure_domain(con, "only-b.chat"); db.set_block(con, "only-b.chat", "bbb222", "blocked", "owner"); con.commit()
        a, b = self.req("/blocked?device=aaa111")[2], self.req("/blocked?device=bbb222")[2]
        self.assertIn("only-a.chat", a); self.assertNotIn("only-b.chat", a)
        self.assertIn("only-b.chat", b); self.assertNotIn("only-a.chat", b)
        both = self.req("/blocked?device=nope")[2]                    # unknown device → everything, not an error
        self.assertIn("only-a.chat", both); self.assertIn("only-b.chat", both)

    def test_lists_are_grouped_and_say_what_each_site_is(self):
        self.setup_all(); con = self.con()
        for d, cat, title, desc, about in (("chess.example", "games", "Chess Club", "Play chess online", None),
                                           ("news.example", "news", "Daily News", None, None),
                                           ("tracker.example", "ads", None, None, "Advertising network")):
            db.ensure_domain(con, d, seen=True)
            con.execute("UPDATE domains SET verdict='clean', kind=?, category=?, title=?, description=?, about=?, hits=3 WHERE domain=?",
                        ("infrastructure" if d == "tracker.example" else "website", cat, title, desc, about, d))
        con.commit()
        other = self.req("/checked")[2]
        self.assertIn("Play chess online", other)                    # meta description shown, not just the title
        self.assertLess(other.index(">Games<"), other.index(">News &amp; reading<"))   # grouped, in a fixed order
        self.assertNotIn("Daily News", self.req("/checked?cat=games")[2])
        self.assertIn("chess.example", self.req("/checked?q=chess+club")[2])            # search matches what it is
        self.assertIn("Advertising network", self.req("/hidden?show=background")[2])    # background: the AI one-liner

    def test_every_settings_form_has_a_save_button(self):
        # regression: Schedule and Blocking rules once rendered "Save" as plain text — the parent had no way to submit
        html = self.setup_all() and self.req("/settings")[2]
        for sid in ("nextdns", "devices", "ai", "schedule", "rules"):
            form = html.split(f'id="{sid}"', 1)[1].split("</form>", 1)[0]
            self.assertIn("<button", form, sid)

    def test_users_can_be_added_and_password_changed(self):
        self.setup_all()
        self.post("/users", {"op": "add", "username": "dad", "password": "another-long-pw"}, "/users")
        self.assertIn("dad", self.req("/users")[2])
        code, url, html = self.post("/users", {"op": "password", "password": "brand-new-pw-1", "confirm": "brand-new-pw-1"}, "/users")
        self.assertIn("Password changed", html)
        self.new_browser(); code, url, _ = self.req("/login", {"username": "mum", "password": "brand-new-pw-1"}); self.assertEqual(url, "/")

if __name__ == "__main__":
    unittest.main()
