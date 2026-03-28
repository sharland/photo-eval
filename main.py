import sys
from pathlib import Path

# Ensure _app/ is on the path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import database
from config import APP_DIR, EXIFTOOL_PATH

app = FastAPI(title="Photo Eval")

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def template_response(request: Request, template: str, context: dict = None):
    ctx = {
        "request": request,
        "exiftool_available": EXIFTOOL_PATH is not None,
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(template, ctx)


@app.on_event("startup")
def startup():
    conn = database.get_connection()
    database.ensure_schema(conn)
    conn.close()
    # Ensure temp preview dir exists
    from config import TEMP_PREVIEWS
    TEMP_PREVIEWS.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    conn = database.get_connection()
    try:
        stats = _get_dashboard_stats(conn)
    finally:
        conn.close()
    return template_response(request, "index.html", {"stats": stats})


def _get_dashboard_stats(conn) -> dict:
    def scalar(sql, params=()):
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    total_photos = scalar("SELECT COUNT(*) FROM photos WHERE is_personal = 0")

    etsy_yes = scalar(
        "SELECT COUNT(*) FROM evaluations WHERE eval_type='etsy' AND verdict='yes'"
    )
    etsy_reviewed = scalar(
        "SELECT COUNT(*) FROM evaluations WHERE eval_type='etsy'"
    )
    etsy_pending = max(0, total_photos - etsy_reviewed)

    instagram_yes = scalar(
        "SELECT COUNT(*) FROM evaluations WHERE eval_type='instagram' AND verdict='yes'"
    )
    instagram_reviewed = scalar(
        "SELECT COUNT(*) FROM evaluations WHERE eval_type='instagram'"
    )
    instagram_pending = max(0, total_photos - instagram_reviewed)

    confirmed_listings = scalar("SELECT COUNT(*) FROM etsy_listings")

    recent_batches = conn.execute(
        """SELECT session_date, eval_type, target_folder, images_reviewed
           FROM evaluation_batches
           ORDER BY id DESC LIMIT 10"""
    ).fetchall()

    return {
        "total_photos": total_photos,
        "etsy_yes": etsy_yes,
        "etsy_pending": etsy_pending,
        "instagram_yes": instagram_yes,
        "instagram_pending": instagram_pending,
        "confirmed_listings": confirmed_listings,
        "recent_batches": recent_batches,
    }


# Route modules (imported here after app is created)
from routes import scan, preview, evaluate, report, listings

app.include_router(scan.router)
app.include_router(preview.router)
app.include_router(evaluate.router)
app.include_router(report.router)
app.include_router(listings.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
