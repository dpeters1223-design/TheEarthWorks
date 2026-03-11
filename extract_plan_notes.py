"""extract_plan_notes.py

Scans grading plan pages, TITLE_SHEET, GENERAL_NOTES, and DETAILS pages for
construction specification text: strip depth, material layer thicknesses, and
area callouts.

Output: outputs/plan_notes.json
"""

import base64
import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI  # used with Ollama's OpenAI-compatible endpoint
from PIL import Image

BASE_DIR           = Path(__file__).parent
SHEET_CLASS_FILE   = BASE_DIR / "outputs" / "sheet_classification.json"
OUTPUT_FILE        = BASE_DIR / "outputs" / "plan_notes.json"
INPUT_DIR          = BASE_DIR / "Input"

# Sheet types to scan for plan notes
NOTE_SHEET_TYPES = {
    "BASE_GRADING_PLAN",
    "FINAL_GRADING_PLAN",
    "SITE_GRADING_PLAN",
    "EXISTING_CONDITIONS_PLAN",
    "TITLE_SHEET",
    "GENERAL_NOTES",
    "GEOTECH_SUMMARY",
    "DETAILS",
}

MAX_RENDER_PX = 2048

load_dotenv(BASE_DIR / ".env")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
MODEL = os.getenv("OLLAMA_MODEL", "gemma3:27b")


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def resize_to_max(img: Image.Image, max_px: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_px:
        return img
    factor = max_px / longest
    return img.resize((round(w * factor), round(h * factor)), Image.LANCZOS)


def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            lines = inner.split("\n", 1)
            if len(lines) == 2 and not lines[0].strip().startswith("{"):
                inner = lines[1]
            text = inner
    return text.strip()


# --------------------------------------------------
# Vision prompt
# --------------------------------------------------

PROMPT = """
You are analyzing a civil engineering plan sheet for a landfill closure or grading project.

Your task: find any construction specifications, general notes, or callout text that mentions:

1. STRIPPING DEPTH — phrases like "strip 6 inches of topsoil", "remove 0.5 ft of organic material",
   "topsoil stripping depth = 6 in", "strip and stockpile topsoil to 6-inch depth", etc.

2. MATERIAL LAYER THICKNESSES — specifications for placed material layers such as:
   "18-inch infiltration layer", "6-inch vegetative support layer", "12-inch intermediate cover",
   "geomembrane liner", "drainage layer 12\"", etc. Include zone info if mentioned
   (e.g. "within cap area", "outside cap", "seeding area").

3. AREA CALLOUTS — any stated areas such as "229,476 SF intermediate cover area",
   "cap area = 5.27 acres", "14,202 SF seeding area", "grading limits = 243,678 SF", etc.

4. ZONE DESCRIPTIONS — descriptions of project zones like "cap area", "intermediate cover area",
   "outside cap seeding area", "topsoil restoration area", etc.

Scan the ENTIRE image carefully — notes may be in small text boxes, legend areas, or general notes
sections anywhere on the sheet.

Return ONLY valid JSON — no markdown fences, no text outside the object:
{
  "strip_depth_in": <number or null>,
  "strip_depth_note": "<exact text seen, or null>",
  "material_layers": [
    {
      "name": "<layer name>",
      "depth_in": <number or null>,
      "zone": "<zone description or null>",
      "note": "<exact text seen>"
    }
  ],
  "areas_mentioned": [
    {
      "description": "<what area this is>",
      "value_sf": <number or null>,
      "value_acres": <number or null>,
      "note": "<exact text seen>"
    }
  ],
  "assumptions": ["<note>", ...]
}

If nothing relevant is found on this sheet, return the structure with null/empty values.
"""


# --------------------------------------------------
# Per-page extraction
# --------------------------------------------------

def extract_page_notes(client: OpenAI, image_path: str, page_name: str) -> dict:
    img = Image.open(image_path)
    render_img = resize_to_max(img, MAX_RENDER_PX)

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": image_to_data_url(render_img)}},
            ],
        }],
    )

    raw = (resp.choices[0].message.content or "").strip()

    base = {
        "page": page_name,
        "strip_depth_in": None,
        "strip_depth_note": None,
        "material_layers": [],
        "areas_mentioned": [],
        "assumptions": [],
    }

    if not raw:
        base["assumptions"] = ["Model returned no text"]
        return base

    cleaned = clean_json_text(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        base["assumptions"] = [f"JSON parse error: {exc}", cleaned[:300]]
        return base

    base.update({
        "strip_depth_in":   data.get("strip_depth_in"),
        "strip_depth_note": data.get("strip_depth_note"),
        "material_layers":  data.get("material_layers", []),
        "areas_mentioned":  data.get("areas_mentioned", []),
        "assumptions":      data.get("assumptions", []),
    })
    return base


# --------------------------------------------------
# Merge / consolidate across pages
# --------------------------------------------------

def merge_results(page_results: list) -> dict:
    """Merge multi-page extraction into a single authoritative plan_notes record."""

    # Strip depth: take first non-null value found (prefer grading plan pages)
    strip_depth_in     = None
    strip_depth_source = None
    for r in page_results:
        if r.get("strip_depth_in") is not None:
            strip_depth_in     = r["strip_depth_in"]
            strip_depth_source = r["page"]
            break

    # Material layers: collect all, deduplicate by name (keep first seen)
    seen_names = {}
    all_layers = []
    for r in page_results:
        for layer in r.get("material_layers", []):
            name = (layer.get("name") or "").strip().lower()
            if name and name not in seen_names:
                seen_names[name] = True
                all_layers.append({**layer, "source_page": r["page"]})

    # Areas: collect all unique descriptions
    all_areas = []
    seen_descs = set()
    for r in page_results:
        for area in r.get("areas_mentioned", []):
            desc = (area.get("description") or "").strip().lower()
            if desc and desc not in seen_descs:
                seen_descs.add(desc)
                all_areas.append({**area, "source_page": r["page"]})

    # Build areas_mentioned_sf dict for downstream scripts
    areas_sf = {}
    for area in all_areas:
        key = (area.get("description") or "area").strip()
        val = area.get("value_sf")
        if val is None and area.get("value_acres"):
            val = round(area["value_acres"] * 43560.0)
        if val is not None:
            # Normalize common keys
            k_lower = key.lower()
            if "cap" in k_lower and "outside" not in k_lower and "seed" not in k_lower:
                areas_sf["cap_area"] = val
            elif "seed" in k_lower or ("outside" in k_lower and "cap" in k_lower):
                areas_sf["seeding_area"] = val
            elif "disturb" in k_lower or "grading limit" in k_lower:
                areas_sf["total_disturbed_area"] = val
            else:
                areas_sf[key[:40]] = val

    return {
        "strip_depth_in":      strip_depth_in,
        "strip_depth_source":  strip_depth_source,
        "material_layers":     all_layers,
        "areas_mentioned_sf":  areas_sf,
        "all_areas":           all_areas,
        "assumptions":         [
            "Merged from all note/grading/details pages",
            f"Strip depth from: {strip_depth_source or 'not found'}",
        ],
        "page_results":        page_results,
    }


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    if not SHEET_CLASS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {SHEET_CLASS_FILE}. Run classify_sheets.py first."
        )

    all_sheets = json.loads(SHEET_CLASS_FILE.read_text())
    note_pages = [
        {"file": s["file"], "path": str(INPUT_DIR / s["file"])}
        for s in all_sheets
        if s.get("sheet_type") in NOTE_SHEET_TYPES
    ]

    if not note_pages:
        print("No note/grading/details sheets found in sheet_classification.json.")
        return

    print(f"Scanning {len(note_pages)} page(s) for plan notes ...\n")

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    page_results = []
    for idx, page in enumerate(note_pages):
        print(f"[{idx + 1}/{len(note_pages)}] {page['file']} ...")
        try:
            result = extract_page_notes(client, page["path"], page["file"])
            strip  = result.get("strip_depth_in")
            layers = result.get("material_layers", [])
            areas  = result.get("areas_mentioned", [])
            print(f"  strip_depth={strip} in  layers={len(layers)}  areas={len(areas)}")
            for layer in layers:
                print(f"    layer: {layer.get('name')} @ {layer.get('depth_in')} in "
                      f"({layer.get('zone') or 'no zone'})")
            for area in areas:
                print(f"    area: {area.get('description')} = "
                      f"{area.get('value_sf')} SF / {area.get('value_acres')} ac")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            result = {
                "page": page["file"],
                "strip_depth_in": None,
                "strip_depth_note": None,
                "material_layers": [],
                "areas_mentioned": [],
                "assumptions": [f"Processing error: {exc}"],
            }
        page_results.append(result)

    output = merge_results(page_results)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")

    print(f"\n--- Summary ---")
    print(f"Strip depth : {output['strip_depth_in']} in  (from {output['strip_depth_source']})")
    print(f"Layers found: {len(output['material_layers'])}")
    for layer in output["material_layers"]:
        print(f"  {layer.get('name')} @ {layer.get('depth_in')} in  zone={layer.get('zone')}")
    print(f"Areas found : {output['areas_mentioned_sf']}")


if __name__ == "__main__":
    main()
