from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

import database
from config import APP_DIR, EXIFTOOL_PATH

router = APIRouter()
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _tmpl(request: Request, name: str, ctx: dict = None):
    base = {"request": request, "exiftool_available": EXIFTOOL_PATH is not None}
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(name, base)


@router.get("/listings", response_class=HTMLResponse)
def listings_page(request: Request, collection: str = ""):
    conn = database.get_connection()
    try:
        photos = _get_etsy_yes(conn, collection)
        confirmed_ids = {
            r[0] for r in conn.execute("SELECT photo_id FROM etsy_listings").fetchall()
        }
        collections = [r[0] for r in conn.execute(
            "SELECT DISTINCT collection FROM etsy_listings WHERE collection IS NOT NULL ORDER BY collection"
        ).fetchall()]
    finally:
        conn.close()
    return _tmpl(request, "listings.html", {
        "photos": photos,
        "confirmed_ids": confirmed_ids,
        "collections": collections,
        "selected_collection": collection,
    })


@router.post("/listings/confirm/{photo_id}", response_class=HTMLResponse)
async def confirm_listing(photo_id: int, request: Request):
    form = await request.form()
    collection = form.get("collection", "").strip() or None
    conn = database.get_connection()
    try:
        conn.execute("""
            INSERT INTO etsy_listings (photo_id, collection)
            VALUES (?, ?)
            ON CONFLICT(photo_id) DO UPDATE SET collection = excluded.collection
        """, (photo_id, collection))
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse(f'<span style="color:var(--yes-active);">✓ Confirmed</span>')


@router.post("/listings/remove/{photo_id}", response_class=HTMLResponse)
async def remove_listing(photo_id: int):
    conn = database.get_connection()
    try:
        conn.execute("DELETE FROM etsy_listings WHERE photo_id = ?", (photo_id,))
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse('<span style="color:var(--muted);">Removed</span>')


@router.get("/listings/export")
def export_listings(collection: str = ""):
    conn = database.get_connection()
    try:
        rows = _get_confirmed_for_export(conn, collection)
    finally:
        conn.close()

    if not rows:
        return PlainTextResponse("No confirmed listings to export.")

    lines = []
    for r in rows:
        lines.append(f"{r['filename']} — {r['date_taken'] or r['folder_path']}")
        if r["paper_recommendation"]:
            lines.append(f"Paper: {r['paper_recommendation']}")
        if r["rationale"]:
            lines.append(f"Rationale: {r['rationale']}")
        if r["collection"]:
            lines.append(f"Collection: {r['collection']}")
        lines.append(f"Path: {r['folder_path']}")
        lines.append("")

    return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="etsy_listings.txt"'})


def _get_etsy_yes(conn, collection: str) -> list:
    collection_clause = "AND el.collection = ?" if collection else ""
    params = ["etsy", "yes"]
    if collection:
        params.append(collection)
    return conn.execute(f"""
        SELECT p.*, e.rationale, e.paper_recommendation, el.collection, el.status,
               CASE WHEN el.photo_id IS NOT NULL THEN 1 ELSE 0 END AS is_confirmed
        FROM photos p
        JOIN evaluations e ON e.photo_id = p.id
        LEFT JOIN etsy_listings el ON el.photo_id = p.id
        WHERE e.eval_type = ? AND e.verdict = ?
          {collection_clause}
        ORDER BY p.folder_path, p.filename
    """, params).fetchall()


def _get_confirmed_for_export(conn, collection: str) -> list:
    col_clause = "AND el.collection = ?" if collection else ""
    params = ["etsy", "yes"]
    if collection:
        params.append(collection)
    return conn.execute(f"""
        SELECT p.filename, p.folder_path, p.date_taken,
               e.rationale, e.paper_recommendation, el.collection
        FROM etsy_listings el
        JOIN photos p ON p.id = el.photo_id
        JOIN evaluations e ON e.photo_id = p.id AND e.eval_type = ? AND e.verdict = ?
        WHERE 1=1 {col_clause}
        ORDER BY p.folder_path, p.filename
    """, params).fetchall()
