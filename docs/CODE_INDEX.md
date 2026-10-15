# Code index

## Repository shape
```
autoguard/            the app (Python 3.12 stdlib only)
  __main__.py         CLI: web (default) · scan · create-user · reset-password · backup · restore
  web.py              HTTP server: routing, login/session gates, setup wizard, all writes, JSON API
  views.py            HTML for every page (parent-facing wording lives here)
  scan.py             one check: import NextDNS lists → read logs → triage → enrich → AI → block → verify
  guard.py            code-owned guardrails: never-block list, shared-hosting keys, website vs background, thresholds
  llm.py              OpenAI-compatible AI client: JSON modes + fallback, robust parsing, connection test
  nextdns.py          NextDNS API client (per-domain denylist writes only)
  enrich.py           homepage title/description fetcher (public addresses only)
  actions.py          parent decisions: block/unblock per device, fine, hide, topics, export
  auth.py · settings.py · db.py · scheduler.py · config.py
tests/test_autoguard.py   product rules + HTTP walkthroughs (fake NextDNS and AI)
tools/demo.py             fake NextDNS + AI + invented family, for trying the app and screenshots
tools/screenshots.py      renders docs/images from the demo
docs/guide/               the user guide · docs/images/ screenshots · docs/schema.dbml data model
Dockerfile · compose.yaml · .env.example
```

## Entry points
- Container: `python -m autoguard` (web + built-in scheduler), port 8095, data in `/data/autoguard.db`.
- One check by hand: `python -m autoguard scan`.

## Main flows
- Setup wizard (`web.wizard`) → settings table → first check (`scan.run`).
- Check: `scan.run` → `import_lists` → `pull` → `triage` → `classify_all` (→ `enrich`, `llm.classify`) → `apply`.
- Parent click → `web.post_action` → `actions.*` → NextDNS write + read-back → `actions` history row.
