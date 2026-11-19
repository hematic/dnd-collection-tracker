"""Cover images: render page 1 of a linked PDF, or store an uploaded image."""
from __future__ import annotations

import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import db

ALLOWED_UPLOAD = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
COVER_WIDTH = 400  # px; plenty for a shelf thumbnail and the detail drawer
PREVIEW_MAX_DIMENSION = 840
PREVIEW_JPEG_QUALITY = 82


def _safe_name(release_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", release_id)


def _clear_existing(release_id: str) -> None:
    for p in db.COVERS_DIR.glob(_safe_name(release_id) + ".*"):
        p.unlink(missing_ok=True)


def render_from_pdf(release_id: str, pdf_path: str) -> str:
    """Render the first page of ``pdf_path``; return the stored file name."""
    return save_pdf_cover(release_id, render_pdf_cover(pdf_path))


def render_pdf_cover(pdf_path: str) -> bytes:
    """Render without modifying stored covers or holding a database transaction."""
    import pymupdf  # imported lazily so the app still starts if it is missing

    with pymupdf.open(pdf_path) as doc:
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
        page = doc.load_page(0)
        zoom = COVER_WIDTH / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes(output="jpg", jpg_quality=PREVIEW_JPEG_QUALITY)


def save_pdf_cover(release_id: str, data: bytes) -> str:
    _clear_existing(release_id)
    name = _safe_name(release_id) + ".jpg"
    (db.COVERS_DIR / name).write_bytes(data)
    return name


def save_upload(release_id: str, content_type: str, data: bytes) -> str:
    ext = ALLOWED_UPLOAD.get(content_type)
    if not ext:
        raise ValueError("Cover must be a PNG, JPEG or WebP image")
    if len(data) > 15 * 1024 * 1024:
        raise ValueError("Image is larger than 15 MB")
    _clear_existing(release_id)
    name = _safe_name(release_id) + ext
    (db.COVERS_DIR / name).write_bytes(data)
    return name


def remove(release_id: str) -> None:
    _clear_existing(release_id)


def cover_file(name: str) -> Path | None:
    p = (db.COVERS_DIR / name).resolve()
    if p.parent != db.COVERS_DIR.resolve() or not p.is_file():
        return None
    return p


def preview_file(name: str) -> Path | None:
    """Return a cached, display-sized preview for PNG/JPEG covers."""
    source = cover_file(name)
    if source is None or source.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return source

    source_stat = source.stat()
    for extension in (".jpg", ".png"):
        preview = source.with_name(f"{source.stem}.preview{extension}")
        try:
            if preview.stat().st_mtime_ns >= source_stat.st_mtime_ns:
                return preview
        except FileNotFoundError:
            pass

    import pymupdf  # imported lazily so the app still starts if it is missing

    pix = pymupdf.Pixmap(str(source))
    has_alpha = bool(pix.alpha)
    extension = ".png" if has_alpha else ".jpg"
    preview = source.with_name(f"{source.stem}.preview{extension}")

    scale = min(1, PREVIEW_MAX_DIMENSION / max(pix.width, pix.height))
    if scale < 1:
        pix = pymupdf.Pixmap(
            pix,
            max(1, round(pix.width * scale)),
            max(1, round(pix.height * scale)),
        )
    if not has_alpha and (pix.colorspace is None or pix.colorspace.n not in (1, 3)):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

    with NamedTemporaryFile(dir=source.parent, prefix=f".{preview.name}.", suffix=".tmp", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        if has_alpha:
            pix.save(str(temporary), output="png")
        else:
            pix.save(str(temporary), output="jpg", jpg_quality=PREVIEW_JPEG_QUALITY)
        temporary.replace(preview)
    finally:
        temporary.unlink(missing_ok=True)
    return preview
