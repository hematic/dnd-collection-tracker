"""Idempotent import of data/catalog.json into SQLite.

Catalog format (compact on purpose so it is easy to hand-edit):

    {"works": [
       {"id": "1e-phb", "title": "Players Handbook", "edition": "AD&D 1e",
        "type": "Core Rulebook", "year": 1978, "code": "2010", "setting": null,
        "releases": [                                  # optional
           {"key": "orig", "kind": "Original", "label": "...", "year": 1978,
            "code": "2010", "isbn": "...", "publisher": "TSR", "primary": true},
           {"key": "2012", "kind": "Premium Reprint", "year": 2012}
        ]}
    ]}

A boxed set may list the books inside it:

        "contents": [{"title": "Sigil and the Outlands", "type": "Campaign Setting"}, ...]

Each becomes its own work (id "<box id>--<slug>", parent_id = the box) with the
box's edition/year/setting unless overridden, so it can have its own PDF/cover.

If "releases" is omitted a single Original release is created from the work's
year/code. Release ids are "<work id>--<key>". Re-running the seed updates
catalog fields only; user fields (PDF path, cover, owned flags, notes) are kept.
Deleted entries and explicitly chosen shelf defaults are also preserved.
An empty collection with no deletion or approval history receives the full catalog.
On subsequent imports, entries marked requires_reconciliation reuse approved
mappings but do not create unapproved books or releases. Releases may also be
gated individually. preserve_existing_bibliography prevents updates to existing
work/release rows while still allowing permitted inserts on fresh collections.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import db

CATALOG = db.CATALOG_PATH


def _default_publisher(year: int | None) -> str:
    if year is None:
        return ""
    return "TSR" if year <= 1997 else "Wizards of the Coast"


def _expand(work: dict) -> list[dict]:
    rels = work.get("releases") or [{"key": "orig", "kind": "Original", "primary": True}]
    if not any(r.get("primary") for r in rels):
        rels[0]["primary"] = True
    out = []
    for i, r in enumerate(rels):
        year = r.get("year", work.get("year"))
        out.append(
            {
                "id": f"{work['id']}--{r.get('key') or i}",
                "work_id": work["id"],
                "release_kind": r.get("kind", "Original"),
                "label": r.get("label"),
                "year": year,
                "publisher": r.get("publisher") or work.get("publisher") or _default_publisher(year),
                "product_code": r.get("code", work.get("code") if r.get("kind", "Original") == "Original" else None),
                "isbn": r.get("isbn"),
                "is_primary": 1 if r.get("primary") else 0,
                **({"requires_reconciliation": True} if r.get("requires_reconciliation") else {}),
            }
        )
    return out


def _flatten(works: list[dict]) -> list[dict]:
    out = []
    for w in works:
        out.append(w)
        for c in w.get("contents") or []:
            key = c.get("key") or re.sub(r"[^a-z0-9]+", "-", c["title"].lower()).strip("-")
            out.append({
                "id": f"{w['id']}--{key}",
                "title": c["title"],
                "edition": c.get("edition", w["edition"]),
                "type": c.get("type", "Sourcebook"),
                "year": c.get("year", w.get("year")),
                "code": c.get("code"),
                "setting": c.get("setting", w.get("setting")),
                "publisher": c.get("publisher", w.get("publisher")),
                "parent_id": w["id"],
                "requires_reconciliation": w.get("requires_reconciliation", False),
                "preserve_existing_bibliography": c.get("preserve_existing_bibliography", False),
            })
    return out


def seed(path: Path | None = None) -> tuple[int, int]:
    path = CATALOG if path is None else path
    if not path.exists():
        return 0, 0
    data = json.loads(path.read_text(encoding="utf-8"))
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        fresh = not any(conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in (
            "work", "release", "catalog_deletion", "catalog_work_mapping",
            "catalog_release_mapping", "catalog_metadata_repair", "catalog_copy_repair", "catalog_work_redirect",
        ))
        return seed_catalog(conn, data["works"], fresh_installation=fresh)


def seed_catalog(conn: sqlite3.Connection, catalog_works: list[dict], *,
                 fresh_installation: bool = False) -> tuple[int, int]:
    """Seed within the caller's transaction, resolving approved local identities."""
    works = _flatten(catalog_works)
    n_work, n_rel = 0, 0
    work_mappings = dict(conn.execute("SELECT catalog_id, local_id FROM catalog_work_mapping"))
    release_mappings = dict(conn.execute("SELECT catalog_id, local_id FROM catalog_release_mapping"))
    deleted = {"work": set(), "release": set()}
    for row in conn.execute("SELECT entity_type, entity_id FROM catalog_deletion"):
        deleted[row["entity_type"]].add(row["entity_id"])
    primary_overrides = {
        row["id"] for row in conn.execute(
            "SELECT id FROM work WHERE primary_release_override = 1"
        )
    }
    for w in works:
        local_id = work_mappings.get(w["id"], w["id"])
        if w["id"] in deleted["work"] or local_id in deleted["work"]:
            continue
        existing = conn.execute("SELECT id FROM work WHERE id = ?", (local_id,)).fetchone()
        if (w.get("requires_reconciliation") and not fresh_installation
                and w["id"] not in work_mappings and not existing):
            continue
        if w["id"] in work_mappings:
            if not existing:
                raise ValueError("Mapped local work no longer exists")
            if local_id != w["id"] and conn.execute("SELECT 1 FROM work WHERE id = ?", (w["id"],)).fetchone():
                raise ValueError("Both canonical and mapped local work exist; manual review required")
        else:
            parent_id = w.get("parent_id")
            local_parent = work_mappings.get(parent_id, parent_id)
            if parent_id in deleted["work"] or local_parent in deleted["work"]:
                local_parent = None
            conn.execute(
                """INSERT INTO work (id, title, edition, book_type, first_year, setting, parent_id, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'catalog')
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title, edition=excluded.edition,
                     book_type=excluded.book_type, first_year=excluded.first_year,
                     setting=excluded.setting, parent_id=excluded.parent_id
                   WHERE work.source = 'catalog' AND NOT ?""",
                (local_id, w["title"], w["edition"], w["type"], w.get("year"), w.get("setting"), local_parent,
                 bool(w.get("preserve_existing_bibliography"))),
            )
        n_work += 1
        for r in _expand(w):
            canonical_release = r["id"]
            r["id"] = release_mappings.get(canonical_release, canonical_release)
            r["work_id"] = local_id
            if canonical_release in deleted["release"] or r["id"] in deleted["release"]:
                continue
            if ((w.get("requires_reconciliation") or r.get("requires_reconciliation")) and not fresh_installation
                    and canonical_release not in release_mappings
                    and not conn.execute("SELECT 1 FROM release WHERE id = ?", (canonical_release,)).fetchone()):
                continue
            if canonical_release in release_mappings:
                existing_release = conn.execute("SELECT work_id FROM release WHERE id = ?", (r["id"],)).fetchone()
                if not existing_release or existing_release["work_id"] != local_id:
                    raise ValueError("Mapped release belongs to a different or missing local work")
                if r["id"] != canonical_release and conn.execute(
                    "SELECT 1 FROM release WHERE id = ?", (canonical_release,)
                ).fetchone():
                    raise ValueError("Both canonical and mapped local release exist; manual review required")
            else:
                r["preserve_primary"] = local_id in primary_overrides or w["id"] in work_mappings
                r["preserve_bibliography"] = bool(w.get("preserve_existing_bibliography"))
                if r["preserve_primary"]:
                    r["is_primary"] = 0
                conn.execute(
                    """INSERT INTO release (id, work_id, release_kind, label, year, publisher,
                                            product_code, isbn, is_primary, source)
                       VALUES (:id, :work_id, :release_kind, :label, :year, :publisher,
                               :product_code, :isbn, :is_primary, 'catalog')
                       ON CONFLICT(id) DO UPDATE SET
                         release_kind=excluded.release_kind, label=excluded.label,
                         year=excluded.year, publisher=excluded.publisher,
                         product_code=excluded.product_code, isbn=excluded.isbn,
                         is_primary=CASE WHEN :preserve_primary THEN release.is_primary
                                         ELSE excluded.is_primary END
                       WHERE release.source = 'catalog' AND NOT :preserve_bibliography""",
                    r,
                )
            n_rel += 1
    return n_work, n_rel


if __name__ == "__main__":
    db.init_db()
    w, r = seed()
    print(f"Seeded {w} works / {r} releases")
