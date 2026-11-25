# Configuration reference

Every setting is an environment variable. A local install needs none of them. For Docker, put the Compose settings in a `.env` file next to the Compose file, or in your stack manager's environment (Komodo, Portainer).

← [Back to the README](../README.md)

## Authenticated setup (`docker-compose.yml`)

These are read by [`docker-compose.yml`](../docker-compose.yml). [`.env.example`](../.env.example) lists them with comments.

| Variable | Default | What it does |
|---|---|---|
| `DND_DATA_DIR` | *required* | Host folder for the database and covers, mounted at `/data`. Use an absolute path on the host's local disk, not a network share: SQLite needs local file locking. |
| `DND_TRACKER_ADMINS` | *required* | Comma-separated usernames or emails that may edit. Matched, ignoring case, against the `Remote-User` and `Remote-Email` headers from your proxy. Everyone else is read-only. |
| `DND_TRACKER_TRUSTED_PROXIES` | *required* | Comma-separated IPs your reverse proxy connects from. The app refuses every other client except localhost. `TRAEFIK_IP` is the old name and is used when this one is blank. See [Reverse proxy and login](reverse-proxy.md). |
| `DND_PDF_DIR` | `/mnt/dnd/Books` | Host folder with your PDF library, mounted read-only at `/pdfs` in both containers. |
| `DND_TRACKER_PDF_MAP` | *(blank)* | Translates PDF paths stored by an older install to paths inside the container. See [`DND_TRACKER_PDF_MAP`](#dnd_tracker_pdf_map). |
| `DND_TRACKER_IMAGE` | `hematic/dnd-collection-tracker:latest` | Image for both services. Pin an exact version, such as `hematic/dnd-collection-tracker:1.1.9`, to control when you upgrade. |
| `DND_PORT` | `8765` | Host port your proxy connects to. |
| `PUID`, `PGID` | `1000` | User and group the containers run as. Set them to the owner of `DND_DATA_DIR` (run `id` on the host). |
| `DND_TRACKER_CPU_SHARES` | `1024` | Relative CPU priority of the web app. This is a weight, not a cap. |
| `DND_OCR_CPU_SHARES` | `1024` | Relative CPU priority of the OCR worker. Lower it, for example to `256`, if indexing slows other services on the host. |

## Local-only setup (`compose.local.yml`)

[`compose.local.yml`](../compose.local.yml) has no login and needs no settings. These are optional:

| Variable | Default | What it does |
|---|---|---|
| `DND_LOCAL_PDF_DIR` | `./pdfs` | Host folder with your PDF library, mounted read-only at `/pdfs`. |
| `DND_LOCAL_PORT` | `8765` | Port on `127.0.0.1` where the app is published. |
| `DND_TRACKER_IMAGE` | `hematic/dnd-collection-tracker:latest` | Image for both services. |

## App settings

The app itself reads these. The Compose files set the first two for you. Set them yourself only when running the app without Docker or with your own Compose file.

| Variable | Default | What it does |
|---|---|---|
| `DND_TRACKER_DATA` | `./data` in a source checkout, `/data` in the image | Folder holding `tracker.db` and `covers/`. |
| `DND_TRACKER_PDF_ROOT` | *(unset)* | Folder the **Browse PDF library** picker shows. Links made with the picker are stored relative to it, so you can move the library without relinking. Unset hides the picker. |
| `DND_TRACKER_ADMINS` | *(unset)* | As above. Unset means everyone can edit, which suits a local install. |
| `DND_TRACKER_TRUSTED_PROXIES` | *(unset)* | As above. Unset means any client is accepted. |
| `DND_TRACKER_PDF_MAP` | *(unset)* | As above. |
| `DND_TRACKER_DB` | `tracker.db` in the data folder | Database file path. Mainly for testing. |

The local launcher (`python -m app`, or `run.bat` on Windows) also takes `--port` (default `8000`) and `--no-browser`.

### `DND_TRACKER_PDF_MAP`

Use this when a database from an older install stores PDF paths that don't exist inside the container, such as a Windows or NAS path. Each entry is `stored prefix=path in the container`; separate entries with `;`.

```sh
DND_TRACKER_PDF_MAP='\\nas\Books=/pdfs'
DND_TRACKER_PDF_MAP='\\nas\Books=/pdfs;D:\More Books=/pdfs/more'
```

Matching ignores case and treats `\` and `/` the same, and the longest matching prefix wins. The database keeps the original paths, so the same database still works on the old machine. Use single quotes in a `.env` file so the backslashes are kept.
