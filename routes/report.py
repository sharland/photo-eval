from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import database
from config import APP_DIR, EVAL_TYPES, EXIFTOOL_PATH

router = APIRouter()
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _tmpl(request: Request, name: str, ctx: dict = None):
    base = {"request": request, "exiftool_available": EXIFTOOL_PATH is not None}
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(name, base)


@router.get("/report", response_class=HTMLResponse)
def report(request: Request, folder: str = ""):
    conn = database.get_connection()
    try:
        stats = _build_report(conn, folder)
        # Top-level folder roots with photos
        roots = [r[0] for r in conn.execute("""
            SELECT DISTINCT
                CASE WHEN folder_path LIKE '%/%'
                     THEN substr(folder_path, 1, instr(folder_path, '/') - 1)
                     ELSE folder_path END
            FROM photos WHERE is_personal = 0 ORDER BY 1
        """).fetchall()]
        pending = _build_pending(conn)
    finally:
        conn.close()
    return _tmpl(request, "report.html", {
        "stats": stats,
        "roots": roots,
        "selected_folder": folder,
        "eval_types": EVAL_TYPES,
        "pending": pending,
    })


def _build_report(conn, folder_prefix: str) -> dict:
    folder_clause = "AND p.folder_path LIKE ? || '%'" if folder_prefix else ""
    params_base = [folder_prefix] if folder_prefix else []

    def scalar(sql, params=()):
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    total = scalar(
        f"SELECT COUNT(*) FROM photos p WHERE p.is_personal = 0 {folder_clause}",
        params_base,
    )

    per_type = {}
    for et in EVAL_TYPES:
        params = [et] + params_base
        yes = scalar(
            f"SELECT COUNT(*) FROM evaluations e JOIN photos p ON p.id = e.photo_id "
            f"WHERE e.eval_type = ? AND e.verdict = 'yes' AND p.is_personal = 0 {folder_clause}",
            params,
        )
        edge = scalar(
            f"SELECT COUNT(*) FROM evaluations e JOIN photos p ON p.id = e.photo_id "
            f"WHERE e.eval_type = ? AND e.verdict = 'edge_case' AND p.is_personal = 0 {folder_clause}",
            params,
        )
        no = scalar(
            f"SELECT COUNT(*) FROM evaluations e JOIN photos p ON p.id = e.photo_id "
            f"WHERE e.eval_type = ? AND e.verdict = 'no' AND p.is_personal = 0 {folder_clause}",
            params,
        )
        reviewed = yes + edge + no
        per_type[et] = {
            "yes": yes, "edge": edge, "no": no,
            "reviewed": reviewed,
            "pending": max(0, total - reviewed),
            "hit_rate": f"{(yes / reviewed * 100):.1f}%" if reviewed else "—",
        }

    # Paper breakdown for Etsy YES
    paper_params = ["etsy", "yes"] + params_base
    paper_rows = conn.execute(
        f"""SELECT COALESCE(e.paper_recommendation, '(none)') as paper, COUNT(*) as cnt
            FROM evaluations e JOIN photos p ON p.id = e.photo_id
            WHERE e.eval_type = ? AND e.verdict = ?
              AND p.is_personal = 0 {folder_clause}
            GROUP BY paper ORDER BY cnt DESC""",
        paper_params,
    ).fetchall()

    return {"total": total, "per_type": per_type, "paper_breakdown": paper_rows}


def _build_pending(conn) -> list:
    """Folders with photos not yet evaluated for etsy."""
    return conn.execute("""
        SELECT
            CASE WHEN p.folder_path LIKE '%/%'
                 THEN substr(p.folder_path, 1, instr(p.folder_path, '/') - 1)
                 ELSE p.folder_path END as root,
            COUNT(*) as total,
            SUM(CASE WHEN e.id IS NULL THEN 1 ELSE 0 END) as pending_etsy
        FROM photos p
        LEFT JOIN evaluations e ON e.photo_id = p.id AND e.eval_type = 'etsy'
        WHERE p.is_personal = 0
        GROUP BY root
        HAVING pending_etsy > 0
        ORDER BY root
    """).fetchall()
