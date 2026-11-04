# ingestion/pipeline.py
import os, re, sys, time, collections
from pathlib import Path
import pdfplumber, psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv
from embed_and_load import embed, vec
from ocr_scanned import ocr_page, page_png
from generate_insights import generate

load_dotenv()
MIN_CHARS = 80
HEADING_RE = re.compile(r"^(\d{1,2})\.\s+([A-Z].{2,100})$")

GENERIC_PROMPT = """Transcribe this scanned page of study notes into clean markdown.
Rules:
- The FIRST line must be the page's main heading or title, with no '#'. If there is none, write a short descriptive title.
- Keep reading order. Use '###' for sub-headings.
- Convert tables to markdown tables.
- For diagrams, write one line: [Diagram: short description of the flow or labels].
- Ignore watermarks, page numbers, scanner stamps and repeated headers or footers.
- Transcribe only what is on the page. Do not add, fix or explain anything."""


def set_progress(conn, doc_id, status, progress, error=None):
    conn.execute("update documents set status=%s, progress=%s, error=%s where id=%s",
                 (status, progress, error, doc_id))
    conn.commit()


def read_pages(conn, doc_id, path):
    cache = Path("data/processed") / f"doc_{doc_id}"      # OCR results, so a retry doesn't repay
    cache.mkdir(parents=True, exist_ok=True)
    pages = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            scanned = len(text) < MIN_CHARS
            if scanned:
                f = cache / f"page_{i:03d}.md"
                if f.exists():
                    text = f.read_text()
                else:
                    text = ocr_page(page_png(page), prompt=GENERIC_PROMPT)
                    f.write_text(text)
                    time.sleep(4)                          # free-tier rate limit
            pages.append({"page": i, "text": text, "scanned": scanned})
            set_progress(conn, doc_id, "parsing", int(30 * i / total))
    return pages


def strip_repeats(pages):
    """Drop running headers/footers: lines that repeat on at least half the text pages."""
    text_pages = [p for p in pages if not p["scanned"]]
    if len(text_pages) < 4:
        return pages
    norm = lambda l: re.sub(r"\d+", "#", l.strip().lower())   # 'PAGE 7' and 'PAGE 8' count as one
    counts = collections.Counter()
    for p in text_pages:
        for k in {norm(l) for l in p["text"].splitlines() if l.strip()}:
            counts[k] += 1
    limit = max(3, len(text_pages) // 2)
    repeated = {k for k, c in counts.items() if c >= limit}
    out = []
    for p in pages:
        if p["scanned"]:
            out.append(p)
            continue
        lines = [l for l in p["text"].splitlines() if norm(l) not in repeated]
        out.append({**p, "text": "\n".join(lines).strip()})
    return out


def numbered_sections(pages):
    """'1. Title', '2. Title' ... accepted only in sequence, so stray numbered lines don't split."""
    sections, current, expected = [], None, 1
    for p in pages:
        for line in p["text"].splitlines():
            line = line.strip()
            if not line:
                continue
            m = HEADING_RE.match(line)
            if m and int(m.group(1)) == expected:
                if current:
                    sections.append(current)
                current = {"title": m.group(2).strip(), "page_start": p["page"],
                           "page_end": p["page"], "lines": []}
                expected += 1
                continue
            if current:
                current["lines"].append(line)
                current["page_end"] = p["page"]
    if current:
        sections.append(current)
    for s in sections:
        s["text"] = "\n".join(s.pop("lines"))
    return sections


def page_sections(pages):
    """Fallback: one section per page, titled from its first line."""
    out = []
    for p in pages:
        if not p["text"].strip():
            continue
        first, _, rest = p["text"].strip().partition("\n")
        out.append({"title": first.lstrip("#").strip()[:80], "page_start": p["page"],
                    "page_end": p["page"], "text": rest.strip() or first})
    return out


def build_sections(pages):
    if not any(p["scanned"] for p in pages):
        secs = numbered_sections(pages)
        if len(secs) >= 3:
            return secs
    return page_sections(pages)


def split_long(sections, limit=6000):
    out = []
    for s in sections:
        if len(s["text"]) <= limit:
            out.append(s)
            continue
        parts, cur = [], ""
        for para in s["text"].split("\n\n"):
            if cur and len(cur) + len(para) > limit:
                parts.append(cur)
                cur = ""
            cur += para + "\n\n"
        if cur.strip():
            parts.append(cur)
        for n, part in enumerate(parts, start=1):
            out.append({**s, "title": f"{s['title']} (part {n})", "text": part.strip()})
    return out


def run(doc_id: int):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "select owner_id, stored_path, label from documents where id=%s", (doc_id,)).fetchone()
        if not row:
            raise SystemExit(f"document {doc_id} not found")
        owner, path, label = row
        try:
            set_progress(conn, doc_id, "parsing", 0)
            pages = strip_repeats(read_pages(conn, doc_id, path))
            sections = split_long(build_sections(pages))
            if not sections:
                raise ValueError("No readable text found in this PDF")

            set_progress(conn, doc_id, "embedding", 30)
            vectors = embed([f"{label} - {s['title']}\n{s['text']}" for s in sections])

            conn.execute("delete from topics where document_id=%s", (doc_id,))   # makes re-runs safe
            conn.execute("delete from chunks where document_id=%s", (doc_id,))
            chunk_ids = []
            for s, v in zip(sections, vectors):
                cid = conn.execute(
                    """insert into chunks (document_id, owner_id, unit, section_title,
                                           page_start, page_end, text, embedding)
                       values (%s,%s,%s,%s,%s,%s,%s,%s::vector) returning id""",
                    (doc_id, owner, label, s["title"], s["page_start"], s["page_end"],
                     s["text"], vec(v))).fetchone()[0]
                chunk_ids.append(cid)
                conn.execute(
                    "insert into topics (owner_id, document_id, unit, name, source) values (%s,%s,%s,%s,'notes')",
                    (owner, doc_id, label, s["title"]))
            conn.commit()
            set_progress(conn, doc_id, "insights", 50)

            for n, (cid, s) in enumerate(zip(chunk_ids, sections), start=1):
                try:                                  # insights are a bonus: search works without them
                    data, model = generate(s["title"], s["text"])
                    conn.execute(
                        """insert into topic_insights (chunk_id, key_points, likely_questions, model)
                           values (%s,%s,%s,%s) on conflict (chunk_id) do nothing""",
                        (cid, Jsonb(data["key_points"]), Jsonb(data["likely_questions"]), model))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"  insights skipped for '{s['title']}': {str(e)[:80]}", flush=True)
                set_progress(conn, doc_id, "insights", 50 + int(50 * n / len(sections)))
                time.sleep(2)

            set_progress(conn, doc_id, "ready", 100)
        except Exception as e:
            conn.rollback()
            set_progress(conn, doc_id, "failed", 0, str(e)[:500])
            raise


if __name__ == "__main__":
    run(int(sys.argv[1]))