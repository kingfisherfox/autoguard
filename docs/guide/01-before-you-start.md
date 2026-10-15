# 1. Before you start

[← Guide contents](README.md) · Next: [Installing Autoguard →](02-install.md)

## What Autoguard does, and what it doesn't

NextDNS is a filtering service your children's devices use to look up websites. It already blocks the big, well
known categories (porn, gambling, dating, piracy) and lets you set bedtimes. What it can't keep up with is the
steady stream of new sites that no list has caught yet: AI "girlfriend" and uncensored roleplay chatbots, Omegle
copies and random video-chat sites, red-pill and manosphere forums.

Autoguard reads which sites your children's devices looked up, asks an AI whether each **new** site belongs to one
of the topics you want gone, and blocks it on all your children's devices. You see what it did and why, and you
can undo anything with one click.

What it can't do:

- It works on whole sites. It can't block one YouTube channel, one TikTok account or one Discord server.
- It only sees devices that use NextDNS. A device with NextDNS switched off is invisible to it.
- The AI makes mistakes. That's why there's a review list, a limit on blocks per check, a list of sites that are
  never blocked, and a trial mode.

## What you need

| | |
|---|---|
| **A NextDNS account** | [nextdns.io](https://nextdns.io). The free plan covers a light-use family; heavy use needs the paid plan. |
| **One NextDNS profile per child device** | So each device can be handled separately. |
| **An AI key** | From OpenAI, Anthropic, OpenRouter, Cerebras or another provider that offers an OpenAI-compatible API, or a free local model with Ollama. A small model is enough; expect a few cents a day. |
| **An always-on computer at home** | A NAS, Raspberry Pi 4 or 5, mini PC or old laptop that can run Docker. Autoguard uses about 60 MB of memory. |

## Step 1: create a NextDNS profile for each device

1. Sign in at [my.nextdns.io](https://my.nextdns.io).
2. Use the profile menu at the top to create a new profile for each child device, for example *Sam's phone*,
   *Sam's tablet*, *Mia's phone*. Use names you'll recognise; Autoguard shows them.
3. Set up each profile's basic protection the way you want in NextDNS (Security, Privacy, Parental Control,
   bedtime "Recreation time"). Autoguard adds to this; it doesn't replace it.
4. In each profile go to **Settings → Logs** and make sure logging is **on**. Autoguard can only see what NextDNS logs.
   A retention of at least 7 days is a good idea.

## Step 2: put each device on its profile

Each profile's **Setup** page in NextDNS shows the exact instructions and the profile's ID (six letters and
numbers, for example `a1b2c3`).

- **Android phones and tablets:** Settings → Network & internet → Private DNS → *Private DNS provider hostname*,
  then enter `a1b2c3.dns.nextdns.io` (with your profile's ID). To make the device show up by name in the NextDNS
  logs, put a name in front: `Sams--Phone-a1b2c3.dns.nextdns.io` (a double hyphen becomes a space).
- **iPhone and iPad:** open [apple.nextdns.io](https://apple.nextdns.io) on the device, enter the profile ID,
  download the configuration profile and install it under Settings → General → VPN & Device Management.
- **Windows, Mac, Chromebook:** follow the profile's Setup page in NextDNS (there are apps for Windows and Mac).

Check it works: browse a little on the device, then open the profile's **Logs** page in NextDNS. You should see
lookups appearing.

## Step 3: stop the children switching it off

A child who knows where the setting is can turn NextDNS off. Lock it:

- **Android:** use Google Family Link and don't let the child change device settings, or use the device's own
  parental restrictions.
- **iPhone/iPad:** in Screen Time → Content & Privacy Restrictions, don't allow changes to the configuration
  profile, and turn off private relay and VPN apps.

Autoguard's setup shows how many lookups each device made in the last 7 days. A device that suddenly goes quiet
probably has NextDNS turned off.

## Step 4: get your two keys ready

- **NextDNS API key:** [my.nextdns.io/account](https://my.nextdns.io/account), scroll to **API**, copy the key. It
  works for your whole account.
- **AI key:** for example [OpenAI](https://platform.openai.com/api-keys),
  [Anthropic](https://console.anthropic.com/settings/keys), [OpenRouter](https://openrouter.ai/keys) or
  [Cerebras](https://cloud.cerebras.ai/). Most providers ask for a small prepayment. Set a monthly spending limit
  in their dashboard if they offer one.

Keep both somewhere safe for the next ten minutes. Autoguard stores them on your own computer and never shows them
again in full.

[Next: Installing Autoguard →](02-install.md)
