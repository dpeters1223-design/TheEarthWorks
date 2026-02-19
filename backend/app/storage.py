from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

STORAGE_DIR = PROJECT_ROOT / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
RENDER_DIR = STORAGE_DIR / "renders"
POLYGON_DIR = STORAGE_DIR / "polygons"

def ensure_dirs():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    POLYGON_DIR.mkdir(parents=True, exist_ok=True)
