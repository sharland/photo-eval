import uuid
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import database
from config import APP_DIR, EXIFTOOL_PATH, PHOTO_ROOTS
from services.scanner import SCAN_TASKS, scan_folder


def _scan_all(task_id: str) -> None:
    """Scan every PHOTO_ROOT sequentially, accumulating progress into one task."""
    for root in PHOTO_ROOTS:
        if SCAN_TASKS[task_id]["status"] == "error":
            break
        SCAN_TASKS[task_id]["root"] = root
        scan_folder(root, task_id)
    if SCAN_TASKS[task_id]["status"] != "error":
        SCAN_TASKS[task_id]["status"] = "done"
        SCAN_TASKS[task_id]["root"] = "all"

router = APIRouter()
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _tmpl(request: Request, name: str, ctx: dict = None):
    base = {"request": request, "exiftool_available": EXIFTOOL_PATH is not None}
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(name, base)


@router.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request):
    conn = database.get_connection()
    try:
        folder_stats = conn.execute("""
            SELECT fs.folder_path, fs.file_count, fs.personal_count, fs.scanned_at,
                   fs.last_evaluated, fs.eval_type_last
            FROM folder_scans fs
            ORDER BY fs.folder_path
        """).fetchall()
        total_indexed = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE is_personal = 0"
        ).fetchone()[0]
    finally:
        conn.close()

    return _tmpl(request, "scan.html", {
        "photo_roots": PHOTO_ROOTS,
        "folder_stats": folder_stats,
        "total_indexed": total_indexed,
    })


@router.post("/scan/start", response_class=HTMLResponse)
async def scan_start(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    root_name = form.get("root", "").strip()
    if not root_name:
        return HTMLResponse("<p style='color:red'>No folder selected.</p>", status_code=400)

    task_id = str(uuid.uuid4())
    SCAN_TASKS[task_id] = {
        "status": "running",
        "folders_done": 0,
        "files_found": 0,
        "root": root_name,
    }
    if root_name == "all":
        background_tasks.add_task(_scan_all, task_id)
    else:
        background_tasks.add_task(scan_folder, root_name, task_id)

    # Return a status poller partial
    return HTMLResponse(f"""
        <div id="scan-status" hx-get="/scan/status/{task_id}"
             hx-trigger="every 2s" hx-swap="outerHTML">
          <p style="color:#4a9eff">&#9654; Scanning <strong>{root_name}</strong>…
            <span class="spinner">⏳</span></p>
        </div>
    """)


@router.get("/scan/status/{task_id}", response_class=HTMLResponse)
def scan_status(task_id: str):
    task = SCAN_TASKS.get(task_id)
    if not task:
        return HTMLResponse("<p style='color:var(--muted)'>Unknown task.</p>")

    root = task.get("root", "")
    folders = task.get("folders_done", 0)
    files = task.get("files_found", 0)
    status = task.get("status", "running")

    if status == "running":
        return HTMLResponse(f"""
            <div id="scan-status" hx-get="/scan/status/{task_id}"
                 hx-trigger="every 2s" hx-swap="outerHTML">
              <p style="color:#4a9eff">&#9654; Scanning <strong>{root}</strong> —
                {folders} folders, {files:,} files so far… ⏳</p>
            </div>
        """)
    elif status == "done":
        return HTMLResponse(f"""
            <div id="scan-status">
              <p style="color:#5aba5a">&#10003; Scan complete: <strong>{root}</strong> —
                {folders} folders, {files:,} files indexed.
                <a href="/scan" style="color:var(--accent); margin-left:1rem">Refresh</a></p>
            </div>
        """)
    else:
        msg = task.get("message", "Unknown error")
        return HTMLResponse(f"""
            <div id="scan-status">
              <p style="color:#ca4a4a">&#10007; Scan error on <strong>{root}</strong>: {msg}</p>
            </div>
        """)
