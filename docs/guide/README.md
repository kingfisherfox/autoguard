# Autoguard user guide

This guide walks a parent through everything: getting NextDNS ready, installing Autoguard on a home server, the
five-minute setup, and using every page afterwards. No technical background is assumed. Where a step needs a
terminal, the exact command is given.

![The Home page](../images/06-home.png)

## Chapters

1. [Before you start](01-before-you-start.md): what Autoguard does, what you need, and how to put each child's device on NextDNS.
2. [Installing Autoguard](02-install.md): on a Linux box, a Raspberry Pi, a Synology or Unraid NAS, or a desktop computer.
3. [First-time setup](03-first-time-setup.md): the five setup steps, one screen at a time.
4. [Everyday use](04-everyday-use.md): Home, Blocked, To check, Other sites and Fine sites.
5. [Settings](05-settings.md): connections, what to block, people, history and checks.
6. [Looking after it](06-looking-after-it.md): updates, backups, passwords, remote access, troubleshooting and FAQ.

## The short version

1. Put each child's device on its own NextDNS profile and switch logs on.
2. On an always-on computer at home: `git clone https://github.com/kingfisherfox/autoguard.git && cd autoguard && docker compose up -d`
3. Open `http://<that computer's address>:8095` and follow the setup.
4. Every few days, glance at **To check**. That's it.

## Words used in this guide

| Word | Meaning |
|---|---|
| **Site** | A website or online service, written the way it appears in the address bar, for example `chess.com`. |
| **Device** | One child's phone, tablet or computer. In NextDNS each device has its own *profile*. |
| **Blocked** | The site won't open on that device. |
| **To check** | Autoguard thinks the site *might* be a problem and wants your decision. |
| **Fine** | You've said the site is OK. Autoguard never blocks it and doesn't ask the AI about it. |
| **Hidden** | Things you don't need to see, such as ad servers and app back-ends. They're still checked. |
| **Check** | One run of Autoguard: read the new lookups, judge new sites, block matches. |
| **Topic** | A kind of site you want gone, for example "Stranger chat". |

## Try it without any keys

To look around before connecting anything real, run the demo. It uses a pretend NextDNS account, a pretend AI and
an invented family (the screenshots in this guide come from it):

```bash
python3 tools/demo.py          # then open http://127.0.0.1:8199 and type anything as the keys
```
