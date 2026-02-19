from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.storage import POLYGON_DIR
from app.polygon_store import save_polygon
from pydantic import BaseModel
import json
from app.volume_stub import compute_cut_fill_stub

from pathlib import Path
import shutil
import uuid

from app.storage import ensure_dirs, UPLOAD_DIR, RENDER_DIR
from app.pdf_tools import get_page_count, render_page_png

app = FastAPI(title="TheEarthWorks.ai API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "TheEarthWorks.ai backend running"}

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    ensure_dirs()

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    job_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{job_id}.pdf"

    with pdf_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        page_count = get_page_count(pdf_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read PDF: {e}")

    return {
        "job_id": job_id,
        "page_count": page_count
    }

@app.get("/render/{job_id}/{page_number}")
def render_page(job_id: str, page_number: int, dpi: int = 150):
    ensure_dirs()

    pdf_path = UPLOAD_DIR / f"{job_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Job PDF not found.")

    if page_number < 1:
        raise HTTPException(status_code=400, detail="page_number must be >= 1")

    out_path = RENDER_DIR / f"{job_id}_p{page_number:03d}_{dpi}dpi.png"

    try:
        render_page_png(pdf_path, page_number=page_number, output_path=out_path, dpi=dpi)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render page: {e}")

    return FileResponse(str(out_path))
class PolygonPayload(BaseModel):
    points: list[dict]

@app.post("/save_polygon/{job_id}/{page_number}")
def save_polygon_route(job_id: str, page_number: int, payload: PolygonPayload):
    path = save_polygon(POLYGON_DIR, job_id, page_number, payload.points)
    return {"saved_to": str(path)}

@app.get("/compute_cut_fill_stub/{job_id}/{page_number}")
def compute_cut_fill_stub_route(job_id: str, page_number: int):
    polygon_path = POLYGON_DIR / f"{job_id}_p{page_number:03d}_polygon.json"
    if not polygon_path.exists():
        raise HTTPException(status_code=404, detail="Polygon not found")

    data = json.loads(polygon_path.read_text(encoding="utf-8"))
    points = data["points"]

    return compute_cut_fill_stub(points)
