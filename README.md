# D&D Collection Tracker

**A bookshelf for your Dungeons & Dragons collection.** Browse by edition, track the specific printings you own, and open your own PDFs directly from the shelf.

Start with a built-in catalog of **1,048 books and sets across 1,115 releases**, from original D&D through the 2024 rules, plus edition-independent companions. Run it on your own computer or host it for a group. The catalog ships with bibliographic metadata, not PDFs or cover art.

[See it in action](#see-it-in-action) · [Quick start](#quick-start) · [Using your collection](#using-your-collection) · [Self-hosting](#self-host-with-docker) · [Release notes](./CHANGELOG.md)

## See it in action

![Fresh install showing the AD&D 2e shelf, catalog filters, and color-coded placeholder covers](./docs/media/fresh-shelves.png)

*A fresh install: pick an edition and start browsing, even before you've linked a single PDF.*

## Quick start

**Windows:** Install Python 3.10 or later and double-click [`run.bat`](./run.bat). It creates a virtual environment, installs dependencies, and opens [http://127.0.0.1:8000](http://127.0.0.1:8000). Use `run.bat --port 8080` if port 8000 is in use.

**macOS or Linux:** From a checkout of this repository, run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app
```

The local launcher listens on your own machine only. Use the [Docker setup](#self-host-with-docker) for shared access and PDF indexing.

## Using your collection

| What you want to do | Where to start |
|---|---|
| Browse and compare books | Pick **Shelves**, **Grid**, or **Table**. Search by title, code, ISBN, setting, or publisher. Combine edition, type, year, ownership and PDF filters; bookmark the URL to keep the view. |
| Track a specific printing | Click a book title or table row. Set **Own print copy** and **Own PDF** per release, and choose which printing is the **shelf default**. Use **Show every release separately** to compare variants side by side. |
| Open a PDF from the shelf | In the release drawer, choose **Browse PDF library** and select a file. If no library folder is configured, paste the full path instead. The first page becomes the cover unless you upload your own image. Click the cover to open the PDF or the title to return to the drawer. |
| Organize books not in the catalog | Use **Add book** for missing titles, **New box set** to group books, or **Select** to make changes across several entries. |
| Take an inventory with you | Under **Export**, download the **Current filtered view** or a full, physically owned, or not-physically-owned CSV. |

### Search inside your PDFs

In the Docker setup, open **PDF Search** and choose **Start indexing** as an editor. The worker indexes embedded text and uses local OCR for scanned pages. Search for all words, any word, or an exact phrase, optionally filter by edition, and open a result at the matching page.

Indexing only starts when requested. Editors can pause, resume, re-index, or retry failures. Readers can use the completed index. Text stays in your database, and the source PDFs are never modified.

Use the **?** buttons in the app for contextual help, version information, and release notes.

For a local installation, set `DND_TRACKER_PDF_ROOT` to an absolute folder path before launching the app to enable the picker. Docker configures it automatically. Files are not uploaded or copied: picker links are relative to the library folder, so you can move the library without relinking if you keep its folder structure.

## Data

| Path | What |
|---|---|
| `data/catalog.json` | Shared catalog and fresh seed: 1,008 top-level books/sets, 40 child books, 1,048 total works / 1,115 releases, across OD&D to 5e 2024 and edition-independent companions. Factual metadata only; no PDFs, covers or personal ownership data are included. |
| `data/tracker.db` | Your data: PDF links, owned flags, covers, notes, books you added, and saved catalog compatibility/history records. Back this up. |
| `data/covers/` | Rendered/uploaded cover images. |

The catalog is loaded every time the app starts. Re-seeding updates catalog facts but **never** overwrites your PDF links, covers, owned flags or notes. If you edit a catalog book in the app, it becomes yours and the seed leaves it alone from then on. PDF page text and the full-text search index are also stored in `tracker.db`; the database may grow as PDFs are indexed.

The first seed into an empty collection with no work, release, deletion,
mapping, repair or redirect history creates the complete bundled catalog in
one transaction. The emptiness check and seed share a write reservation.
No ownership, file links, mapping approvals or repair audits are invented.
Existing collections retain their creation gates: previously gated additions
and new gated releases are not silently added on restart. Previously saved
catalog-to-local mappings continue to reuse your stable local IDs without
rewriting mapped bibliography. Catalog entries marked
`preserve_existing_bibliography` also keep their existing work/release fields
and shelf defaults.

Deleting a catalog book or release is permanent in your database: restarting or updating the app does not bring it back. Deleting a box set keeps its contained books as separate entries. Your shelf-default release choice also survives catalog updates without preventing other unedited catalog facts from being refreshed. These preferences are stored in `tracker.db` and included in its backups. Deletions made before this behavior was added cannot be recovered automatically; delete any previously restored entries again.

## Extending the catalog

The catalog covers the core rules, sourcebooks, setting books, adventures and
accessories across editions, but it is not every product ever published.
Add personal or missing books with the in-app form, or add factual entries
to `catalog.json` in this format (`releases` is optional):

```json
{"id": "2e-my-book", "title": "My Book", "edition": "AD&D 2e", "type": "Sourcebook",
 "year": 1994, "code": "2150", "setting": "Forgotten Realms",
 "releases": [
   {"key": "orig", "kind": "Original", "primary": true, "label": "First printing"},
   {"key": "2013", "kind": "Premium Reprint", "year": 2013}
 ]}
```

Valid editions, types and release kinds are listed in `app/db.py`.

## Self-host with Docker

Everything lives in two places, and neither is in git:

| What | Local (Windows) | Server |
|---|---|---|
| Database + covers | `data/tracker.db`, `data/covers/` | `DND_DATA_DIR` on the server (mounted at `/data`) |
| PDFs | Your local library or network share | `DND_PDF_DIR` on the host (default `/mnt/dnd/Books`), mounted read-only at `/pdfs` |

The supplied [Compose stack](./docker-compose.yml) assumes Traefik and TinyAuth. It starts the web app and a separate OCR worker. Both containers need the same library at `/pdfs`; keep the SQLite database on the host's local disk, not a network share.

1. Copy [`.env.example`](./.env.example) to `.env`. Set the host storage paths, editor usernames or emails, and `TRAEFIK_IP`. In Komodo, put those values in the Stack environment and enable **Run Build**.
2. Route Traefik to `DND_PORT` (default `8765`). Configure forward-auth to strip incoming identity headers and pass TinyAuth's authenticated headers. For Docker labels, the response-header setting is:
   ```
   traefik.http.middlewares.tinyauth.forwardauth.authResponseHeaders: Remote-User,Remote-Email,Remote-Name,Remote-Groups
   ```
3. If moving an existing collection, stop the local app and copy its database and covers to `DND_DATA_DIR`. Give `PUID:PGID` write access. If existing links use a Windows or NAS path, set `DND_TRACKER_PDF_MAP` in your `.env` or Komodo environment (for example, `\\nas\Books=/pdfs`). Compose passes it to both services; the database keeps the original paths. New Docker installs can leave the mapping blank and use **Browse PDF library** to pick files from `DND_PDF_DIR`.
4. Deploy the stack, or run `docker compose up -d --build`.

Anyone TinyAuth lets in can browse and open linked PDFs. Only `DND_TRACKER_ADMINS` can edit. Restrict direct access to the published port so clients cannot bypass Traefik.

**Backups:** Use SQLite's `.backup` command (or stop both services before copying the database) and back up the `covers/` folder. Keep the PDF library backed up separately.

**OCR troubleshooting:** If the UI reports **OCR worker offline**, check `docker compose ps` and `docker compose logs -f dnd-tracker-ocr`. `DND_OCR_CPU_SHARES` adjusts its relative CPU priority, not a hard cap.
