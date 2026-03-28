"""
Batch query and verdict-save logic for the evaluation workflow.
"""
import sqlite3

import database
from config import BATCH_SIZE


def get_next_batch(
    eval_type: str,
    folder_prefix: str,
    batch_size: int = BATCH_SIZE,
) -> list[sqlite3.Row]:
    """Return up to batch_size unevaluated photos for the given type and folder prefix."""
    conn = database.get_connection()
    try:
        rows = conn.execute("""
            SELECT p.*
            FROM photos p
            WHERE p.is_personal = 0
              AND p.folder_path LIKE ? || '%'
              AND NOT EXISTS (
                SELECT 1 FROM evaluations e
                WHERE e.photo_id = p.id AND e.eval_type = ?
              )
            ORDER BY p.folder_path, p.filename
            LIMIT ?
        """, (folder_prefix, eval_type, batch_size)).fetchall()
    finally:
        conn.close()
    return rows


def get_progress(eval_type: str, folder_prefix: str) -> dict:
    """Return reviewed/total counts for this eval_type + folder."""
    conn = database.get_connection()
    try:
        total = conn.execute("""
            SELECT COUNT(*) FROM photos
            WHERE is_personal = 0 AND folder_path LIKE ? || '%'
        """, (folder_prefix,)).fetchone()[0]

        reviewed = conn.execute("""
            SELECT COUNT(*) FROM evaluations e
            JOIN photos p ON p.id = e.photo_id
            WHERE e.eval_type = ?
              AND p.is_personal = 0
              AND p.folder_path LIKE ? || '%'
        """, (eval_type, folder_prefix)).fetchone()[0]
    finally:
        conn.close()
    return {"reviewed": reviewed, "total": total, "remaining": max(0, total - reviewed)}


def create_batch_record(eval_type: str, target_folder: str) -> int:
    """Insert a new evaluation_batches row and return its id."""
    conn = database.get_connection()
    try:
        cur = conn.execute("""
            INSERT INTO evaluation_batches (eval_type, target_folder)
            VALUES (?, ?)
        """, (eval_type, target_folder))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def save_verdicts(verdicts: list[dict], batch_id: int) -> None:
    """
    Each verdict dict: {photo_id, eval_type, verdict, rationale, rejection_reason, paper_recommendation}
    """
    conn = database.get_connection()
    try:
        for v in verdicts:
            conn.execute("""
                INSERT INTO evaluations
                    (photo_id, eval_type, verdict, rationale, rejection_reason, paper_recommendation, batch_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(photo_id, eval_type) DO UPDATE SET
                    verdict = excluded.verdict,
                    rationale = excluded.rationale,
                    rejection_reason = excluded.rejection_reason,
                    paper_recommendation = excluded.paper_recommendation,
                    batch_id = excluded.batch_id,
                    reviewed_at = datetime('now')
            """, (
                v["photo_id"],
                v["eval_type"],
                v["verdict"],
                v.get("rationale", ""),
                v.get("rejection_reason", ""),
                v.get("paper_recommendation", ""),
                batch_id,
            ))
        conn.execute("""
            UPDATE evaluation_batches
            SET images_reviewed = images_reviewed + ?
            WHERE id = ?
        """, (len(verdicts), batch_id))
        conn.commit()
    finally:
        conn.close()


def get_folder_roots_with_photos() -> list[str]:
    """Return distinct top-level folder roots that have indexed photos."""
    conn = database.get_connection()
    try:
        rows = conn.execute("""
            SELECT DISTINCT
                CASE
                    WHEN folder_path LIKE '%/%' THEN substr(folder_path, 1, instr(folder_path, '/') - 1)
                    ELSE folder_path
                END AS root
            FROM photos
            WHERE is_personal = 0
            ORDER BY root
        """).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]
