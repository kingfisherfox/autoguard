# 🛡️ Autoguard

**AI-assisted website blocking for your children's devices, on top of [NextDNS](https://nextdns.io). Self-hosted, free, no tracking.**

NextDNS already blocks the big categories (porn, gambling, dating, piracy). What it can't keep up with is the stream
of *new* sites: AI "girlfriend" and uncensored roleplay chatbots, Omegle copies and random video-chat sites, red-pill
and manosphere forums. A new one appears every week under a new name.

Autoguard reads which sites your children's devices looked up, asks an AI whether each **new** site belongs to a
topic you want gone, and blocks it on **all** your children's devices, usually within hours of the first visit. You
see what it did and why, and undo anything per device or everywhere with one click. It remembers your decisions.

![Autoguard home page](docs/images/06-home.png)

It's one small Docker container on any always-on computer at home (NAS, Raspberry Pi, mini PC). Nothing to install
on the children's devices beyond NextDNS itself.

## 📖 [Read the full user guide](docs/guide/README.md)

Step by step, with screenshots: [preparing NextDNS](docs/guide/01-before-you-start.md) ·
[installing](docs/guide/02-install.md) · [first-time setup](docs/guide/03-first-time-setup.md) ·
[everyday use](docs/guide/04-everyday-use.md) · [settings](docs/guide/05-settings.md) ·
[updates, backups and troubleshooting](docs/guide/06-looking-after-it.md).

## Quick start

You need: a NextDNS account with **one profile per child device** and logs switched on, an API key from an AI
provider, and Docker with Compose v2.24 or newer.

```bash
git clone https://github.com/kingfisherfox/autoguard.git
cd autoguard
docker compose up -d
```

Open **`http://<your-server-ip>:8095`** and follow the five-step setup: create your login, paste your NextDNS key,
tick your children's devices, connect an AI (with a live test), choose what to block. The first check starts
straight away.

Want to look around first? `python3 tools/demo.py` runs it with a pretend NextDNS account, a pretend AI and an
invented family. No keys needed.

## How it works

1. **Shows what you already have.** Each device's NextDNS block list appears on the Blocked page; your NextDNS allow
   list becomes your Fine sites. If you change something in NextDNS, Autoguard follows.
2. **Reads** the lookups of the devices you ticked (only those) from the NextDNS API, every few hours.
3. **Skips** anything already judged, your Fine sites, your NextDNS allowlist, and big platforms that must never be
   blocked by mistake (Google, Apple, Microsoft, Meta, WhatsApp, Discord, YouTube, ChatGPT and others).
4. **Looks** at each new site's homepage title and description, because names alone mislead.
5. **Asks** the AI, with your topics and your "what's fine in our family" note. The AI answers with a topic, how
   sure it is, a one-line reason, and whether it's a real website or a background service.
6. **Decides in code, not by AI.** Very likely matches are blocked on every device. Unsure ones go to *To check* for
   you. A per-check limit stops a misbehaving AI.
7. **Blocks and verifies** by adding the site to each device's NextDNS denylist and reading it back.

Parents only see what might be a problem. Ad servers, app back-ends and load balancers are sorted out and hidden.

| Page | For |
|---|---|
| **Home** | Is it working, when it checks next, anything that needs you. |
| **Blocked** | Every blocked site with what it is and why; one button per device to block or allow it there. |
| **To check** | Possible problems the AI wasn't sure about: *Block it* or *It's fine*. |
| **Other sites** | Sites judged fine. Optional reading; one click clears a page. |
| **Fine sites** | Sites you trust. Never blocked, never sent to the AI. |
| **Settings** | Connections and AI test, what to block, people, hidden sites, history, checks. |

Default topics: **Uncensored / companion AI**, **Stranger chat**, **Red pill / manosphere**, plus an optional
**Porn & adult content (backup)**. All editable.

## AI providers

Any OpenAI-compatible `/chat/completions` API works. Setup has presets:

| Provider | Base URL | Example model | Notes |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-5.4-mini` | Strict JSON schema. |
| Anthropic (Claude) | `https://api.anthropic.com/v1` | `claude-haiku-4-5` | Anthropic's OpenAI-compatible endpoint ignores JSON schemas, so the preset asks for JSON in the prompt. |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-5.4-mini`, `anthropic/claude-haiku-5.5` | Auto mode falls back when a route can't do strict JSON. |
| Cerebras | `https://api.cerebras.ai/v1` | `qwen-3.8-27b` | Very fast. |
| Ollama (local) | `http://host.docker.internal:11434/v1` | `qwen3:8b` | Free and private. No key. |
| Anything else | your URL | your model | LM Studio, vLLM, LiteLLM, Groq, Together, Mistral… |

Tested live: OpenAI `gpt-5.4-mini`, Cerebras `qwen-3.8-27b`, OpenRouter `anthropic/claude-haiku-5.5`. The direct
Anthropic preset has only been tested for its error handling so far; reports of success welcome.

## Privacy and security

- **What leaves your network.** To NextDNS: API calls with your key. To your AI provider: site addresses, public page
  titles and descriptions, your topic text. **Never** which child visited what, when, IP addresses or page contents.
  Autoguard also fetches the public homepage of each new site to read its title.
- **What's stored.** One SQLite file in the `autoguard-data` volume: your keys, logins (salted PBKDF2 hashes),
  settings and the sites seen. Readable only by the container user. Keys are never shown again (last 4 characters
  only). Prefer a secrets manager? Use `.env` (see `.env.example`).
- **Protections.** Login throttling, per-session CSRF tokens, same-origin checks, `HttpOnly`/`SameSite` cookies
  (`Secure` behind HTTPS), no external scripts or fonts, runs as a non-root user, and the homepage fetcher refuses
  private addresses so a hostile site can't make it probe your router or NAS.
- **Keep it on your home network.** Don't port-forward 8095. Use a VPN or an HTTPS reverse proxy for remote access.
- **API.** `GET /api/status.json` and `GET /api/denylist.json` with `Authorization: Bearer <token>` (Settings).

## Limits

It works on whole sites, not individual YouTube channels or Discord servers. It only sees devices that use NextDNS.
The AI makes mistakes, which is why there's a review list, a block limit, a never-block list and trial mode. It
complements conversations and tools like Family Link or Screen Time; it doesn't replace them.

## Development

Python 3.12 standard library only. No dependencies.

```bash
cd tests && python3 -m unittest test_autoguard     # 48 tests: blocking rules, imports, hiding, setup, auth, CSRF, backups
python3 tools/demo.py                              # demo server with fake NextDNS + AI on :8199
python3 tools/screenshots.py                       # regenerate docs/images (needs Chrome + Pillow)
AUTOGUARD_DB=./data/dev.db python3 -m autoguard    # real server on :8095
```

Code map: [`docs/CODE_INDEX.md`](docs/CODE_INDEX.md) · data model: [`docs/schema.dbml`](docs/schema.dbml) · design
notes for contributors and coding agents: [`CONTEXT.md`](CONTEXT.md).

## License

MIT. See [LICENSE](LICENSE).
