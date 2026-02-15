# pdf_to_png.py

from pathlib import Path
from pdf2image import convert_from_path

# Folder containing PDFs
INPUT_DIR = Path("Input")

# Output PNGs will be saved in same folder
OUTPUT_DIR = INPUT_DIR

# MacPorts poppler location
POPPLER_PATH = "/opt/local/bin"

# Find all PDFs
pdf_files = list(INPUT_DIR.glob("*.pdf"))

if not pdf_files:
    print("No PDFs found in Input folder.")
    exit()

print(f"Found {len(pdf_files)} PDF(s)\n")

for pdf_path in pdf_files:

    print(f"Converting: {pdf_path.name}")

    try:

        pages = convert_from_path(
            pdf_path,
            dpi=300,
            poppler_path=POPPLER_PATH
        )

        for i, page in enumerate(pages):

            output_file = OUTPUT_DIR / f"{pdf_path.stem}_page_{i+1}.png"

            page.save(output_file, "PNG")

            print(f"Saved: {output_file.name}")

    except Exception as e:

        print(f"ERROR converting {pdf_path.name}: {e}")

print("\nDone.")
