# Constraints

- **Public repo.** Never commit keys, `.env`, databases, real NextDNS profile ids, real family names, real visit
  data, or the maintainer's home-network details. Screenshots come only from `tools/demo.py` (invented data).
- **Never send real requests with fake keys or to real NextDNS accounts in tests.** Tests use fakes only.
- **Stdlib only** (Python 3.12). No external assets in the UI (works offline on a LAN).
- **Light theme only.** Parent-facing wording: plain English; no "domain/DNS/profile/confidence/verdict" on parent
  pages (a test enforces it).
- **The AI never owns control flow.** Thresholds, caps and never-block lists are code. AI outage ⇒ enforcement continues.
- **Parent decisions are never overwritten by a check.** Unticked NextDNS profiles are never read or written.
- **Only per-domain denylist writes** to NextDNS; never replace whole lists.
- The homepage fetcher must refuse non-public addresses.
- Doc files ≤ 300 lines; split and index when longer.
