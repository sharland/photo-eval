import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import database
from services.preview_cache import get_preview_path

router = APIRouter()


@router.get("/preview/{photo_id}")
async def serve_preview(photo_id: int):
    conn = database.get_connection()
    try:
        photo = conn.execute(
            "SELECT * FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()
    finally:
        conn.close()

    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    preview_path = await asyncio.to_thread(get_preview_path, photo)
    return FileResponse(
        str(preview_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )
