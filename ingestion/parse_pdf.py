# ingestion/parse_pdf.py
import pdfplumber, json
from pathlib import Path

MIN_CHARS = 80  # fewer characters than this means the page is probably a scan

def parse_pdf(path: str) -> list[dict]:
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            pages.append({"page": i, "text": text, "needs_ocr": len(text) < MIN_CHARS})
    return pages

if __name__ == "__main__":
    out_dir = Path("data/processed")
    out_dir.mkdir(parents=True, exist_ok=True)

    for pdf in sorted(Path("data/raw/notes").glob("*.pdf")):
        pages = parse_pdf(str(pdf))
        scanned = sum(p["needs_ocr"] for p in pages)
        print(f"{pdf.name}: {len(pages)} pages, {scanned} need OCR")

        (out_dir / f"{pdf.stem}.json").write_text(json.dumps(pages, indent=2, ensure_ascii=False))
        (out_dir / f"{pdf.stem}.txt").write_text(
            "\n\n".join(f"=== PAGE {p['page']} ===\n{p['text']}" for p in pages)
        )