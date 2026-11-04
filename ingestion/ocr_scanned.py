# ingestion/ocr_scanned.py
import os, io, re, json, time, sys
from pathlib import Path
import pdfplumber
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],     http_options=types.HttpOptions(timeout=90_000),
)
MODEL = "gemini-3.6-flash"

PROMPT = """Transcribe this scanned study-notes page into clean markdown.
Rules:
- The FIRST line must be the numbered section title in the yellow banner, e.g. "3. Process of Communication". No '#' on it.
- Keep reading order. Use '###' for sub-headings like "3.1 What is Process of Communication?".
- Convert tables to markdown tables.
- For diagrams, write one line: [Diagram: short description of the flow or labels].
- Ignore the top-left box (AL301 / Semester / RGPV), the page number badge, watermarks (RGPV NOTES HUB) and "Scanned with CamScanner".
- Transcribe only what is on the page. Do not add, fix or explain anything."""


def page_png(page) -> bytes:
    img = page.to_image(resolution=150).original
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()



def ocr_page(png: bytes, prompt: str = PROMPT) -> str:
    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[types.Part.from_bytes(data=png, mime_type="image/png"), PROMPT],
            )
            return resp.text.strip()
        except Exception as e:
            msg = str(e)
            # Retry only temporary problems (rate limit, server overload)
            if any(code in msg for code in ("429", "500", "503", "UNAVAILABLE")):
                print("  retry:", msg[:120])
                time.sleep(5 * (attempt + 1))
            else:
                raise  # 404, bad key, bad request: fail immediately
    raise RuntimeError("OCR failed after retries")

def run(pdf_path: str, unit: str):
    stem = Path(pdf_path).stem
    cache = Path("data/processed") / f"{stem}_ocr"
    cache.mkdir(parents=True, exist_ok=True)

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            f = cache / f"page_{i:02d}.md"
            if f.exists():                       # reuse earlier results
                text = f.read_text()
            else:
                print(f"OCR page {i}/{len(pdf.pages)}")
                text = ocr_page(page_png(page))
                f.write_text(text)
            pages.append({"page": i, "text": text})

    sections = []
    for p in pages:
        first, _, rest = p["text"].partition("\n")
        title = first.strip().lstrip("#").strip()
        m = re.match(r"^(\d{1,2})\.\s*(.+)$", title)
        sections.append({
            "unit": unit,
            "number": int(m.group(1)) if m else p["page"],
            "title": m.group(2).strip() if m else title,
            "page_start": p["page"],
            "page_end": p["page"],
            "text": rest.strip(),
        })

    Path(f"data/processed/{stem}_sections.json").write_text(
        json.dumps(sections, indent=2, ensure_ascii=False))
    for s in sections:
        print(f"{s['number']:>2}. {s['title'][:55]:<55} p{s['page_start']}  {len(s['text'])} chars")

if __name__ == "__main__":
    run("data/raw/notes/unit1.pdf", unit="Unit 1")