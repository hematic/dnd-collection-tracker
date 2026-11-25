# Docker hosting

The [Docker Hub image](https://hub.docker.com/r/hematic/dnd-collection-tracker) runs on Linux amd64 and arm64. Each setup runs two containers from the same image: the web app and the OCR worker that indexes PDFs for [PDF search](../README.md#search-inside-your-pdfs).

← [Back to the README](../README.md) · [Configuration reference](configuration.md) · [Reverse proxy and login](reverse-proxy.md) · [Back up and restore](backup.md)

| Setup | Compose file | Login | For |
|---|---|---|---|
| [Local only](#local-only) | [`compose.local.yml`](../compose.local.yml) | None | One person on their own computer |
| [Authenticated](#authenticated-setup) | [`docker-compose.yml`](../docker-compose.yml) | From your reverse proxy | A server shared with a group, or access from outside your network |

## Local only

Use Docker Engine 28 or newer (or a current Docker Desktop) and Docker Compose v2. This setup needs no account, proxy, or `.env` file.

```sh
mkdir -p dnd-tracker/pdfs
cd dnd-tracker
curl -fLO https://raw.githubusercontent.com/hematic/dnd-collection-tracker/main/compose.local.yml
docker compose -f compose.local.yml up -d
```

On Windows, or without `curl`, create an empty folder, download [`compose.local.yml`](https://raw.githubusercontent.com/hematic/dnd-collection-tracker/main/compose.local.yml) into it (right-click, **Save link as**), and run `docker compose -f compose.local.yml up -d` from that folder.

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). **Keep this stack local.** It has no login; anyone who can reach it can edit and open linked PDFs. For remote access, use the [authenticated setup](#authenticated-setup) instead.

The `dnd-tracker-local_tracker-data` volume holds the database and covers and survives `docker compose -f compose.local.yml down`. Do not add `-v` unless you intend to delete that data. Add PDFs to `./pdfs`, or set `DND_LOCAL_PDF_DIR` to your library path. Set `DND_LOCAL_PORT` if port `8765` is already taken. You can put these optional settings in a `.env` file next to the Compose file.

## Authenticated setup

Put the app behind a reverse proxy that handles login, as described in [Reverse proxy and login](reverse-proxy.md). That guide includes Traefik, Caddy and nginx examples, including a read-only guest hostname next to a login-protected one for editors.

The database and covers live in `DND_DATA_DIR`, mounted at `/data`. Keep it on the host's local disk, not a network share. The PDF library in `DND_PDF_DIR` (default `/mnt/dnd/Books`) is mounted read-only at `/pdfs` in both containers. Every setting is listed in the [configuration reference](configuration.md).

1. Download `docker-compose.yml` and `tracker.env.example` from the [GitHub release](https://github.com/hematic/dnd-collection-tracker/releases) you want to install. Rename `tracker.env.example` to `.env` to use that release's pinned image. From a source checkout, use [`.env.example`](../.env.example) instead.
2. In `.env`, set `DND_DATA_DIR`, `DND_PDF_DIR`, the editors in `DND_TRACKER_ADMINS`, and your proxy's IP in `DND_TRACKER_TRUSTED_PROXIES`.
3. Create `DND_DATA_DIR` and give `PUID:PGID` write access. If moving an existing collection, stop the old app and copy its database and covers there. If existing links use a Windows or NAS path, set [`DND_TRACKER_PDF_MAP`](configuration.md#dnd_tracker_pdf_map). New installs can leave the mapping blank and use **Browse PDF library** to pick files from `DND_PDF_DIR`.
4. Route your proxy to `DND_PORT` (default `8765`) and set up the login as described in [Reverse proxy and login](reverse-proxy.md).
5. Deploy the stack with `docker compose pull && docker compose up -d`.

**Komodo, Portainer and similar:** Point the stack at `docker-compose.yml`, paste your `.env` settings into its environment, and leave building off. The stack pulls the published image.

## Updating

[Back up first](backup.md). Then change `DND_TRACKER_IMAGE` to the new `X.Y.Z` tag and run `docker compose pull && docker compose up -d`. For the local setup, add `-f compose.local.yml` to both commands.

`latest` follows the newest stable release. Pin a numbered tag to control when you upgrade. [Release notes](../CHANGELOG.md) say when a release changes the Compose files; download the new ones from that release, because pulling the image doesn't update them.

To roll back, run the old image with the backup taken before the upgrade. Don't open an upgraded database with an older image.

## Health checks

The image has a health check for both containers. The web app is healthy when it answers `/healthz`. The OCR worker is healthy while it keeps renewing its hold on the indexing queue, which it does every 10 seconds. `docker compose ps` shows the result, and so do tools that read Docker's health status, such as Komodo, Dozzle or Uptime Kuma.

Docker doesn't restart a container just because it's unhealthy. The restart policy only acts when the process exits.

## Security hardening

Both Compose files run the containers with:

- a read-only filesystem, plus a 64 MB in-memory `/tmp` for cover uploads in progress and the worker's health check file
- no Linux capabilities and `no-new-privileges`
- a non-root user: `PUID:PGID` in `docker-compose.yml`, UID 1000 in `compose.local.yml`
- log rotation at 10 MB, keeping three files

If your Docker daemon sends logs to another driver, such as Loki or journald, remove the `logging` block from the Compose file.

## Building from source

```sh
docker build -t dnd-collection-tracker:local .
DND_TRACKER_IMAGE=dnd-collection-tracker:local docker compose up -d --pull never
```

## Troubleshooting

- **The UI reports "OCR worker offline".** Check `docker compose ps` and `docker compose logs -f dnd-tracker-ocr`. The worker shows as `unhealthy` when it hasn't renewed its hold on the indexing queue in the last minute.
- **Indexing slows the host.** Lower `DND_OCR_CPU_SHARES`, for example to `256`. It sets relative priority, not a hard cap, so the worker still uses idle CPU.
- **"Open this app through its public address".** See [Reverse proxy troubleshooting](reverse-proxy.md#troubleshooting).
- **The app can't write to `/data`.** `DND_DATA_DIR` must be writable by `PUID:PGID`. Run `ls -ln` on the folder and compare its owner with your `.env`.
