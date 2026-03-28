"""
Walk the photo archive and index files into the photos + folder_scans tables.
Idempotent: re-running adds new files, existing rows are silently skipped.
"""
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import TypedDict

import database
from config import ROOT, PHOTO_EXTENSIONS

# In-memory progress store keyed by task_id
SCAN_TASKS: dict[str, dict] = {}

# Decade-folder names to skip when parsing dates (e.g. "2020s", "2010s")
_DECADE_RE = re.compile(r"^\d{4}s$")


def start_scan(root_name: str) -> str:
    """Launch a scan in the current thread (call via BackgroundTasks). Returns task_id."""
    task_id = str(uuid.uuid4())
    SCAN_TASKS[task_id] = {"status": "running", "folders_done": 0, "files_found": 0, "root": root_name}
    scan_folder(root_name, task_id)
    return task_id


def scan_folder(root_name: str, task_id: str) -> None:
    """Walk root_name (relative to ROOT) and index all photo files."""
    scan_root = ROOT / root_name
    if not scan_root.exists():
        SCAN_TASKS[task_id] = {"status": "error", "message": f"Folder not found: {scan_root}"}
        return

    conn = database.get_connection()
    try:
        _walk_and_index(scan_root, root_name, conn, task_id)
        conn.commit()
        SCAN_TASKS[task_id]["status"] = "done"
    except Exception as exc:
        conn.rollback()
        SCAN_TASKS[task_id]["status"] = "error"
        SCAN_TASKS[task_id]["message"] = str(exc)
        raise
    finally:
        conn.close()


def _walk_and_index(scan_root: Path, root_name: str, conn: sqlite3.Connection, task_id: str) -> None:
    task = SCAN_TASKS[task_id]

    for dirpath, dirnames, filenames in os.walk(scan_root):
        current_dir = Path(dirpath)
        rel_dir = current_dir.relative_to(ROOT)
        rel_str = rel_dir.as_posix()  # always forward slashes

        # Separate personal subfolder files before os.walk descends
        personal_count = 0
        if "personal" in dirnames:
            dirnames.remove("personal")  # stop os.walk from descending
            personal_dir = current_dir / "personal"
            personal_files = _list_photo_files(personal_dir)
            for fname, fsize in personal_files:
                _upsert_photo(conn, fname, rel_str + "/personal", fsize, is_personal=1)
            personal_count = len(personal_files)

        # Index files in current directory
        photo_files = [(f, os.path.getsize(current_dir / f))
                       for f in filenames
                       if Path(f).suffix.lower() in PHOTO_EXTENSIONS]

        date_taken = _parse_date(rel_str)

        for fname, fsize in photo_files:
            _upsert_photo(conn, fname, rel_str, fsize, is_personal=0, date_taken=date_taken)

        # Update folder_scans
        if photo_files or personal_count:
            conn.execute("""
                INSERT INTO folder_scans (folder_path, file_count, personal_count, scanned_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(folder_path) DO UPDATE SET
                    file_count = excluded.file_count,
                    personal_count = excluded.personal_count,
                    scanned_at = excluded.scanned_at
            """, (rel_str, len(photo_files), personal_count))

        task["folders_done"] = task.get("folders_done", 0) + 1
        task["files_found"] = task.get("files_found", 0) + len(photo_files)

        # Commit every 50 folders to avoid huge transactions
        if task["folders_done"] % 50 == 0:
            conn.commit()


def _list_photo_files(directory: Path) -> list[tuple[str, int]]:
    if not directory.exists():
        return []
    return [
        (f.name, f.stat().st_size)
        for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in PHOTO_EXTENSIONS
    ]


def _upsert_photo(
    conn: sqlite3.Connection,
    filename: str,
    folder_path: str,
    file_size: int,
    is_personal: int,
    date_taken: str | None = None,
) -> None:
    stem = Path(filename).stem
    parts = stem.split("_", 1)
    camera_prefix = parts[0] if len(parts) > 1 else ""
    extension = Path(filename).suffix.lstrip(".").upper()

    conn.execute("""
        INSERT OR IGNORE INTO photos
            (filename, folder_path, extension, file_size, camera_prefix, date_taken, is_personal)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (filename, folder_path, extension, file_size, camera_prefix, date_taken, is_personal))


def _parse_date(rel_path: str) -> str | None:
    """
    Extract YYYY-MM-DD from a relative folder path.

    Handles two structures:
      2020s/2025/04/14  →  2025-04-14
      2026/04/14        →  2026-04-14
      2026/04           →  2026-04 (partial, OK)
    """
    parts = rel_path.split("/")
    # Strip leading decade folder (e.g. "2020s", "2010s")
    filtered = [p for p in parts if not _DECADE_RE.match(p)]

    # Expect YYYY, MM, DD in remaining segments
    year = month = day = None
    for seg in filtered:
        if re.match(r"^\d{4}$", seg) and year is None:
            year = seg
        elif re.match(r"^\d{2}$", seg) and year and month is None:
            month = seg
        elif re.match(r"^\d{2}$", seg) and year and month and day is None:
            day = seg

    if year and month and day:
        return f"{year}-{month}-{day}"
    if year and month:
        return f"{year}-{month}"
    if year:
        return year
    return None
