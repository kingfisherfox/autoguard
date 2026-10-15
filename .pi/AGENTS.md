# Autoguard — agent router

Open-source, self-hosted NextDNS + AI auto-blocker for parents. Read `CONTEXT.md` (design, rules, terminology)
before changing code; `docs/CODE_INDEX.md` for where things live; `docs/guide/` is the parent-facing manual.

## Task routing
- What gets blocked / guardrails → `autoguard/guard.py`, `settings.DEFAULTS`, `db.TOPICS`, R-tests in `tests/`.
- AI providers → `settings.PRESETS`, `llm.py`, README provider table, guide chapter 3 and 5.
- Any UI change → `views.py`, then `python3 tools/screenshots.py` and check the guide still matches.
- Data model change → additive `db.MIGRATIONS` + `docs/schema.dbml`.

## Rules
- See `.pi/CONSTRAINTS.md`. Run `cd tests && python3 -m unittest test_autoguard` before every commit.
