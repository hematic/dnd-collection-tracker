"""SQLite access, enums, and the filter/sort query used by the bookshelf."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"  # ships with the code
# Your data (database + covers). Override with DND_TRACKER_DATA, e.g. /data in Docker.
DATA_DIR = Path(os.environ.get("DND_TRACKER_DATA") or ROOT / "data")
DB_PATH = Path(os.environ.get("DND_TRACKER_DB") or DATA_DIR / "tracker.db")  # env override for testing
COVERS_DIR = DATA_DIR / "covers"
SCHEMA = Path(__file__).with_name("schema.sql")

# Order matters: it is the shelf order and the "edition" sort order.
EDITIONS = [
    "OD&D",
    "Basic",
    "AD&D 1e",
    "AD&D 2e",
    "3.0",
    "3.5",
    "4e",
    "5e (2014)",
    "5e (2024)",
    "D&D Companions",
    "Other",
]

BOOK_TYPES = [
    "Core Rulebook",
    "Sourcebook",
    "Monster Book",
    "Adventure",
    "Campaign Setting",
    "Supplement",
    "Boxed Set",
    "Third Party",
    "Other",
]

RELEASE_KINDS = [
    "Original",
    "Revised",
    "Reprint",
    "Premium Reprint",
    "Special Edition",
    "Alternate Cover",
    "Digital",
    "Compilation",
]

USER_FIELDS = ("pdf_path", "cover_path", "cover_source", "owned_physical", "owned_pdf", "notes")


@contextmanager
def connect(*, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Commit or roll back the transaction, then close the connection on every exit."""
    if read_only:
        conn = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        # Migrations for databases created by earlier versions.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(work)")}
        if "parent_id" not in cols:
            conn.execute("ALTER TABLE work ADD COLUMN parent_id TEXT REFERENCES work(id) ON DELETE SET NULL")
        if "primary_release_override" not in cols:
            conn.execute("ALTER TABLE work ADD COLUMN primary_release_override INTEGER NOT NULL DEFAULT 0")
            # Older versions marked the chosen release as user-owned, but not its siblings.
            conn.execute(
                "UPDATE work SET primary_release_override = 1 WHERE id IN ("
                "SELECT work_id FROM release WHERE source = 'user' AND is_primary = 1 "
                "GROUP BY work_id HAVING COUNT(*) = 1)"
            )
            conn.execute(
                "UPDATE release SET is_primary = 0 WHERE source = 'catalog' AND work_id IN ("
                "SELECT id FROM work WHERE primary_release_override = 1)"
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_work_parent ON work(parent_id)")
        pdf_index_cols = {r["name"] for r in conn.execute("PRAGMA table_info(pdf_index)")}
        if "ocr_pages" not in pdf_index_cols:
            conn.execute("ALTER TABLE pdf_index ADD COLUMN ocr_pages INTEGER")
        if "force_reindex" not in pdf_index_cols:
            conn.execute("ALTER TABLE pdf_index ADD COLUMN force_reindex INTEGER NOT NULL DEFAULT 0")


def set_primary_release(
    conn: sqlite3.Connection, work_id: str, release_id: str, *, is_primary: bool = True
) -> None:
    if is_primary:
        conn.execute(
            "UPDATE release SET is_primary = (id = ?) WHERE work_id = ?",
            (release_id, work_id),
        )
    else:
        conn.execute(
            "UPDATE release SET is_primary = 0 WHERE id = ? AND work_id = ?",
            (release_id, work_id),
        )
    conn.execute("UPDATE work SET primary_release_override = 1 WHERE id = ?", (work_id,))


# ---------------------------------------------------------------- listing

def _edition_rank(ed: str) -> int:
    try:
        return EDITIONS.index(ed)
    except ValueError:
        return len(EDITIONS)


def _type_rank(t: str) -> int:
    try:
        return BOOK_TYPES.index(t)
    except ValueError:
        return len(BOOK_TYPES)


def list_books(
    *,
    editions: list[str] | None = None,
    types: list[str] | None = None,
    publishers: list[str] | None = None,
    settings: list[str] | None = None,
    kinds: list[str] | None = None,
    hide_kinds: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    owned: bool = False,
    not_physically_owned: bool = False,
    has_pdf: bool = False,
    no_pdf: bool = False,
    q: str | None = None,
    sort: str = "year",
    desc: bool = False,
    all_releases: bool = False,
    show_contents: bool = False,
) -> list[dict]:
    """Return one row per shelf item (a release joined with its work).

    Filters apply to releases. When ``all_releases`` is false, each work is
    shown once, using its primary release if it matches the filters, else the
    earliest matching release.

    Books that ship inside a box set (``parent_id``) are hidden when their box
    is also in the results, unless ``show_contents`` is set or a text search is
    active.

    ``no_pdf`` checks every release of a book in the grouped view, or only
    the individual release when ``all_releases`` is true.
    """
    where: list[str] = []
    params: list = []

    def in_clause(col: str, values: list[str], negate: bool = False) -> None:
        marks = ",".join("?" * len(values))
        where.append(f"{col} {'NOT IN' if negate else 'IN'} ({marks})")
        params.extend(values)

    if editions:
        in_clause("w.edition", editions)
    if types:
        in_clause("w.book_type", types)
    if publishers:
        in_clause("TRIM(COALESCE(r.publisher, ''))", publishers)
    if settings:
        in_clause("TRIM(COALESCE(w.setting, ''))", settings)
    where.append("w.book_type != 'DM Screen/Kit'")
    if kinds:
        in_clause("r.release_kind", kinds)
    if hide_kinds:
        in_clause("r.release_kind", hide_kinds, negate=True)
    if year_min is not None:
        where.append("COALESCE(r.year, w.first_year) >= ?")
        params.append(year_min)
    if year_max is not None:
        where.append("COALESCE(r.year, w.first_year) <= ?")
        params.append(year_max)
    if owned:
        where.append(
            "(r.owned_physical = 1 OR EXISTS (SELECT 1 FROM release box_physical "
            "WHERE box_physical.work_id = w.parent_id AND box_physical.owned_physical = 1))"
        )
    if not_physically_owned:
        where.append(
            "NOT EXISTS (SELECT 1 FROM release physical "
            "WHERE physical.work_id = w.id AND physical.owned_physical = 1) "
            "AND NOT EXISTS (SELECT 1 FROM release box_physical "
            "WHERE box_physical.work_id = w.parent_id AND box_physical.owned_physical = 1)"
        )
    if has_pdf:
        where.append("r.pdf_path IS NOT NULL")
    if no_pdf:
        if all_releases:
            where.append("r.pdf_path IS NULL")
        else:
            where.append(
                "NOT EXISTS (SELECT 1 FROM release linked "
                "WHERE linked.work_id = w.id AND linked.pdf_path IS NOT NULL)"
            )
    if q:
        like = f"%{q.strip()}%"
        where.append(
            "(w.title LIKE ? OR r.product_code LIKE ? OR r.label LIKE ? "
            "OR w.setting LIKE ? OR r.isbn LIKE ? OR r.publisher LIKE ? "
            "OR w.id IN (SELECT c.parent_id FROM work c WHERE c.title LIKE ?))"
        )
        params.extend([like] * 7)

    sql = f"""
        SELECT r.*, w.title, w.edition, w.book_type, w.first_year, w.setting, w.parent_id,
               (SELECT p.title FROM work p WHERE p.id = w.parent_id) AS parent_title,
               (SELECT COUNT(*) FROM work c WHERE c.parent_id = w.id) AS content_count,
               (SELECT MAX(r3.owned_physical) FROM release r3 WHERE r3.work_id = w.parent_id) AS parent_physical,
               (SELECT COUNT(*) FROM release r4 JOIN work c ON c.id = r4.work_id
                  WHERE c.parent_id = w.id AND (r4.pdf_path IS NOT NULL OR r4.owned_pdf = 1)) AS contents_pdf,
               (SELECT COUNT(*) FROM release r2 WHERE r2.work_id = w.id) AS release_count,
               (SELECT MAX(owned_physical) FROM release r2 WHERE r2.work_id = w.id) AS any_physical,
               (SELECT MAX(owned_pdf) FROM release r2 WHERE r2.work_id = w.id) AS any_owned_pdf,
               (SELECT r2.id FROM release r2 WHERE r2.work_id = w.id AND r2.pdf_path IS NOT NULL
                  ORDER BY r2.is_primary DESC, r2.year LIMIT 1) AS any_pdf_release
        FROM release r JOIN work w ON w.id = r.work_id
        {"WHERE " + " AND ".join(where) if where else ""}
    """
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, params)]

    if not show_contents and not q:
        # A book inside a box set is represented by its box -- but only when the
        # box itself matches the filters. If a filter (e.g. book type "Third Party")
        # matches the book but not its box, the book shows on its own.
        shown = {r["work_id"] for r in rows}
        rows = [r for r in rows if r["parent_id"] not in shown]

    for r in rows:
        r["display_year"] = r["year"] if r["year"] is not None else r["first_year"]
        r["has_pdf"] = r["pdf_path"] is not None
        r.pop("pdf_path", None)  # never expose filesystem paths in list output

    if not all_releases:
        # Pick the shelf face: a release you own, then one with a cover image,
        # then the catalog's primary release, then the earliest.
        def face_key(r: dict) -> tuple:
            owned = r["owned_physical"] or r["owned_pdf"] or r["has_pdf"]
            return (
                0 if owned else 1,
                0 if r["cover_path"] else 1,
                0 if r["is_primary"] else 1,
                r["display_year"] or 9999,
            )

        best: dict[str, dict] = {}
        for r in rows:
            cur = best.get(r["work_id"])
            if cur is None or face_key(r) < face_key(cur):
                best[r["work_id"]] = r
        rows = list(best.values())

    # Ownership badges / click target. One-per-book view summarises every
    # release of the work; the all-releases view is per release.
    for r in rows:
        if all_releases:
            r["own_hc"] = bool(r["owned_physical"])
            r["own_pdf"] = bool(r["has_pdf"] or r["owned_pdf"])
            r["pdf_release_id"] = r["id"] if r["has_pdf"] else None
        else:
            r["own_hc"] = bool(r["any_physical"])
            r["own_pdf"] = bool(r["any_pdf_release"] or r["any_owned_pdf"])
            r["pdf_release_id"] = r["id"] if r["has_pdf"] else r["any_pdf_release"]
        # Owning the box set means owning the books inside it; a box set counts
        # as "PDF" when any of its books has one.
        r["own_hc"] = r["own_hc"] or bool(r["parent_physical"])
        r["own_pdf"] = r["own_pdf"] or bool(r["contents_pdf"])
        for k in ("any_physical", "any_owned_pdf", "any_pdf_release", "parent_physical", "contents_pdf"):
            r.pop(k, None)

    def title_key(r: dict) -> str:
        t = r["title"].lower()
        for article in ("the ", "a ", "an "):
            if t.startswith(article):
                return t[len(article):]
        return t

    # Primary sort key honours the direction; ties always fall back to title A→Z
    # (stable two-pass sort).
    year = lambda r: r["display_year"] or 0
    keys = {
        "year": lambda r: (year(r), -_edition_rank(r["edition"]) if desc else _edition_rank(r["edition"])),
        "title": title_key,
        "edition": lambda r: (_edition_rank(r["edition"]), year(r)),
        "type": lambda r: (_type_rank(r["book_type"]), year(r)),
        "code": lambda r: (r["product_code"] or "~").lower(),
        "publisher": lambda r: (r["publisher"] or "").strip().lower() or "~",
    }
    rows.sort(key=title_key)
    rows.sort(key=keys.get(sort, keys["year"]), reverse=desc)
    return rows


def publisher_names() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT TRIM(publisher) AS publisher FROM release "
            "WHERE TRIM(COALESCE(publisher, '')) != '' "
            "ORDER BY publisher COLLATE NOCASE"
        ).fetchall()
    return [row["publisher"] for row in rows]


def setting_names() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT TRIM(setting) AS setting FROM work "
            "WHERE TRIM(COALESCE(setting, '')) != '' "
            "ORDER BY setting COLLATE NOCASE"
        ).fetchall()
    return [row["setting"] for row in rows]


def year_bounds() -> tuple[int | None, int | None]:
    with connect() as conn:
        row = conn.execute(
            "SELECT MIN(COALESCE(r.year, w.first_year)), MAX(COALESCE(r.year, w.first_year)) "
            "FROM release r JOIN work w ON w.id = r.work_id"
        ).fetchone()
    return row[0], row[1]


def export_books(*, edition: str | None = None, physical_owned: bool | None = None) -> list[dict]:
    """Return one inventory row per book, including books inside boxed sets."""
    where = ["w.book_type != 'DM Screen/Kit'"]
    params: list = []
    if edition:
        where.append("w.edition = ?")
        params.append(edition)

    sql = f"""
        WITH ranked_releases AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY r.work_id
                       ORDER BY r.is_primary DESC, r.year IS NULL, r.year, r.id
                   ) AS release_rank,
                   MAX(r.owned_physical) OVER (PARTITION BY r.work_id) AS work_physical
            FROM release r
        ),
        box_ownership AS (
            SELECT work_id, MAX(owned_physical) AS physically_owned
            FROM release
            GROUP BY work_id
        ),
        inventory AS (
            SELECT w.id, w.title, w.edition, w.book_type, w.first_year, w.setting,
                   parent.title AS parent_title,
                   release.year AS release_year, release.release_kind,
                   release.publisher, release.product_code, release.isbn,
                   (COALESCE(release.work_physical, 0) OR
                    COALESCE(box.physically_owned, 0)) AS physically_owned
            FROM work w
            LEFT JOIN work parent ON parent.id = w.parent_id
            LEFT JOIN ranked_releases release
                   ON release.work_id = w.id AND release.release_rank = 1
            LEFT JOIN box_ownership box ON box.work_id = w.parent_id
            WHERE {" AND ".join(where)}
        )
        SELECT * FROM inventory
        {"WHERE physically_owned = ?" if physical_owned is not None else ""}
        ORDER BY edition, title COLLATE NOCASE
    """
    if physical_owned is not None:
        params.append(int(physical_owned))
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params)]
