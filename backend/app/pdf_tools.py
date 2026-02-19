from pathlib import Path
import fitz

def get_page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    n = doc.page_count
    doc.close()
    return n

def render_page_png(pdf_path: Path, page_number: int, output_path: Path, dpi: int = 150) -> Path:
    doc = fitz.open(str(pdf_path))

    if page_number < 1 or page_number > doc.page_count:
        doc.close()
        raise ValueError(f"page_number out of range: {page_number}")

    page = doc.load_page(page_number - 1)

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    pix = page.get_pixmap(matrix=mat, alpha=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(output_path))

    doc.close()
    return output_path
