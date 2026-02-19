"""extract_vectors.py

Extracts raw vector geometry and text from grading plan PDF pages using PyMuPDF.

Reads outputs/sheet_classification.json to identify grading pages, then for each
grading page extracts:
  - All vector paths with style attributes (width, color, dashes, closed flag)
  - All text elements with position and font size
  - Flags text that looks like an elevation label (3–4 digit number)

Does NOT classify paths into contour/LOD/etc — that's label_contours.py's job.
Coordinates are in PDF points (1 pt = 1/72 in), origin top-left, y increases down.

Output: outputs/vectors.json
"""

import json
import re
from pathlib import Path

import fitz  # PyMuPDF

BASE_DIR = Path(__file__).parent
SHEET_CLASS_FILE = BASE_DIR / "outputs" / "sheet_classification.json"
INPUT_DIR = BASE_DIR / "Input"
OUTPUT_FILE = BASE_DIR / "outputs" / "vectors.json"

GRADING_TYPES = {"SITE_GRADING_PLAN", "GRADING_PLAN", "FINAL_GRADING_PLAN", "BASE_GRADING_PLAN"}
MIN_CONFIDENCE = 0.5

# Matches bare 3–4 digit numbers (optionally one decimal place): 570, 1344, 594.5
ELEVATION_RE = re.compile(r"^\d{3,4}(?:\.\d{1,2})?$")

BEZIER_STEPS = 8  # samples per cubic bezier segment


# --------------------------------------------------
# Path geometry helpers
# --------------------------------------------------

def sample_bezier(p0, p1, p2, p3) -> list:
    """Sample a cubic bezier curve at BEZIER_STEPS intervals. Returns [[x,y], ...]."""
    pts = []
    for i in range(BEZIER_STEPS + 1):
        t = i / BEZIER_STEPS
        u = 1 - t
        x = u**3*p0.x + 3*u**2*t*p1.x + 3*u*t**2*p2.x + t**3*p3.x
        y = u**3*p0.y + 3*u**2*t*p1.y + 3*u*t**2*p2.y + t**3*p3.y
        pts.append([round(x, 3), round(y, 3)])
    return pts


def extract_path_points(items: list) -> list:
    """Flatten all path items into a list of [x, y] sample points."""
    pts = []
    for item in items:
        kind = item[0]
        if kind == "l":          # line segment: (type, p1, p2)
            pts.append([round(item[1].x, 3), round(item[1].y, 3)])
            pts.append([round(item[2].x, 3), round(item[2].y, 3)])
        elif kind == "c":        # cubic bezier: (type, p1, p2, p3, p4)
            pts.extend(sample_bezier(item[1], item[2], item[3], item[4]))
        elif kind == "re":       # rectangle: (type, fitz.Rect)
            r = item[1]
            pts.extend([
                [round(r.x0, 3), round(r.y0, 3)],
                [round(r.x1, 3), round(r.y0, 3)],
                [round(r.x1, 3), round(r.y1, 3)],
                [round(r.x0, 3), round(r.y1, 3)],
            ])
        elif kind == "qu":       # quad: (type, fitz.Quad)
            q = item[1]
            for corner in (q.ul, q.ur, q.lr, q.ll):
                pts.append([round(corner.x, 3), round(corner.y, 3)])
    return pts


# --------------------------------------------------
# Page extraction
# --------------------------------------------------

def extract_page(page: fitz.Page, file_name: str) -> dict:
    pw = round(page.rect.width, 3)
    ph = round(page.rect.height, 3)

    # --- Vector paths ---
    paths = []
    for i, d in enumerate(page.get_drawings()):
        items = d.get("items", [])
        pts = extract_path_points(items)
        if not pts:
            continue

        rect = d.get("rect")
        color = d.get("color")   # stroke color as (r,g,b) or None
        fill  = d.get("fill")    # fill color as (r,g,b) or None
        width = d.get("width") or 0.0
        dashes = d.get("dashes", "") or ""
        is_dashed = dashes.strip() not in ("", "[] 0", "[0] 0")

        paths.append({
            "id": i,
            "width": round(width, 4),
            "color_stroke": [round(c, 4) for c in color] if color else None,
            "color_fill":   [round(c, 4) for c in fill]  if fill  else None,
            "is_closed": bool(d.get("closePath", False)),
            "is_dashed": is_dashed,
            "dash_pattern": dashes.strip(),
            "point_count": len(pts),
            "bbox": [round(v, 3) for v in (rect.x0, rect.y0, rect.x1, rect.y1)] if rect else None,
            "points": pts,
        })

    # --- Text elements ---
    text_elements = []
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                b = span["bbox"]
                cx = round((b[0] + b[2]) / 2, 3)
                cy = round((b[1] + b[3]) / 2, 3)
                is_elev = bool(ELEVATION_RE.match(text))
                elem = {
                    "text": text,
                    "x": cx,
                    "y": cy,
                    "size": round(span["size"], 3),
                    "bbox": [round(v, 3) for v in b],
                    "is_elevation": is_elev,
                }
                if is_elev:
                    elem["elevation_ft"] = float(text)
                text_elements.append(elem)

    n_elev = sum(1 for t in text_elements if t["is_elevation"])
    print(f"  {len(paths)} paths | {len(text_elements)} text elements | {n_elev} elevation labels")

    return {
        "page": file_name,
        "page_width_pts":  pw,
        "page_height_pts": ph,
        "path_count":  len(paths),
        "text_count":  len(text_elements),
        "elev_count":  n_elev,
        "paths": paths,
        "text_elements": text_elements,
    }


# --------------------------------------------------
# PDF + page lookup
# --------------------------------------------------

def parse_page_number(filename: str) -> tuple[str, int]:
    """
    'site_plan_page_3.png' → ('site_plan', 3)
    Returns (stem, 1-indexed page number). Falls back to page 1 if pattern not found.
    """
    m = re.search(r"_page_(\d+)\.png$", filename, re.IGNORECASE)
    if m:
        stem = filename[:m.start()]
        return stem, int(m.group(1))
    # Fallback: strip extension
    return Path(filename).stem, 1


def find_pdf(stem: str) -> Path:
    """Locate the source PDF for a given stem, searching Input/ then project root."""
    for directory in (INPUT_DIR, BASE_DIR):
        for ext in (".pdf", ".PDF"):
            candidate = directory / (stem + ext)
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        f"Could not find '{stem}.pdf' in {INPUT_DIR}/ or project root. "
        "Place the source PDF in the Input/ directory."
    )


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    if not SHEET_CLASS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {SHEET_CLASS_FILE}. Run classify_sheets.py first."
        )

    classifications = json.loads(SHEET_CLASS_FILE.read_text())
    grading_entries = [
        e for e in classifications
        if e.get("sheet_type") in GRADING_TYPES
        and e.get("confidence", 0) >= MIN_CONFIDENCE
    ]

    if not grading_entries:
        seen = {e.get("sheet_type") for e in classifications}
        print(f"No grading pages found. Seen sheet types: {seen}")
        return

    print(f"Found {len(grading_entries)} grading page(s) to process.\n")

    # Group entries by PDF stem so we open each PDF only once
    by_pdf: dict[str, list] = {}
    for entry in grading_entries:
        stem, page_num = parse_page_number(entry["file"])
        by_pdf.setdefault(stem, []).append((page_num, entry))

    results = []
    for stem, pages in by_pdf.items():
        pdf_path = find_pdf(stem)
        print(f"Opening {pdf_path.name} ...")
        doc = fitz.open(str(pdf_path))
        total = doc.page_count

        for page_num, entry in sorted(pages):
            idx = page_num - 1
            if idx < 0 or idx >= total:
                print(f"  Warning: page {page_num} out of range (PDF has {total} pages) — skipping")
                continue
            print(f"[page {page_num}/{total}] {entry['file']}")
            page = doc[idx]
            result = extract_page(page, entry["file"])
            result["sheet_type"] = entry.get("sheet_type")
            results.append(result)

        doc.close()

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")
    total_paths = sum(r["path_count"] for r in results)
    total_elev  = sum(r["elev_count"]  for r in results)
    print(f"Total: {total_paths} paths, {total_elev} elevation labels across {len(results)} page(s)")


if __name__ == "__main__":
    main()
