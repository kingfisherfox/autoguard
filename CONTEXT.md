# Autoguard — agent context

## Purpose
Open-source, self-hosted add-on for NextDNS families: every N hours read the DNS logs of the children's devices,
have any OpenAI-compatible AI judge each never-seen site against a short topic list, block matches on every chosen
device, and let parents review/undo from a dashboard. Built to be given away: zero dependencies, one container,
everything configured in a browser wizard. Human docs: `README.md` + `docs/guide/`.

## User Stories
- As a parent, I install with `docker compose up -d`, open the page, and a wizard connects NextDNS + an AI in 5 minutes.
- As a parent, new AI-companion / stranger-chat / red-pill sites get blocked on all my kids' devices without me spotting them.
- As a parent, I see why something was blocked and undo it per device or everywhere — and it stays undone.
- As the other parent, I have my own login.

## Information Flow
- **Imports:** every check mirrors each enabled device's NextDNS denylist into `blocks` (source `nextdns`, per
  device, never spread, never re-decided; removed in NextDNS ⇒ shown unblocked, not re-added) and its allowlist into
  Fine (`owner_ok`, reason `nextdns_allowlist`). Imported sites get an AI description (topic/kind/group/about) only.
- **Descriptions:** every check fetches the homepage title/description of any shown site never fetched (≤200/check,
  no AI). Rows judged before groups existed (clean/imported/review/block) are re-sent once for group + about only;
  an answer without a valid group stores `other` so nothing is asked twice. Fine, hidden, big-platform and allowlist
  rows are never sent (R2/R3/R12/R13).
- **Inputs:** NextDNS API (`GET /profiles`, `/profiles/:id/logs` by watermark, deny/allowlists), homepage
  title/description (public addresses only), AI verdicts (`POST {base}/chat/completions`).
- **Outputs:** per-domain NextDNS denylist children (`POST|PATCH|DELETE /profiles/:id/denylist/<domain>`; never a
  full PUT), SQLite at `$AUTOGUARD_DB` (default `/data/autoguard.db`), dashboard, `/api/*.json` (Bearer token).
- **Schedule:** in-process thread (`scheduler.py`), `scan_interval_hours` (0 = off). CLI `python -m autoguard scan|backup|restore`.

## Terminology
- **profile / device** — one NextDNS profile per child device; only `profiles.enabled=1` are read or written.
- **domain key** — NextDNS `root` (registrable domain), or `tenant.<shared-host>` (`guard.SHARED`).
- **verdict** — pending → skip | clean | review | block; parent: owner_ok | owner_block | ignored (hidden); imported.
- **kind** — website | infrastructure (AI, `kind_by=ai`; no real homepage ⇒ infrastructure). Parents see only
  websites in Other sites; infrastructure, `last_blocked=1` (newest lookup blocked by NextDNS rules) and `skip` live
  under Hidden sites. Blocked/To check never filter by kind.
- **held** — block verdict over `max_blocks_per_run`; blocked next scan.
- **trial mode** — `dry_run=1`: everything recorded, nothing written to NextDNS.
- **group (category)** — `domains.category`, one of `db.CATEGORIES`, picked by the AI in the same reply as the verdict.
  Display only (list sections + filter chips); no rule reads it. Sites the AI may not see stay NULL ("Not sorted").
- **about** — the AI's ≤12-word plain summary (what it is, who runs it), shown with ✦ when the homepage title or
  description is missing — the only explanation a parent gets for background services.

## Key Files
- `autoguard/scan.py` — pipeline: sync profiles → pull → triage → enrich → classify → apply/reconcile/verify → record
- `autoguard/guard.py` — code-owned guardrails (NEVER list, shared-host keys, thresholds, cap)
- `autoguard/llm.py` — provider-agnostic client: json modes schema/object/prompt + auto fallback, robust parsing
- `autoguard/web.py` (routing, auth gates, wizard, writes) + `views.py` (HTML) · `auth.py` · `settings.py` (env > DB > default)
- `tests/test_autoguard.py` — product rules R1–R15 + LLM fallback + safety + backups + full HTTP wizard/auth/CSRF/pagination/plain-language
- `tools/demo.py` (fake NextDNS + AI + invented family) · `tools/screenshots.py` (regenerates `docs/images/` for `docs/guide/`)

## External Dependencies
- Schema: `docs/schema.dbml`. APIs: NextDNS https://nextdns.github.io/api/ · OpenAI-compatible chat completions.
- Verified 2026-10-15: OpenAI gpt-5.4-mini (schema), Cerebras qwen-3.8-27b (schema), OpenRouter
  anthropic/claude-haiku-5.5 (prompt; schema+require_parameters → 404 → auto falls back). Anthropic direct
  OpenAI-compat endpoint reported to ignore `response_format` → preset uses prompt mode (not live-verified: no key).

## Constraints
- UI copy is for NON-technical parents: no "domain/DNS/profile/confidence/verdict" on parent pages (a test checks).
  Default views show only possible problems (Blocked, To check); everything fine/noisy is opt-in.
- Stdlib only (Python 3.12). Light theme only. No external assets (CSP-friendly, offline LAN).
- Styling: Atlassian Design System light tokens, one `--ds-*` CSS variable per token in `views.CSS` (the only home
  for colours/spacing). Square corners everywhere (owner decision 2026-10-16; a test checks `border-radius` is 0).
- Every list page goes through `views.listing` (search + device + group filters, grouped rows); add list pages there,
  not with their own queries. Device = "looked it up" (`domains.profiles`) and narrows the list; on Blocked the device is
  a point of view (`narrow=False`): the master list with that device's state and one Block/Unblock for it.
- Secrets: only in the DB settings table or env; never rendered (masked last 4), never logged, never in git.
  Tests assert no key appears in any page.
- The AI never decides control flow: guardrails + thresholds + cap in code; LLM outage ⇒ `llm_error`, enforcement continues.
- Owner rows/verdicts are never overwritten by scans. Unticked profiles are never read or written.
- Enrichment must refuse non-public addresses (SSRF on a home LAN).
- DB changes: additive migrations in `db.MIGRATIONS` + update `docs/schema.dbml`.

## Attention Guidance
- Changing what gets blocked → `guard.py`, `settings.DEFAULTS`, `db.TOPICS`, and the R-tests.
- Adding a provider → `settings.PRESETS` + README table + a live `Settings → AI → Save & test`.
- Any UI change → regenerate screenshots (`tools/screenshots.py`) and re-read the matching guide chapter.
