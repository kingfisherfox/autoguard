# 2. Installing Autoguard

[← Before you start](01-before-you-start.md) · Next: [First-time setup →](03-first-time-setup.md)

Autoguard runs as one small Docker container. Pick the section for the computer you have. Every route ends the
same way: a web page at `http://<computer's address>:8095`.

> **Do the setup straight after installing.** The first person to open the page creates the admin account.

## Find your computer's address

You'll open Autoguard from any phone or laptop at home using the computer's local address, which usually looks
like `192.168.1.20`. On Linux run `hostname -I`; on a NAS it's on the NAS's network or info page; your router's
list of connected devices also shows it. It helps to give that computer a fixed address (a "DHCP reservation")
in your router so the link keeps working.

## Linux (Ubuntu, Debian, Raspberry Pi OS 64-bit, a mini PC)

1. Install Docker if it isn't there yet:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER      # then log out and back in
   ```
2. Download and start Autoguard:
   ```bash
   git clone https://github.com/kingfisherfox/autoguard.git
   cd autoguard
   docker compose up -d
   ```
3. Check it's running: `docker compose ps` should say `healthy` after about 20 seconds.
4. Open `http://<computer's address>:8095`.

No `git`? Download the ZIP from the GitHub page (green **Code** button → Download ZIP), unpack it, and run
`docker compose up -d` inside the folder.

## Synology NAS (DSM 7.2 or newer)

1. Install **Container Manager** from Package Center.
2. Download the ZIP from GitHub and unpack it into a shared folder, for example `docker/autoguard`.
3. Container Manager → **Project** → **Create**. Name it `autoguard`, choose the folder from step 2, and use the
   existing `compose.yaml`. Finish the wizard; it builds and starts the container.
4. Open `http://<NAS address>:8095`.

## Unraid

The simplest route is the terminal (top-right of the Unraid web page):

```bash
mkdir -p /mnt/user/appdata && cd /mnt/user/appdata
git clone https://github.com/kingfisherfox/autoguard.git && cd autoguard
docker compose up -d
```

If your Unraid version doesn't have `docker compose`, install the **Docker Compose Manager** plugin from Community
Applications and add the folder as a stack.

## Windows or Mac (Docker Desktop)

This works, but the computer must stay switched on and awake for Autoguard to check on schedule.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Download the ZIP from GitHub, unpack it, open a terminal in that folder and run `docker compose up -d`.
3. Open `http://localhost:8095` on that computer, or `http://<computer's address>:8095` from other devices.

## Port 8095 is already used

Start it on another port instead, for example 8100:

```bash
AUTOGUARD_PORT=8100 docker compose up -d
```

## Optional: keep keys out of the database

You don't need this. If you prefer to keep your NextDNS and AI keys in a file (or a secrets manager) rather than
typing them into the setup page, copy `.env.example` to `.env`, fill in the values and run `docker compose up -d`
again. Keys set this way show as "provided by the server environment" in Autoguard and can't be changed in the
browser. Never share or commit the `.env` file.

## Optional: a nicer address with HTTPS

On your home network the plain `http://` address is fine. If you already run a reverse proxy (Nginx Proxy Manager,
Caddy, Traefik), point a name such as `autoguard.home.arpa` at port 8095. When the proxy tells Autoguard the
connection is HTTPS, the login cookie is automatically marked secure.

**Don't** open port 8095 to the internet on your router. For access from outside the house, see
[Looking after it](06-looking-after-it.md#using-it-away-from-home).

[Next: First-time setup →](03-first-time-setup.md)
