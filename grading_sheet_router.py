"""grading_sheet_router.py

Reads outputs/sheet_classification.json, filters for SITE_GRADING_PLAN entries
with confidence >= 0.5, and writes outputs/grading_pages.json with resolved paths.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "Input"
CLASSIFICATION_FILE = BASE_DIR / "outputs" / "sheet_classification.json"
OUTPUT_FILE = BASE_DIR / "outputs" / "grading_pages.json"

CONFIDENCE_THRESHOLD = 0.5


def main():
    if not CLASSIFICATION_FILE.exists():
        raise FileNotFoundError(f"Missing {CLASSIFICATION_FILE}. Run classify_sheets.py first.")

    classifications = json.loads(CLASSIFICATION_FILE.read_text())

    grading_pages = []
    for entry in classifications:
        if (
            entry.get("sheet_type") == "SITE_GRADING_PLAN"
            and entry.get("confidence", 0.0) >= CONFIDENCE_THRESHOLD
        ):
            filename = entry["file"]
            full_path = INPUT_DIR / filename
            grading_pages.append({
                "file": filename,
                "path": str(full_path),
                "confidence": entry["confidence"],
            })

    print(f"Found {len(grading_pages)} grading sheet(s) from {len(classifications)} classified pages")
    for p in grading_pages:
        print(f"  {p['file']}  (confidence={p['confidence']:.2f})")

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(grading_pages, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
