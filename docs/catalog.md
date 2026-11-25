# The catalog

← [Back to the README](../README.md)

## Extending the catalog

The catalog covers the core rules, sourcebooks, setting books, adventures and
accessories across editions, but it is not every product ever published.
Add personal or missing books with the in-app form, or add factual entries
to [`data/catalog.json`](../data/catalog.json) in this format (`releases` is optional):

```json
{"id": "2e-my-book", "title": "My Book", "edition": "AD&D 2e", "type": "Sourcebook",
 "year": 1994, "code": "2150", "setting": "Forgotten Realms",
 "releases": [
   {"key": "orig", "kind": "Original", "primary": true, "label": "First printing"},
   {"key": "2013", "kind": "Premium Reprint", "year": 2013}
 ]}
```

Valid editions, types and release kinds are listed in [`app/db.py`](../app/db.py).

## How catalog updates treat your data

| Path | What |
|---|---|
| `data/catalog.json` | Shared catalog and fresh seed: 1,008 top-level books/sets, 40 child books, 1,048 total works / 1,115 releases, across OD&D to 5e 2024 and edition-independent companions. Factual metadata only; no PDFs, covers or personal ownership data are included. |
| `data/tracker.db` | Your data: PDF links, owned flags, covers, notes, books you added, and saved catalog compatibility/history records. Back this up. |
| `data/covers/` | Rendered/uploaded cover images. |

The catalog is loaded every time the app starts. Re-seeding updates catalog facts but **never** overwrites your PDF links, covers, owned flags or notes. If you edit a catalog book in the app, it becomes yours and the seed leaves it alone from then on. PDF page text and the full-text search index are also stored in `tracker.db`; the database may grow as PDFs are indexed.

On a brand-new install, the app fills your collection with the full catalog the first time it starts. It only adds books and releases. It never marks anything as owned or links any PDFs for you.

On an existing collection, updates are careful not to undo your choices. Books you've edited stay as you left them, and anything you deleted stays deleted.

Deleting a catalog book or release is permanent in your database: restarting or updating the app does not bring it back. Deleting a box set keeps its contained books as separate entries. Your shelf-default release choice also survives catalog updates without preventing other unedited catalog facts from being refreshed. These preferences are stored in `tracker.db` and included in its backups.

## Applying the catalog setting updates

Change lists: [1.1.6 (since 1.1.5)](./catalog-setting-changes-1.1.6.csv) · [1.1.5 (since 1.1.4)](./catalog-setting-changes-1.1.5.csv) · [1.1.4 (since 1.1.3)](./catalog-setting-changes-1.1.4.csv).

[Back up your collection](backup.md), then upgrade and restart the app. It fills in the new settings on eligible catalog entries automatically; no CSV import or database commands are needed. Your ownership, PDF links, covers, and notes are kept.

Each change list includes the catalog work ID, title, edition, and old and new settings (a blank old setting means unassigned). Books you edited locally or that are mapped to a local record still get a setting when theirs is blank, but a setting you chose yourself is never replaced. Custom entries are left alone. To apply a change to one of those books, find it by title and edition, open **Edit book**, and update **Setting**. Deleted entries are not restored, and entries held back by the existing catalog reconciliation rules are not added by this update.

The review uses the published setting or a named framing location, such as Waterdeep's Yawning Portal. **Setting Agnostic** identifies books designed for use without a specific campaign setting, such as general rulebooks and reference books. Use **No setting set** for entries that still lack an assignment; it does not mean they are setting agnostic. References include [TSR Archive](https://www.tsrarchive.com/), the [Mystara product index](https://www.pandius.com/prodlist.html), the [Great Library of Greyhawk](https://greyhawkonline.com/greyhawkwiki/Category:Adventures), and the [4e published adventure index](https://dnd4.fandom.com/wiki/List_of_Published_Adventures).
