"""FastAPI app: JSON API + static UI. Run with `python -m app` (see run.bat)."""
from __future__ import annotations

import csv
import os
import re
import stat
from io import StringIO
from itertools import groupby
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import covers, db, pdf_indexer, seed, settings
from .version import APP_VERSION

STATIC_DIR = db.ROOT / "static"

app = FastAPI(title="D&D Collection Tracker", version=APP_VERSION)


@app.middleware("http")
async def _read_only_guard(request: Request, call_next):
    """Only DND_TRACKER_ADMINS may change anything; everyone else can browse and read PDFs."""
    if not settings.allowed_client(request):
        return JSONResponse({"detail": "Open this app through its public address (behind the login)."}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and not settings.can_edit(request):
        return JSONResponse({"detail": "You have read-only access to this collection."}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    seed.seed()


# ---------------------------------------------------------------- helpers

def _cover_url(name: str | None) -> str | None:
    if not name:
        return None
    p = db.COVERS_DIR / name
    try:
        stat_result = p.stat()
        v = f"{stat_result.st_mtime_ns:x}-{stat_result.st_size:x}"
    except FileNotFoundError:
        v = "0"
    return f"/covers/{name}?v={v}"


def _public_release(r: dict) -> dict:
    r = dict(r)
    r["cover_url"] = _cover_url(r.get("cover_path"))
    r["has_pdf"] = bool(r.get("pdf_path"))
    return r


def _get_release(conn, release_id: str) -> dict:
    row = conn.execute("SELECT * FROM release WHERE id = ?", (release_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Release not found")
    return dict(row)


def _split(v: str | None) -> list[str] | None:
    if not v:
        return None
    return [s for s in v.split("|") if s]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "book"


def _check_enum(value: str | None, allowed: list[str], name: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(422, f"Unknown {name}: {value}")


# ---------------------------------------------------------------- read API

@app.get("/changelog", include_in_schema=False)
def changelog():
    return FileResponse(
        db.ROOT / "CHANGELOG.md",
        media_type="text/plain",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/meta")
def meta(request: Request):
    lo, hi = db.year_bounds()
    return {
        "user": settings.user(request),
        "can_edit": settings.can_edit(request),
        "can_open_external": hasattr(os, "startfile"),
        "pdf_library_enabled": bool(settings.PDF_ROOT),
        "version": APP_VERSION,
        "editions": db.EDITIONS,
        "book_types": db.BOOK_TYPES,
        "publishers": db.publisher_names(),
        "settings": db.setting_names(),
        "release_kinds": db.RELEASE_KINDS,
        "year_min": lo,
        "year_max": hi,
    }


@app.get("/api/books")
def books(
    edition: str | None = None,
    type: str | None = None,
    publisher: list[str] | None = Query(None),
    kinds: str | None = None,
    hide_kinds: str | None = None,
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
    contents: bool = False,
    setting: Annotated[list[str] | None, Query()] = None,
):
    rows = db.list_books(
        editions=_split(edition),
        types=_split(type),
        publishers=publisher,
        settings=setting,
        kinds=_split(kinds),
        hide_kinds=_split(hide_kinds),
        year_min=year_min,
        year_max=year_max,
        owned=owned,
        not_physically_owned=not_physically_owned,
        has_pdf=has_pdf,
        no_pdf=no_pdf,
        q=q,
        sort=sort,
        desc=desc,
        all_releases=all_releases,
        show_contents=contents,
    )
    for r in rows:
        r["cover_url"] = _cover_url(r.get("cover_path"))
    return rows


@app.get("/api/pdf-index")
def pdf_index_status():
    return pdf_indexer.status()


@app.get("/api/pdf-index/books")
def pdf_index_books(
    ocr_only: bool = True,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT r.id AS release_id, w.title, w.edition, r.release_kind, r.label, "
            "COALESCE(i.status, 'not_indexed') AS status, "
            "COALESCE(i.indexed_pages, 0) AS indexed_pages, "
            "COALESCE(i.page_count, 0) AS page_count, i.ocr_pages, i.error "
            "FROM release r JOIN work w ON w.id = r.work_id "
            "LEFT JOIN pdf_index i ON i.release_id = r.id "
            "WHERE r.pdf_path IS NOT NULL AND (? = 0 OR i.ocr_pages > 0) "
            "ORDER BY i.ocr_pages DESC, w.title COLLATE NOCASE, r.release_kind "
            "LIMIT ? OFFSET ?",
            (ocr_only, limit, offset),
        ).fetchall()
    return {"results": [dict(row) for row in rows], "limit": limit, "offset": offset}


@app.post("/api/pdf-index")
def start_pdf_index(mode: str = Query("all", pattern="^(all|reindex|failed|pause|resume)$")):
    if mode == "pause":
        pdf_indexer.pause_worker()
        return {"queued": 0, "mode": mode}
    if mode == "resume":
        queued = pdf_indexer.enqueue_all()
        pdf_indexer.resume_worker()
        return {"queued": queued, "mode": mode}
    if mode == "failed":
        queued = pdf_indexer.retry_failed()
    else:
        queued = pdf_indexer.enqueue_all(force=mode == "reindex")
    pdf_indexer.resume_worker()
    return {"queued": queued, "mode": mode}


@app.post("/api/pdf-index/{release_id}/retry")
def retry_pdf_index(release_id: str):
    with db.connect() as conn:
        release = conn.execute(
            "SELECT pdf_path FROM release WHERE id = ?", (release_id,)
        ).fetchone()
    if release is None or not release["pdf_path"]:
        raise HTTPException(404, "No linked PDF found for this release")
    pdf_indexer.enqueue(release_id, force=True)
    pdf_indexer.resume_worker()
    return {"queued": True, "release_id": release_id}


def _pdf_search_criteria(
    q: str = Query(..., min_length=1, max_length=200),
    match: str = Query("all", pattern="^(all|any|phrase)$"),
    edition: str | None = None,
    editions: Annotated[list[str] | None, Query()] = None,
):
    edition = edition or None
    _check_enum(edition, db.EDITIONS, "edition")
    selected = list(dict.fromkeys(editions or []))
    for item in selected:
        _check_enum(item, db.EDITIONS, "edition")
    terms = re.findall(r"[\w]+", q, flags=re.UNICODE)
    if match == "phrase" and terms:
        match_query = f'"{" ".join(terms)}"*'
    else:
        operator = " AND " if match == "all" else " OR "
        match_query = operator.join(f'"{term}"*' for term in terms)
    return q, match, edition, selected, match_query


PdfSearchCriteria = Annotated[
    tuple[str, str, str | None, list[str], str], Depends(_pdf_search_criteria)
]
PDF_MATCH_COLUMNS = "r.id AS release_id, w.title, w.edition, r.release_kind, r.label, pdf_text_page.page_number"
PDF_MATCH_ORDER = (
    " ORDER BY w.title COLLATE NOCASE, w.id, r.is_primary DESC, r.year, r.id, pdf_text_page.page_number"
)


def _pdf_match_sql(edition: str | None, editions: list[str]) -> str:
    sql = (
        " FROM pdf_text_fts "
        "JOIN pdf_text_page ON pdf_text_page.id = pdf_text_fts.rowid "
        "JOIN pdf_index ON pdf_index.release_id = pdf_text_page.release_id "
        "JOIN release r ON r.id = pdf_text_page.release_id "
        "JOIN work w ON w.id = r.work_id "
        "WHERE pdf_text_fts MATCH ? AND pdf_index.status = 'done' "
        "AND r.pdf_path IS NOT NULL "
    )
    if edition is not None:
        sql += "AND w.edition = ? "
    if editions:
        sql += "AND w.edition IN (" + ", ".join("?" for _ in editions) + ") "
    return sql


@app.get("/api/search/pdf")
def search_pdf_text(
    criteria: PdfSearchCriteria,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    q, match, edition, editions, match_query = criteria
    result = {"query": q, "match": match, "edition": edition, "editions": editions}
    if not match_query:
        return {**result, "total": 0, "results": []}
    sql = _pdf_match_sql(edition, editions)
    params = (match_query, *([edition] if edition else []), *editions)
    with db.connect(read_only=True) as conn:
        conn.execute("BEGIN")
        total = conn.execute("SELECT COUNT(*)" + sql, params).fetchone()[0]
        rows = conn.execute(
            "SELECT " + PDF_MATCH_COLUMNS + ", "
            "snippet(pdf_text_fts, 0, ?, ?, ' … ', 22) AS snippet"
            + sql + PDF_MATCH_ORDER + " LIMIT ? OFFSET ?",
            ("\x1f", "\x1e", *params, limit, offset),
        ).fetchall()
    return {**result, "total": total, "results": [dict(row) for row in rows]}


@app.get("/api/search/pdf.csv")
def export_pdf_search(criteria: PdfSearchCriteria):
    _, _, edition, editions, match_query = criteria
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(["Title", "Edition", "Release kind", "Release label", "Matching PDF pages"])
    if match_query:
        with db.connect(read_only=True) as conn:
            rows = conn.execute(
                "SELECT " + PDF_MATCH_COLUMNS + _pdf_match_sql(edition, editions) + PDF_MATCH_ORDER,
                (match_query, *([edition] if edition else []), *editions),
            )
            for _, matching_pages in groupby(rows, key=lambda row: row["release_id"]):
                first = next(matching_pages)
                pages = [str(first["page_number"]), *(str(row["page_number"]) for row in matching_pages)]
                writer.writerow([
                    *(_csv_cell(first[key]) for key in ("title", "edition", "release_kind", "label")),
                    ", ".join(pages),
                ])
    return _csv_response(output, "dnd-pdf-search.csv")


@app.get("/api/export.csv")
def export_csv(scope: str, edition: str | None = None):
    """Download a book-level inventory CSV, optionally scoped to one edition."""
    if scope not in {"all", "missing", "owned"}:
        raise HTTPException(422, "Unknown export scope")
    if edition is not None and edition not in db.EDITIONS:
        raise HTTPException(422, f"Unknown edition: {edition}")

    physical_owned = {"all": None, "missing": False, "owned": True}[scope]
    rows = db.export_books(edition=edition, physical_owned=physical_owned)
    filename = f"dnd-collection-{scope}{'-' + _slug(edition) if edition else ''}.csv"
    return _inventory_csv(rows, filename)


@app.get("/api/export-view.csv")
def export_view_csv(rows: list[dict] = Depends(books)):
    """Download the same filtered, sorted releases returned by the collection API."""
    inventory = [
        {**row, "release_year": row["year"], "physically_owned": row["own_hc"]}
        for row in rows
    ]
    return _inventory_csv(inventory, "dnd-collection-filtered.csv")


def _inventory_csv(rows: list[dict], filename: str) -> Response:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([
        "Title", "Edition", "Book type", "First published", "Release year",
        "Release kind", "Publisher", "Product code", "ISBN", "Setting",
        "Part of box set", "Physical copy owned",
    ])
    for row in rows:
        values = [
            row["title"], row["edition"], row["book_type"], row["first_year"],
            row["release_year"], row["release_kind"], row["publisher"],
            row["product_code"], row["isbn"], row["setting"], row["parent_title"],
            "Yes" if row["physically_owned"] else "No",
        ]
        writer.writerow([_csv_cell(value) for value in values])

    return _csv_response(output, filename)


def _csv_response(output: StringIO, filename: str) -> Response:
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _csv_cell(value):
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@app.get("/api/works/{work_id}")
def get_work(work_id: str, request: Request):
    out = work_detail(work_id)
    if not settings.can_edit(request):
        for r in out["releases"]:
            r["pdf_path"] = None  # read-only visitors don't need file-server paths
    return out


def work_detail(work_id: str):
    with db.connect() as conn:
        w = conn.execute("SELECT * FROM work WHERE id = ?", (work_id,)).fetchone()
        if w is None:
            redirect = conn.execute("SELECT work_id FROM catalog_work_redirect WHERE old_id=?", (work_id,)).fetchone()
            if redirect:
                work_id = redirect["work_id"]
                w = conn.execute("SELECT * FROM work WHERE id=?", (work_id,)).fetchone()
        if w is None:
            raise HTTPException(404, "Book not found")
        rels = conn.execute(
            "SELECT r.*, i.ocr_pages, i.page_count AS pdf_page_count "
            "FROM release r LEFT JOIN pdf_index i ON i.release_id = r.id "
            "WHERE r.work_id = ? ORDER BY r.is_primary DESC, r.year, r.id",
            (work_id,),
        ).fetchall()
        parent = conn.execute("SELECT id, title FROM work WHERE id = ?", (w["parent_id"],)).fetchone()
        children = conn.execute(
            "SELECT id, title, book_type, first_year FROM work WHERE parent_id = ? ORDER BY title", (work_id,)
        ).fetchall()
        child_releases: dict[str, list[dict]] = {}
        if children:
            for row in conn.execute(
                "SELECT r.* FROM release r JOIN work c ON c.id = r.work_id "
                "WHERE c.parent_id = ? ORDER BY r.is_primary DESC, r.year",
                (work_id,),
            ):
                child_releases.setdefault(row["work_id"], []).append(dict(row))
        kids = []
        for c in children:
            crels = child_releases.get(c["id"], [])
            face = next((r for r in crels if r["cover_path"]), crels[0] if crels else {})
            pdf = next((r for r in crels if r["pdf_path"]), None)
            kids.append({
                **dict(c),
                "cover_url": _cover_url(face.get("cover_path")),
                "pdf_release_id": pdf["id"] if pdf else None,
                "owned_physical": any(r["owned_physical"] for r in crels),
                "owned_pdf": any(r["owned_pdf"] or r["pdf_path"] for r in crels),
            })
    out = dict(w)
    out["releases"] = [_public_release(dict(r)) for r in rels]
    out["parent"] = dict(parent) if parent else None
    out["contents"] = kids
    return out


@app.get("/api/boxsets")
def boxsets():
    """Works that can hold other books (anything not itself inside a set)."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, edition, book_type, first_year FROM work WHERE parent_id IS NULL "
            "ORDER BY (book_type != 'Boxed Set'), title"
        ).fetchall()
    return [dict(r) for r in rows]


def _check_parent(conn, work_id: str | None, parent_id: str | None) -> None:
    if not parent_id:
        return
    if parent_id == work_id:
        raise HTTPException(422, "A book can't be inside itself")
    p = conn.execute("SELECT parent_id FROM work WHERE id = ?", (parent_id,)).fetchone()
    if p is None:
        raise HTTPException(422, "That box set doesn't exist")
    if p["parent_id"]:
        raise HTTPException(422, "Box sets can't be nested inside another book")
    if work_id and conn.execute("SELECT 1 FROM work WHERE parent_id = ?", (work_id,)).fetchone():
        raise HTTPException(422, "This book contains other books, so it can't go inside a set")


# ---------------------------------------------------------------- write API

class WorkIn(BaseModel):
    title: str | None = None
    edition: str | None = None
    book_type: str | None = None
    first_year: int | None = None
    setting: str | None = None
    notes: str | None = None
    parent_id: str | None = None


class ReleaseIn(BaseModel):
    release_kind: str | None = None
    label: str | None = None
    year: int | None = None
    publisher: str | None = None
    product_code: str | None = None
    isbn: str | None = None
    is_primary: bool | None = None
    owned_physical: bool | None = None
    owned_pdf: bool | None = None
    notes: str | None = None


class WorkUpdate(WorkIn):
    release_id: str | None = None
    release: ReleaseIn | None = None


class NewWork(WorkIn):
    title: str
    edition: str
    book_type: str
    release: ReleaseIn | None = None


class PdfIn(BaseModel):
    path: str | None = None
    library_path: str | None = None


@app.post("/api/works", status_code=201)
def create_work(body: NewWork):
    _check_enum(body.edition, db.EDITIONS, "edition")
    _check_enum(body.book_type, db.BOOK_TYPES, "book type")
    rel = body.release or ReleaseIn()
    _check_enum(rel.release_kind, db.RELEASE_KINDS, "release kind")
    with db.connect() as conn:
        _check_parent(conn, None, body.parent_id)
        base = "user-" + _slug(f"{body.edition}-{body.title}")
        wid, n = base, 2
        while conn.execute("SELECT 1 FROM work WHERE id = ?", (wid,)).fetchone():
            wid, n = f"{base}-{n}", n + 1
        conn.execute(
            "INSERT INTO work (id, title, edition, book_type, first_year, setting, notes, parent_id, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user')",
            (wid, body.title.strip(), body.edition, body.book_type, body.first_year, body.setting, body.notes,
             body.parent_id or None),
        )
        conn.execute(
            "INSERT INTO release (id, work_id, release_kind, label, year, publisher, product_code, isbn, "
            "is_primary, owned_physical, owned_pdf, source) VALUES (?,?,?,?,?,?,?,?,1,?,?,'user')",
            (
                f"{wid}--u1", wid, rel.release_kind or "Original", rel.label,
                rel.year if rel.year is not None else body.first_year,
                rel.publisher, rel.product_code, rel.isbn,
                int(bool(rel.owned_physical)), int(bool(rel.owned_pdf)),
            ),
        )
    return work_detail(wid)


@app.patch("/api/works/{work_id}")
def update_work(work_id: str, body: WorkUpdate):
    _check_enum(body.edition, db.EDITIONS, "edition")
    _check_enum(body.book_type, db.BOOK_TYPES, "book type")
    if body.release:
        _check_enum(body.release.release_kind, db.RELEASE_KINDS, "release kind")
    if (body.release_id is None) != (body.release is None):
        raise HTTPException(422, "A release id and release details must be provided together")

    fields = body.model_dump(exclude={"release_id", "release"}, exclude_unset=True)
    if "parent_id" in fields:
        fields["parent_id"] = fields["parent_id"] or None
    release_fields = body.release.model_dump(exclude_unset=True) if body.release else {}
    with db.connect() as conn:
        if fields:
            catalog_fields = {"title", "edition", "book_type", "first_year", "setting", "parent_id"}
            sets = ", ".join(f"{k} = ?" for k in fields)
            # Editing catalog data marks the row as user-owned so a re-seed keeps it.
            extra = ", source = 'user'" if catalog_fields & fields.keys() else ""
            if "parent_id" in fields:
                _check_parent(conn, work_id, fields["parent_id"])
            cur = conn.execute(f"UPDATE work SET {sets}{extra} WHERE id = ?", (*fields.values(), work_id))
            if cur.rowcount == 0:
                raise HTTPException(404, "Book not found")
        elif not conn.execute("SELECT 1 FROM work WHERE id = ?", (work_id,)).fetchone():
            raise HTTPException(404, "Book not found")

        if release_fields:
            release = conn.execute(
                "SELECT * FROM release WHERE id = ? AND work_id = ?",
                (body.release_id, work_id),
            ).fetchone()
            if release is None:
                raise HTTPException(404, "Release not found for this book")
            for key in ("is_primary", "owned_physical", "owned_pdf"):
                if key in release_fields:
                    release_fields[key] = int(bool(release_fields[key]))
            catalog_fields = set(release_fields) - set(db.USER_FIELDS) - {"is_primary"}
            sets = ", ".join(f"{key} = ?" for key in release_fields)
            extra = ", source = 'user'" if catalog_fields else ""
            conn.execute(
                f"UPDATE release SET {sets}{extra} WHERE id = ? AND work_id = ?",
                (*release_fields.values(), body.release_id, work_id),
            )
            if "is_primary" in release_fields:
                db.set_primary_release(
                    conn, work_id, release["id"], is_primary=bool(release_fields["is_primary"])
                )
    return work_detail(work_id)


class BulkRelease(BaseModel):
    publisher: str | None = None
    owned_physical: bool | None = None
    owned_pdf: bool | None = None


class BulkIn(BaseModel):
    work_ids: list[str] = []
    release_ids: list[str] = []      # the shelf releases that were selected (for owned flags etc.)
    work: WorkIn | None = None
    release: BulkRelease | None = None


@app.post("/api/bulk")
def bulk_update(body: BulkIn):
    """Apply the same change to many books at once, all-or-nothing."""
    wf = body.work.model_dump(exclude_unset=True) if body.work else {}
    rf = body.release.model_dump(exclude_unset=True) if body.release else {}
    wf.pop("title", None)  # titles are never bulk-edited
    _check_enum(wf.get("edition"), db.EDITIONS, "edition")
    _check_enum(wf.get("book_type"), db.BOOK_TYPES, "book type")
    if "parent_id" in wf:
        wf["parent_id"] = wf["parent_id"] or None
    for k in ("owned_physical", "owned_pdf"):
        if k in rf:
            rf[k] = int(bool(rf[k]))
    if not wf and not rf:
        raise HTTPException(422, "Nothing to change")
    with db.connect() as conn:
        if wf:
            sets = ", ".join(f"{k} = ?" for k in wf) + ", source = 'user'"
            for wid in body.work_ids:
                if "parent_id" in wf:
                    try:
                        _check_parent(conn, wid, wf["parent_id"])
                    except HTTPException as e:
                        title = conn.execute("SELECT title FROM work WHERE id = ?", (wid,)).fetchone()
                        raise HTTPException(422, f"{title['title'] if title else wid}: {e.detail}")
                conn.execute(f"UPDATE work SET {sets} WHERE id = ?", (*wf.values(), wid))
        if rf:
            extra = ", source = 'user'" if "publisher" in rf else ""
            sets = ", ".join(f"{k} = ?" for k in rf) + extra
            for rid in body.release_ids:
                conn.execute(f"UPDATE release SET {sets} WHERE id = ?", (*rf.values(), rid))
    return {"works": len(body.work_ids) if wf else 0, "releases": len(body.release_ids) if rf else 0}


@app.delete("/api/works/{work_id}", status_code=204)
def delete_work(work_id: str):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO catalog_deletion (entity_type, entity_id) "
            "SELECT 'work', id FROM work WHERE id = ?",
            (work_id,),
        )
        for r in conn.execute("SELECT id FROM release WHERE work_id = ?", (work_id,)).fetchall():
            covers.remove(r["id"])
        conn.execute("DELETE FROM release WHERE work_id = ?", (work_id,))
        conn.execute("UPDATE work SET parent_id = NULL WHERE parent_id = ?", (work_id,))
        conn.execute("DELETE FROM work WHERE id = ?", (work_id,))


@app.post("/api/works/{work_id}/releases", status_code=201)
def create_release(work_id: str, body: ReleaseIn):
    _check_enum(body.release_kind, db.RELEASE_KINDS, "release kind")
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM work WHERE id = ?", (work_id,)).fetchone():
            raise HTTPException(404, "Book not found")
        n = 1
        while conn.execute("SELECT 1 FROM release WHERE id = ?", (f"{work_id}--u{n}",)).fetchone():
            n += 1
        rid = f"{work_id}--u{n}"
        conn.execute(
            "INSERT INTO release (id, work_id, release_kind, label, year, publisher, product_code, isbn, "
            "is_primary, owned_physical, owned_pdf, notes, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'user')",
            (
                rid, work_id, body.release_kind or "Reprint", body.label, body.year, body.publisher,
                body.product_code, body.isbn, int(bool(body.is_primary)),
                int(bool(body.owned_physical)), int(bool(body.owned_pdf)), body.notes,
            ),
        )
        if body.is_primary:
            db.set_primary_release(conn, work_id, rid)
    return work_detail(work_id)


@app.patch("/api/releases/{release_id}")
def update_release(release_id: str, body: ReleaseIn):
    _check_enum(body.release_kind, db.RELEASE_KINDS, "release kind")
    fields = body.model_dump(exclude_unset=True)
    with db.connect() as conn:
        rel = _get_release(conn, release_id)
        if fields:
            for k in ("is_primary", "owned_physical", "owned_pdf"):
                if k in fields:
                    fields[k] = int(bool(fields[k]))
            catalog_fields = set(fields) - set(db.USER_FIELDS) - {"is_primary"}
            extra = ", source = 'user'" if catalog_fields else ""
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE release SET {sets}{extra} WHERE id = ?", (*fields.values(), release_id))
            if "is_primary" in fields:
                db.set_primary_release(
                    conn, rel["work_id"], release_id, is_primary=bool(fields["is_primary"])
                )
    return work_detail(rel["work_id"])


@app.delete("/api/releases/{release_id}")
def delete_release(release_id: str):
    with db.connect() as conn:
        rel = _get_release(conn, release_id)
        count = conn.execute("SELECT COUNT(*) FROM release WHERE work_id = ?", (rel["work_id"],)).fetchone()[0]
        if count <= 1:
            raise HTTPException(400, "A book needs at least one release; delete the book instead")
        conn.execute(
            "INSERT OR IGNORE INTO catalog_deletion (entity_type, entity_id) VALUES ('release', ?)",
            (release_id,),
        )
        covers.remove(release_id)
        conn.execute("DELETE FROM release WHERE id = ?", (release_id,))
        if rel["is_primary"]:
            replacement = conn.execute(
                "SELECT id FROM release WHERE work_id = ? ORDER BY year, id LIMIT 1",
                (rel["work_id"],),
            ).fetchone()
            db.set_primary_release(conn, rel["work_id"], replacement["id"])
    return work_detail(rel["work_id"])


# ---------------------------------------------------------------- PDFs & covers

@app.get("/api/pdf-library")
def browse_pdf_library(request: Request, directory: str = ""):
    if not settings.can_edit(request):
        raise HTTPException(403, "You have read-only access to this collection.")
    if not settings.PDF_ROOT:
        raise HTTPException(404, "No PDF library folder is configured")
    try:
        folder = settings.library_path(directory)
        entries = []
        for child in folder.iterdir():
            relative = f"{directory}/{child.name}" if directory else child.name
            try:
                target = settings.library_path(relative)
            except (ValueError, OSError, RuntimeError):
                continue
            is_dir = target.is_dir()
            if is_dir or (child.suffix.lower() == ".pdf" and target.suffix.lower() == ".pdf" and target.is_file()):
                entries.append({"name": child.name, "path": relative, "directory": is_dir})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (OSError, RuntimeError):
        raise HTTPException(404, "PDF library folder is missing or unreadable") from None
    entries.sort(key=lambda entry: (not entry["directory"], str(entry["name"]).casefold(), entry["name"]))
    return {"entries": entries}


@app.patch("/api/releases/{release_id}/pdf")
def link_pdf(release_id: str, body: PdfIn):
    if body.library_path is not None:
        if body.path is not None or not body.library_path:
            raise HTTPException(422, "Select a PDF from the library")
        raw = settings.LIBRARY_PREFIX + body.library_path
    else:
        raw = os.path.expandvars(os.path.expanduser((body.path or "").strip().strip('"').strip("'")))
    unlinked = not raw
    warning = None
    rendered = None
    with db.connect() as conn:
        rel = _get_release(conn, release_id)
    if raw:
        p = settings.local_path(raw)
        if p is None:
            raise HTTPException(422, "Select a valid PDF inside the configured library")
        if p.suffix.lower() != ".pdf":
            raise HTTPException(422, "That file is not a .pdf")
        if not p.is_file():
            detail = "PDF library file is missing or unreadable" if raw.startswith(settings.LIBRARY_PREFIX) else (
                f"File not found: {raw}" + (f" (looked in {p})" if str(p) != raw else "")
            )
            raise HTTPException(422, detail)
        if rel["cover_source"] != "upload":
            try:
                rendered = covers.render_pdf_cover(str(p))
            except Exception as e:  # noqa: BLE001 - PDF linking can succeed without a cover
                warning = f"PDF linked, but the cover could not be rendered: {e}"

    with db.connect() as conn:
        rel = _get_release(conn, release_id)
        old_path = rel["pdf_path"]
        if not raw:
            conn.execute("UPDATE release SET pdf_path = NULL WHERE id = ?", (release_id,))
            if rel["cover_source"] == "pdf":
                covers.remove(release_id)
                conn.execute("UPDATE release SET cover_path = NULL, cover_source = NULL WHERE id = ?", (release_id,))
        else:
            conn.execute("UPDATE release SET pdf_path = ?, owned_pdf = 1 WHERE id = ?", (raw, release_id))
            if rendered is not None and rel["cover_source"] != "upload":
                try:
                    name = covers.save_pdf_cover(release_id, rendered)
                    conn.execute(
                        "UPDATE release SET cover_path = ?, cover_source = 'pdf' WHERE id = ?", (name, release_id)
                    )
                except Exception as e:  # noqa: BLE001 - PDF linked fine; cover is best-effort
                    warning = f"PDF linked, but the cover could not be rendered: {e}"
    if unlinked:
        pdf_indexer.remove(release_id)
        return work_detail(rel["work_id"])
    if old_path != raw:
        pdf_indexer.remove(release_id)

    out = work_detail(rel["work_id"])
    out["warning"] = warning
    return out


@app.post("/api/releases/{release_id}/cover")
async def upload_cover(release_id: str, file: UploadFile = File(...)):
    data = await file.read()
    with db.connect() as conn:
        rel = _get_release(conn, release_id)
        try:
            name = covers.save_upload(release_id, file.content_type or "", data)
        except ValueError as e:
            raise HTTPException(422, str(e))
        conn.execute("UPDATE release SET cover_path = ?, cover_source = 'upload' WHERE id = ?", (name, release_id))
    return work_detail(rel["work_id"])


@app.delete("/api/releases/{release_id}/cover")
def reset_cover(release_id: str):
    """Drop an uploaded cover and fall back to the PDF's first page (if linked)."""
    with db.connect() as conn:
        rel = _get_release(conn, release_id)
        covers.remove(release_id)
        name, source = None, None
        path = rel["pdf_path"] and settings.local_path(rel["pdf_path"])
        if path and path.is_file():
            try:
                name, source = covers.render_from_pdf(release_id, str(path)), "pdf"
            except Exception:  # noqa: BLE001
                pass
        conn.execute("UPDATE release SET cover_path = ?, cover_source = ? WHERE id = ?", (name, source, release_id))
    return work_detail(rel["work_id"])


@app.get("/pdf/{release_id}")
def serve_pdf(release_id: str):
    with db.connect() as conn:
        rel = _get_release(conn, release_id)
    path = rel["pdf_path"] and settings.local_path(rel["pdf_path"])
    if not path:
        raise HTTPException(404, "No PDF linked, or the linked file has moved")
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        raise HTTPException(404, "No PDF linked, or the linked file has moved") from None
    if not stat.S_ISREG(file_stat.st_mode):
        raise HTTPException(404, "No PDF linked, or the linked file has moved")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=Path(path).name,
        content_disposition_type="inline",
        stat_result=file_stat,
    )


@app.post("/api/releases/{release_id}/open-external", status_code=204)
def open_external(release_id: str):
    with db.connect() as conn:
        rel = _get_release(conn, release_id)
    path = rel["pdf_path"] and settings.local_path(rel["pdf_path"])
    if not path or not path.is_file():
        raise HTTPException(404, "No PDF linked, or the linked file has moved")
    if not hasattr(os, "startfile"):
        raise HTTPException(501, "Opening in an external app is only supported on Windows")
    os.startfile(path)  # type: ignore[attr-defined]


@app.get("/covers/{name}")
def serve_cover(name: str):
    p = covers.preview_file(name)
    if p is None:
        raise HTTPException(404)
    return FileResponse(
        p,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


class NoCacheStatic(StaticFiles):
    """Make the browser revalidate the app's HTML/JS/CSS every load, so updates show up
    without a hard refresh (ES module imports otherwise get served stale from cache)."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStatic(directory=STATIC_DIR, html=True), name="static")
