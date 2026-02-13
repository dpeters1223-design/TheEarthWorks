# pdf_to_png.py
from pdf2image import convert_from_path
from pathlib import Path

PDF_PATH = "input/site_plan.pdf"
OUTPUT_DIR = Path("pages")
DPI = 300

OUTPUT_DIR.mkdir(exist_ok=True)

pages = convert_from_path(PDF_PATH, dpi=DPI)

for i, page in enumerate(pages, start=1):
    out = OUTPUT_DIR / f"page_{i:03}.png"
    page.save(out, "PNG")
    print(f"Wrote {out}")

print(f"Rendered {len(pages)} pages")
