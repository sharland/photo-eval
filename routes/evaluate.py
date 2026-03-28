import asyncio
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import database
from config import APP_DIR, EVAL_TYPES, ETSY_PAPERS, EXIFTOOL_PATH
from services.evaluator import (
    create_batch_record,
    get_folder_roots_with_photos,
    get_next_batch,
    get_progress,
    save_verdicts,
)
from services.preview_cache import get_preview_path, purge_batch_previews

router = APIRouter()
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _tmpl(request: Request, name: str, ctx: dict = None):
    base = {"request": request, "exiftool_available": EXIFTOOL_PATH is not None}
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(name, base)


@router.get("/evaluate", response_class=HTMLResponse)
def evaluate_home(request: Request):
    roots = get_folder_roots_with_photos()
    return _tmpl(request, "evaluate.html", {
        "eval_types": EVAL_TYPES,
        "roots": roots,
    })


@router.get("/evaluate/batch", response_class=HTMLResponse)
async def evaluate_batch(
    request: Request,
    eval_type: str = "etsy",
    folder: str = "",
    batch_id: Optional[int] = None,
):
    photos = get_next_batch(eval_type, folder)
    progress = get_progress(eval_type, folder)

    # Create a new batch record if needed
    if batch_id is None and photos:
        batch_id = create_batch_record(eval_type, folder)

    # Pre-warm previews in parallel
    if photos:
        await asyncio.gather(*[
            asyncio.to_thread(get_preview_path, p) for p in photos
        ])

    return _tmpl(request, "evaluate_batch.html", {
        "photos": photos,
        "eval_type": eval_type,
        "folder": folder,
        "batch_id": batch_id,
        "progress": progress,
        "etsy_papers": ETSY_PAPERS,
    })


@router.post("/evaluate/verdict", response_class=HTMLResponse)
async def evaluate_verdict(request: Request):
    form = await request.form()
    eval_type = form.get("eval_type", "etsy")
    folder = form.get("folder", "")
    batch_id = int(form.get("batch_id", 0))
    photo_ids_raw = form.getlist("photo_ids")
    photo_ids = [int(x) for x in photo_ids_raw]

    verdicts = []
    for i, pid in enumerate(photo_ids):
        verdict = form.get(f"verdict_{i}", "").strip()
        if not verdict:
            continue  # skip unset (shouldn't happen but be safe)
        verdicts.append({
            "photo_id": pid,
            "eval_type": eval_type,
            "verdict": verdict,
            "rationale": form.get(f"rationale_{i}", "").strip(),
            "rejection_reason": form.get(f"rejection_reason_{i}", "").strip(),
            "paper_recommendation": form.get(f"paper_{i}", "").strip(),
        })

    if verdicts:
        save_verdicts(verdicts, batch_id)
        # Purge temp previews for this batch
        conn = database.get_connection()
        try:
            purge_batch_previews(photo_ids, conn)
        finally:
            conn.close()

    # Return next batch
    next_photos = get_next_batch(eval_type, folder)
    progress = get_progress(eval_type, folder)
    next_batch_id = create_batch_record(eval_type, folder) if next_photos else None

    if next_photos:
        await asyncio.gather(*[
            asyncio.to_thread(get_preview_path, p) for p in next_photos
        ])

    return _tmpl(request, "evaluate_batch.html", {
        "photos": next_photos,
        "eval_type": eval_type,
        "folder": folder,
        "batch_id": next_batch_id,
        "progress": progress,
        "etsy_papers": ETSY_PAPERS,
        "just_saved": len(verdicts),
    })
