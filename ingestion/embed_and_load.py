# ingestion/embed_and_load.py
import os, json, time, math, hashlib
from pathlib import Path
import psycopg
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(timeout=90_000),
)
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
DIM = 768
OWNER = "dev-user"   # placeholder until real users exist

# (sections json, original pdf)
FILES = [
    ("data/processed/unit1_sections.json", "data/raw/notes/unit1.pdf"),
    ("data/processed/unit2_sections.json", "data/raw/notes/unit2.pdf"),
]


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    out = []
    for i in range(0, len(texts), 8):               # small batches for free-tier limits
        batch = texts[i:i + 8]
        for attempt in range(5):
            try:
                r = client.models.embed_content(
                    model=EMBED_MODEL,
                    contents=batch,
                    config=types.EmbedContentConfig(task_type=task, output_dimensionality=DIM),
                )
                for e in r.embeddings:
                    v = e.values
                    n = math.sqrt(sum(x * x for x in v)) or 1.0   # normalise (needed for truncated dims)
                    out.append([x / n for x in v])
                break
            except Exception as ex:
                msg = str(ex)
                if any(c in msg for c in ("429", "500", "503", "504", "UNAVAILABLE")):
                    wait = 60 if "429" in msg else 5 * (attempt + 1)
                    print(f"  embed retry ({msg[:50]}), waiting {wait}s", flush=True)
                    time.sleep(wait)
                else:
                    raise
        else:
            raise RuntimeError("embedding failed after retries")
        time.sleep(2)
    return out


def vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"   # pgvector text format


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for sections_path, pdf_path in FILES:
            sections = json.loads(Path(sections_path).read_text())
            file_hash = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
            filename = Path(pdf_path).name

            exists = conn.execute(
                "select id from documents where owner_id=%s and file_hash=%s",
                (OWNER, file_hash),
            ).fetchone()
            if exists:
                print(f"{filename}: already loaded, skipping")
                continue

            doc_id = conn.execute(
                """insert into documents (owner_id, doc_type, filename, file_hash, status)
                   values (%s,'notes',%s,%s,'parsing') returning id""",
                (OWNER, filename, file_hash),
            ).fetchone()[0]

            # Title is added to the text that gets embedded, so searching by topic name works
            texts = [f"{s['unit']} - {s['title']}\n{s['text']}" for s in sections]
            print(f"{filename}: embedding {len(texts)} chunks...", flush=True)
            vectors = embed(texts)

            for s, v in zip(sections, vectors):
                conn.execute(
                    """insert into chunks
                       (document_id, owner_id, unit, section_title, page_start, page_end, text, embedding)
                       values (%s,%s,%s,%s,%s,%s,%s,%s::vector)""",
                    (doc_id, OWNER, s["unit"], s["title"], s["page_start"], s["page_end"],
                     s["text"], vec(v)),
                )
                conn.execute(
                    "insert into topics (owner_id, document_id, unit, name, source) values (%s,%s,%s,%s,'notes')",
                    (OWNER, doc_id, s["unit"], s["title"]),
                )

            conn.execute("update documents set status='ready' where id=%s", (doc_id,))
            conn.commit()
            print(f"{filename}: loaded {len(sections)} chunks")


if __name__ == "__main__":
    main()