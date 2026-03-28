import os
import shutil
from pathlib import Path

ROOT = Path("D:/Dropbox/mac photos")
DB_PATH = ROOT / "photo_eval.db"
APP_DIR = Path(__file__).parent

TEMP_PREVIEWS = Path(os.environ.get("LOCALAPPDATA", os.environ.get("TEMP", "/tmp"))) / "photo_eval"

PHOTO_EXTENSIONS = {".nef", ".jpg", ".jpeg", ".heic", ".tiff", ".tif"}

PHOTO_ROOTS = ["1904", "1999", "2000s", "2010s", "2020s", "2026", "SLR", "scans"]

ETSY_PAPERS = [
    "Photo Rag",
    "Pearl",
    "Baryta",
    "German Etching",
    "Bamboo",
    "Ilford Cotton Textured",
    "Epson Semi-Gloss",
]

EVAL_TYPES = ["etsy", "instagram", "portfolio"]

BATCH_SIZE = 12

# Resolve exiftool: check app-local first, then PATH
def _find_exiftool() -> str | None:
    local = APP_DIR / "exiftool.exe"
    if local.exists():
        return str(local)
    return shutil.which("exiftool")

EXIFTOOL_PATH: str | None = _find_exiftool()
