from pathlib import Path
import json

from pathlib import Path
import json

def save_polygon(polygon_dir: Path, job_id: str, page_number: int, points: list[dict]):
    out = {
        "job_id": job_id,
        "page_number": page_number,
        "points": points
    }
    polygon_dir.mkdir(parents=True, exist_ok=True)
    path = polygon_dir / f"{job_id}_p{page_number:03d}_polygon.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return path
