"""Scan a configured library and persist its review queue, without linking anything."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import stat
import threading
from collections import defaultdict
from pathlib import Path

from . import covers, db, settings
from .pdf_matcher import Match, Matcher, Release

logger = logging.getLogger(__name__)
Identity = tuple[int, int] | Path


class ImportErrorState(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _fingerprint(info: os.stat_result) -> str:
    return f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"


def _identity(path: Path, info: os.stat_result) -> Identity:
    return (info.st_dev, info.st_ino) if info.st_ino else path


def _file_identity(path: Path | None) -> Identity | None:
    if path is not None:
        try:
            path = path.resolve(strict=True)
            info = path.stat()
            if stat.S_ISREG(info.st_mode):
                return _identity(path, info)
        except (OSError, RuntimeError):
            pass
    return None


def _scan_state(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM pdf_import_scan WHERE id = 1").fetchone()


def recover_scan() -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE pdf_import_scan SET status = 'error', error = 'Scan interrupted. Run it again.' "
            "WHERE status = 'scanning'"
        )


def start_scan() -> int:
    try:
        folder = settings.library_path("")
        if not folder.is_dir():
            raise ImportErrorState("Library folder is missing or unreadable.", 404)
    except (ValueError, OSError, RuntimeError) as exc:
        raise ImportErrorState("Select a folder inside the configured PDF library.", 422) from exc
    with db.connect() as conn:
        claimed = conn.execute(
            "UPDATE pdf_import_scan SET status = 'scanning', generation = generation + 1, "
            "scanned = 0, already_linked = 0, skipped = 0, error = NULL "
            "WHERE id = 1 AND status <> 'scanning' RETURNING generation"
        ).fetchone()
        if not claimed:
            raise ImportErrorState("A library scan is already running.")
        generation = claimed["generation"]
    try:
        threading.Thread(target=_run_scan, args=(generation, folder), daemon=True,
                         name="pdf-library-scan").start()
    except RuntimeError as exc:
        _scan_failed(generation)
        raise ImportErrorState("Could not start the library scan.", 503) from exc
    return generation


def _scan_failed(generation: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE pdf_import_scan SET status = 'error', "
            "error = 'Scan did not finish. Check that the library is readable and scan again.' "
            "WHERE generation = ?", (generation,),
        )


def _run_scan(generation: int, folder: Path) -> None:
    try:
        _scan(generation, folder)
    except Exception:
        logger.exception("PDF library scan %s failed", generation)
        _scan_failed(generation)


def _catalog_modules(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    if not db.CATALOG_PATH.is_file():
        return {}
    mappings = dict(conn.execute("SELECT catalog_id, local_id FROM catalog_work_mapping"))
    works = json.loads(db.CATALOG_PATH.read_text(encoding="utf-8"))["works"]
    return {
        mappings.get(work["id"], work["id"]): tuple(filter(None, (work.get("module"), *work.get("module_aliases", []))))
        for work in works if work.get("module") or work.get("module_aliases")
    }


def _release_rows(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["id"]: row for row in conn.execute(
        "SELECT r.*, w.title, w.edition FROM release r JOIN work w ON w.id = r.work_id"
    )}


def _release_summary(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "title": row["title"], "edition": row["edition"], "year": row["year"],
        "label": row["label"], "kind": row["release_kind"], "linked": bool(row["pdf_path"]),
    }


def _raise_walk_error(exc: OSError) -> None:
    raise exc


def _scan(generation: int, folder: Path) -> None:
    with db.connect(read_only=True) as conn:
        cached = {row["path"]: row for row in conn.execute(
            "SELECT path, fingerprint, metadata_title, ignored, chosen_release FROM pdf_import_file"
        )}
        modules = _catalog_modules(conn)
        releases = _release_rows(conn)
    matcher = Matcher([
        Release(row["id"], row["work_id"], row["title"], row["edition"], row["year"],
                row["label"], row["release_kind"], bool(row["is_primary"]), bool(row["pdf_path"]),
                row["product_code"], row["isbn"], modules.get(row["work_id"], ()))
        for row in releases.values()
    ])
    linked_paths = [settings.local_path(row["pdf_path"]) for row in releases.values() if row["pdf_path"]]
    linked_names = {os.path.normcase(str(path)) for path in linked_paths if path is not None}
    linked = {identity for path in linked_paths if (identity := _file_identity(path)) is not None}
    seen: dict[Identity, str] = {}
    drafts: dict[str, tuple[str, str | None, Match, int, str | None]] = {}
    scanned = already_linked = skipped = 0
    for parent, directories, files in os.walk(folder, onerror=_raise_walk_error, followlinks=False):
        directories.sort(key=str.casefold)
        prefix = Path(parent).relative_to(folder).as_posix()
        for name in sorted(files, key=lambda name: (name.casefold(), name)):
            if Path(name).suffix.lower() != ".pdf":
                continue
            scanned += 1
            relative = name if prefix == "." else f"{prefix}/{name}"
            try:
                path = settings.library_path(relative)
                info = path.stat()
            except (ValueError, OSError, RuntimeError):
                skipped += 1
            else:
                if path.suffix.lower() != ".pdf" or not stat.S_ISREG(info.st_mode):
                    skipped += 1
                elif ((identity := _identity(path, info)) in linked
                      or os.path.normcase(str(path)) in linked_names):
                    already_linked += 1
                else:
                    fingerprint = _fingerprint(info)
                    previous = cached.get(relative)
                    unchanged = previous is not None and previous["fingerprint"] == fingerprint
                    other_path = seen.get(identity)
                    other = drafts[other_path] if other_path is not None else None
                    if unchanged and previous is not None:
                        title = previous["metadata_title"]
                    elif other is not None and other[0] == fingerprint:
                        title = other[1]
                    else:
                        title = covers.pdf_title(path)
                    ignored = previous["ignored"] if previous is not None else 0
                    chosen = previous["chosen_release"] if unchanged and previous is not None else None
                    match = matcher.match(relative, title)
                    rank = (bool(ignored or chosen), match.tier == "ready",
                            match.candidates[0].score if match.candidates else 0)
                    replace = other is None
                    if other_path is not None and other is not None:
                        other_match = other[2]
                        other_rank = (bool(other[3] or other[4]), other_match.tier == "ready",
                                      other_match.candidates[0].score if other_match.candidates else 0)
                        replace = rank > other_rank
                        if replace:
                            del drafts[other_path]
                        skipped += 1
                    if replace:
                        seen[identity] = relative
                        drafts[relative] = (fingerprint, title, match, ignored, chosen)
            if scanned % 20 == 0:
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE pdf_import_scan SET scanned = ?, already_linked = ?, skipped = ? WHERE generation = ?",
                        (scanned, already_linked, skipped, generation),
                    )

    requests: dict[str, list[tuple[str, Match, bool]]] = defaultdict(list)
    for path, (_, _, match, ignored, chosen) in drafts.items():
        if not ignored and (chosen or match.candidates):
            candidate = match.candidates[0] if match.candidates else None
            target = chosen or (candidate.release.id if candidate and not candidate.release.linked else None)
            if target:
                requests[target].append((path, match, bool(chosen)))
    for group in requests.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda entry: (not entry[2], entry[1].tier != "ready",
                                      -entry[1].candidates[0].score if entry[1].candidates else 0, entry[0]))
        lead, runner = group[:2]
        close = (not lead[2] and lead[1].candidates[0].score - runner[1].candidates[0].score < 14)
        for i, (_, match, chosen) in enumerate(group):
            if not chosen and (i != 0 or close):
                match.tier = "review"
            if i != 0 or close or chosen:
                match.note = f"Another file suggests the same printing: {(runner if i == 0 else lead)[0]}"

    rows = []
    for path, (fingerprint, title, match, ignored, chosen) in drafts.items():
        candidates = [
            {"id": c.release.id, "reasons": c.reasons, "score": round(c.score, 1),
             "printing": _release_summary(releases[c.release.id])}
            for c in match.candidates
        ]
        rows.append((path, fingerprint, title, match.tier, json.dumps(candidates), match.query, match.note,
                     ignored, chosen))
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        scan = _scan_state(conn)
        if scan["generation"] != generation or scan["status"] != "scanning":
            return
        # Publish one complete snapshot; a failed scan leaves the previous queue intact.
        conn.execute("DELETE FROM pdf_import_file")
        conn.executemany(
            "INSERT INTO pdf_import_file (path, fingerprint, metadata_title, tier, candidates_json, query, note, "
            "ignored, chosen_release) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
            "(SELECT id FROM release WHERE id = ?))", rows,
        )
        conn.execute(
            "UPDATE pdf_import_scan SET status = 'done', scanned = ?, already_linked = ?, skipped = ?, "
            "finished_at = CURRENT_TIMESTAMP WHERE generation = ?", (scanned, already_linked, skipped, generation),
        )


def _review_rows(conn: sqlite3.Connection) -> list[dict]:
    releases = _release_rows(conn)
    reserved = dict(conn.execute(
        "SELECT chosen_release, path FROM pdf_import_file WHERE chosen_release IS NOT NULL AND ignored = 0"
    ))
    output = []
    for row in conn.execute("SELECT * FROM pdf_import_file ORDER BY path COLLATE NOCASE, path"):
        proposed = json.loads(row["candidates_json"])
        candidates = []
        for candidate in proposed:
            release = releases.get(candidate["id"])
            if release is not None:
                candidates.append({**_release_summary(release), "reasons": candidate["reasons"],
                                   "score": candidate["score"]})
        chosen = releases.get(row["chosen_release"])
        selected = _release_summary(chosen) if chosen is not None and not chosen["pdf_path"] else None
        note = None if selected is not None else row["note"]
        tier = row["tier"]
        if selected is None and tier == "ready" and proposed:
            original = releases.get(proposed[0]["id"])
            if original is None or _release_summary(original) != proposed[0]["printing"]:
                tier = "review"
                note = "The suggested printing changed or already has a linked PDF. Check the alternatives."
            elif chosen is None:
                if original["id"] in reserved:
                    tier = "review"
                    note = f"Another file was assigned to this printing: {reserved[original['id']]}"
                else:
                    selected = candidates[0]
        if chosen is not None and chosen["pdf_path"]:
            note = "The chosen printing already has a linked PDF."
            tier = "review"
        if row["ignored"]:
            tier, selected = "ignored", None
        elif selected is not None:
            tier = "ready"
        output.append({"path": row["path"], "tier": tier, "selected": selected, "candidates": candidates,
                       "query": row["query"], "note": note, "manual": chosen is not None})
    return output


def status() -> dict:
    with db.connect(read_only=True) as conn:
        conn.execute("BEGIN")
        scan = dict(_scan_state(conn))
        counts = dict.fromkeys(("ready", "review", "none", "ignored"), 0)
        if scan["status"] != "scanning":
            for row in _review_rows(conn):
                counts[row["tier"]] += 1
    scan.pop("id")
    return {**scan, "counts": counts}


def list_files(tier: str, query: str, offset: int, limit: int) -> dict:
    with db.connect(read_only=True) as conn:
        conn.execute("BEGIN")
        scan = _scan_state(conn)
        rows = [] if scan["status"] == "scanning" else _review_rows(conn)
    rows = [r for r in rows if (tier == "all" or r["tier"] == tier) and query.casefold() in r["path"].casefold()]
    return {"generation": scan["generation"], "total": len(rows), "items": rows[offset:offset + limit]}


def _check_generation(conn: sqlite3.Connection, generation: int) -> None:
    scan = _scan_state(conn)
    if scan["status"] == "scanning" or scan["generation"] != generation:
        raise ImportErrorState("The scan changed. Refresh the review list and try again.")


def _get_file(conn: sqlite3.Connection, relative: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM pdf_import_file WHERE path = ?", (relative,)).fetchone()
    if row is None:
        raise ImportErrorState("File is no longer in the review list.", 404)
    return row


def decide(generation: int, paths: list[str], action: str, release_id: str | None) -> None:
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _check_generation(conn, generation)
        rows = [_get_file(conn, path) for path in paths]
        if action == "choose":
            _current_file(rows[0])
            release = conn.execute("SELECT pdf_path FROM release WHERE id = ?", (release_id,)).fetchone()
            if not release or release["pdf_path"]:
                raise ImportErrorState("Choose a printing that does not already have a linked PDF.")
            if conn.execute(
                "SELECT 1 FROM pdf_import_file WHERE chosen_release = ? AND ignored = 0 AND path <> ?",
                (release_id, paths[0]),
            ).fetchone():
                raise ImportErrorState("Another file is already assigned to that printing.")
            conn.execute("UPDATE pdf_import_file SET chosen_release = ?, ignored = 0 WHERE path = ?",
                         (release_id, paths[0]))
        else:
            for path in paths:
                if action == "restore":
                    conn.execute(
                        "UPDATE pdf_import_file SET ignored = 0, chosen_release = CASE WHEN chosen_release IN ("
                        "SELECT chosen_release FROM pdf_import_file WHERE ignored = 0 AND path <> ?"
                        ") THEN NULL ELSE chosen_release END WHERE path = ?", (path, path),
                    )
                else:
                    conn.execute("UPDATE pdf_import_file SET ignored = 1 WHERE path = ?", (path,))


def _current_file(row: sqlite3.Row) -> tuple[Path, os.stat_result]:
    try:
        path = settings.library_path(row["path"])
        info = path.stat()
        if path.suffix.lower() == ".pdf" and stat.S_ISREG(info.st_mode) and _fingerprint(info) == row["fingerprint"]:
            return path, info
    except (ValueError, OSError, RuntimeError) as exc:
        raise ImportErrorState("PDF is missing or unreadable. Rescan the library.") from exc
    raise ImportErrorState("PDF changed since the scan. Rescan the library before using it.")


def reviewed_file(relative: str) -> tuple[Path, os.stat_result]:
    with db.connect(read_only=True) as conn:
        return _current_file(_get_file(conn, relative))


def validate_link(conn: sqlite3.Connection, generation: int, relative: str, release_id: str,
                  identity_cache: dict[str, Identity | None], *, consume: bool = False) -> None:
    _check_generation(conn, generation)
    row = _get_file(conn, relative)
    if row["ignored"]:
        raise ImportErrorState("Restore the ignored file before linking it.")
    release = conn.execute(
        "SELECT r.*, w.title, w.edition FROM release r JOIN work w ON w.id = r.work_id WHERE r.id = ?",
        (release_id,),
    ).fetchone()
    if release is None or release["pdf_path"]:
        raise ImportErrorState("The selected printing is missing or already has a PDF.")
    if row["chosen_release"] != release_id:
        candidates = json.loads(row["candidates_json"])
        if (row["chosen_release"] is not None or row["tier"] != "ready" or not candidates
                or candidates[0]["id"] != release_id or candidates[0]["printing"] != _release_summary(release)):
            raise ImportErrorState("Review this match and choose a printing before linking it.")
        if conn.execute(
            "SELECT 1 FROM pdf_import_file WHERE chosen_release = ? AND ignored = 0", (release_id,),
        ).fetchone():
            raise ImportErrorState("Another file was manually assigned to this printing.")
    path, info = _current_file(row)
    identity = _identity(path, info)
    for (stored,) in conn.execute("SELECT pdf_path FROM release WHERE pdf_path IS NOT NULL"):
        if stored not in identity_cache:
            identity_cache[stored] = _file_identity(settings.local_path(stored))
        if identity_cache[stored] == identity:
            raise ImportErrorState("This PDF is already linked to a printing.")
    if consume:
        conn.execute("DELETE FROM pdf_import_file WHERE path = ?", (relative,))
        identity_cache[settings.LIBRARY_PREFIX + relative] = identity
