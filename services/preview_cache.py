"""
On-demand JPEG preview generation.

- JPG/JPEG/TIFF: resize original in-memory, save to temp
- HEIC: decode via pillow-heif, resize, save to temp
- NEF: extract embedded JPEG via exiftool, resize, save to temp

Previews are ephemeral: they live in TEMP_PREVIEWS for the duration of
an evaluation session, then purged after each batch is submitted.
"""
import shutil
import sqlite3
import subprocess
from pathlib import Path

from PIL import Image

import pillow_heif
pillow_heif.register_heif_opener()  # registers HEIC/HEIF as a Pillow format

from config import EXIFTOOL_PATH, ROOT, TEMP_PREVIEWS

MAX_SIZE = (800, 800)

# Path to placeholder image served when a preview can't be generated
_PLACEHOLDER = Path(__file__).parent.parent / "templates" / "no_preview.jpg"


def get_preview_path(photo: sqlite3.Row) -> Path:
    """Return a cached JPEG preview path, generating it if needed."""
    folder = photo["folder_path"]
    filename = photo["filename"]
    stem = Path(filename).stem
    ext = Path(filename).suffix.lower()

    preview_path = TEMP_PREVIEWS / folder / (stem + ".jpg")
    if preview_path.exists():
        return preview_path

    preview_path.parent.mkdir(parents=True, exist_ok=True)
    source = ROOT / folder / filename

    if not source.exists():
        return _placeholder()

    try:
        if ext in (".jpg", ".jpeg", ".tiff", ".tif"):
            _resize_and_save(source, preview_path)
        elif ext == ".heic":
            _resize_and_save(source, preview_path)
        elif ext == ".nef":
            _extract_nef_preview(source, preview_path)
        else:
            return _placeholder()
    except Exception:
        return _placeholder()

    return preview_path if preview_path.exists() else _placeholder()


def purge_batch_previews(photo_ids: list[int], conn: sqlite3.Connection) -> None:
    """Delete temp preview files for the given photo IDs."""
    if not photo_ids:
        return
    placeholders = ",".join("?" * len(photo_ids))
    rows = conn.execute(
        f"SELECT folder_path, filename FROM photos WHERE id IN ({placeholders})",
        photo_ids,
    ).fetchall()
    for row in rows:
        stem = Path(row["filename"]).stem
        preview = TEMP_PREVIEWS / row["folder_path"] / (stem + ".jpg")
        if preview.exists():
            preview.unlink(missing_ok=True)


def _resize_and_save(source: Path, dest: Path) -> None:
    with Image.open(source) as img:
        img = img.convert("RGB")
        img.thumbnail(MAX_SIZE, Image.LANCZOS)
        img.save(dest, "JPEG", quality=85, optimize=True)


def _extract_nef_preview(source: Path, dest: Path) -> None:
    if not EXIFTOOL_PATH:
        shutil.copy(_placeholder(), dest)
        return

    # exiftool writes the embedded JPEG to a temp path, then we resize it
    tmp_out = dest.parent / (dest.stem + "_raw.jpg")
    result = subprocess.run(
        [EXIFTOOL_PATH, "-b", "-JpgFromRaw", "-w!", str(tmp_out), str(source)],
        capture_output=True,
        timeout=30,
    )
    if result.returncode == 0 and tmp_out.exists():
        try:
            _resize_and_save(tmp_out, dest)
        finally:
            tmp_out.unlink(missing_ok=True)
    else:
        shutil.copy(_placeholder(), dest)


def _placeholder() -> Path:
    return _PLACEHOLDER
