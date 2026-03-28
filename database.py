import sqlite3
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            extension TEXT,
            file_size INTEGER,
            camera_prefix TEXT,
            date_taken TEXT,
            is_personal BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(folder_path, filename)
        );

        CREATE TABLE IF NOT EXISTS evaluation_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eval_type TEXT NOT NULL,
            target_folder TEXT,
            session_date TEXT DEFAULT (date('now')),
            images_reviewed INTEGER DEFAULT 0,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id INTEGER NOT NULL,
            eval_type TEXT NOT NULL,
            verdict TEXT,
            rationale TEXT,
            rejection_reason TEXT,
            paper_recommendation TEXT,
            batch_id INTEGER,
            reviewed_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (photo_id) REFERENCES photos(id),
            FOREIGN KEY (batch_id) REFERENCES evaluation_batches(id),
            UNIQUE(photo_id, eval_type)
        );

        CREATE TABLE IF NOT EXISTS etsy_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id INTEGER NOT NULL UNIQUE,
            status TEXT DEFAULT 'confirmed',
            collection TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (photo_id) REFERENCES photos(id)
        );

        CREATE TABLE IF NOT EXISTS folder_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path TEXT NOT NULL UNIQUE,
            file_count INTEGER,
            personal_count INTEGER DEFAULT 0,
            scanned_at TEXT DEFAULT (datetime('now')),
            last_evaluated TEXT,
            eval_type_last TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder_path);
        CREATE INDEX IF NOT EXISTS idx_photos_extension ON photos(extension);
        CREATE INDEX IF NOT EXISTS idx_photos_personal ON photos(is_personal);
        CREATE INDEX IF NOT EXISTS idx_evaluations_photo_type ON evaluations(photo_id, eval_type);
        CREATE INDEX IF NOT EXISTS idx_evaluations_verdict ON evaluations(verdict);
        CREATE INDEX IF NOT EXISTS idx_evaluations_batch ON evaluations(batch_id);
    """)
    conn.commit()
