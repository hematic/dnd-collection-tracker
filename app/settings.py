"""Deployment settings, all from environment variables (none are needed locally).

DND_TRACKER_DATA      Folder holding tracker.db and covers/ (default: ./data).
DND_TRACKER_PDF_ROOT  Optional folder exposed by the PDF library picker.
DND_TRACKER_PDF_MAP   Translate stored PDF paths to where the files are on this machine.
                      "from=to" pairs separated by ";", e.g.
                      \\\\nas\\Books=/pdfs
                      Matching ignores case and treats \\ and / the same.
DND_TRACKER_ADMINS    Comma-separated usernames/emails allowed to make changes, matched
                      against the Remote-User / Remote-Email headers set by TinyAuth
                      (via Traefik forward auth). Everyone else is read-only.
                      Unset = everyone can edit (local use).
DND_TRACKER_TRUSTED_PROXIES
                      Comma-separated IPs of the reverse proxy (Traefik). When set, only
                      requests from these IPs (and localhost, for the healthcheck) are
                      served, so nobody on the LAN can skip the login by hitting the
                      published port directly with forged Remote-* headers.
DND_TRACKER_REQUIRE_TRUSTED_PROXIES
                      "true" makes the app refuse to start without
                      DND_TRACKER_TRUSTED_PROXIES. docker-compose.yml sets it, because
                      Compose can't require "this variable or its old name, TRAEFIK_IP".
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Request


def _norm(p: str) -> str:
    return p.replace("\\", "/").rstrip("/")


def _parse_map(raw: str) -> list[tuple[str, str]]:
    pairs = []
    for entry in raw.split(";"):
        if "=" in entry:
            src, dst = entry.split("=", 1)
            if src.strip() and dst.strip():
                pairs.append((_norm(src.strip()), dst.strip()))
    # Longest prefix first so nested mappings win.
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


PDF_MAP = _parse_map(os.environ.get("DND_TRACKER_PDF_MAP", ""))
PDF_ROOT = os.environ.get("DND_TRACKER_PDF_ROOT")
LIBRARY_PREFIX = "library:"
ADMINS = {a.strip().lower() for a in os.environ.get("DND_TRACKER_ADMINS", "").split(",") if a.strip()}
IDENTITY_HEADERS = ("remote-user", "remote-email")
TRUSTED_PROXIES = {ip.strip() for ip in os.environ.get("DND_TRACKER_TRUSTED_PROXIES", "").split(",") if ip.strip()}
LOOPBACK = {"127.0.0.1", "::1"}
REQUIRE_TRUSTED_PROXIES = os.environ.get("DND_TRACKER_REQUIRE_TRUSTED_PROXIES", "").strip().lower() == "true"


def check_startup() -> None:
    """Refuse to serve a deployment that requires a trusted proxy but names none."""
    if REQUIRE_TRUSTED_PROXIES and not TRUSTED_PROXIES:
        raise RuntimeError(
            "Set DND_TRACKER_TRUSTED_PROXIES to the IP your reverse proxy connects from "
            "(TRAEFIK_IP is also accepted). Without it, anyone who can reach the app's port "
            "could skip the login and claim to be an editor."
        )


def allowed_client(request: Request) -> bool:
    if not TRUSTED_PROXIES:
        return True
    host = request.client.host if request.client else ""
    return host in TRUSTED_PROXIES or host in LOOPBACK


def _inside(path: str | Path, roots: list[str], *, follow_symlinks: bool = True) -> Path | None:
    """``path`` with ".." (and, by default, symlinks) resolved, if that lies inside one of
    ``roots``. Without following symlinks, a library may link to files elsewhere on the
    server through symlinks its owner created, while a typed "../" still can't escape."""
    normalize = os.path.realpath if follow_symlinks else os.path.normpath
    real = normalize(os.path.abspath(path))
    for root in roots:
        base = normalize(os.path.abspath(root))
        if real == base or real.startswith(base.rstrip(os.sep) + os.sep):
            return Path(real)
    return None


def library_path(relative: str) -> Path:
    if not PDF_ROOT:
        raise ValueError("No PDF library folder is configured")
    parts = relative.split("/") if relative else []
    if any(part in ("", ".", "..") or "\\" in part or ":" in part or "\0" in part for part in parts):
        raise ValueError("Invalid PDF library path")
    root = os.path.expanduser(PDF_ROOT)
    path = _inside(os.path.join(root, *parts), [root])
    if path is None:
        raise ValueError("Path is outside the PDF library")
    return path


def local_path(stored: str) -> Path | None:
    """Where a stored PDF path lives on this machine, or None if it may not be used.

    With a PDF library configured (always, in Docker), every PDF must lie inside the
    library or a DND_TRACKER_PDF_MAP target, so a pasted path can't expose other files
    on the server. Without one (a local install), any file the user can open is allowed.
    """
    if stored.startswith(LIBRARY_PREFIX):
        try:
            path = library_path(stored[len(LIBRARY_PREFIX):])
        except (ValueError, OSError, RuntimeError):
            return None
        return path if path.suffix.lower() == ".pdf" else None
    norm = _norm(stored)
    for src, dst in PDF_MAP:
        if norm.lower() == src.lower() or norm.lower().startswith(src.lower() + "/"):
            rest = norm[len(src):].lstrip("/")
            path = Path(dst, *rest.split("/")) if rest else Path(dst)
            break
    else:
        path = Path(stored)
    if not PDF_ROOT:
        return path
    try:
        return _inside(
            path, [os.path.expanduser(PDF_ROOT), *(dst for _, dst in PDF_MAP)], follow_symlinks=False
        )
    except (ValueError, OSError):
        return None


def user(request: Request) -> str | None:
    for h in IDENTITY_HEADERS:
        v = request.headers.get(h, "").strip()
        if v:
            return v
    return None


def can_edit(request: Request) -> bool:
    if not ADMINS:
        return True
    ids = {request.headers.get(h, "").strip().lower() for h in IDENTITY_HEADERS}
    return bool(ids & ADMINS)
