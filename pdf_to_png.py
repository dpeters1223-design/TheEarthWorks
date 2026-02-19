# pdf_to_png.py
# Converts each page of every PDF in Input/ to a PNG using PyMuPDF (no poppler needed).
# Output: Input/{stem}_page_1.png, Input/{stem}_page_2.png, ...

from pathlib import Path
import fitz  # PyMuPDF

INPUT_DIR  = Path("Input")
OUTPUT_DIR = INPUT_DIR
DPI        = 300

pdf_files = list({p.resolve() for p in INPUT_DIR.glob("*.pdf")} |
                 {p.resolve() for p in INPUT_DIR.glob("*.PDF")})

if not pdf_files:
    print("No PDFs found in Input/ folder.")
    exit()

print(f"Found {len(pdf_files)} PDF(s)\n")

for pdf_path in pdf_files:
    print(f"Converting: {pdf_path.name}")
    try:
        doc = fitz.open(str(pdf_path))
        mat = fitz.Matrix(DPI / 72, DPI / 72)   # scale factor for target DPI
        for i in range(doc.page_count):
            page = doc[i]
            pix  = page.get_pixmap(matrix=mat)
            out  = OUTPUT_DIR / f"{pdf_path.stem}_page_{i + 1}.png"
            pix.save(str(out))
            print(f"  Saved: {out.name}  ({pix.width}×{pix.height}px)")
        doc.close()
    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone.")
