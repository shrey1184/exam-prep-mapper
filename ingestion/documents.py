# ingestion/documents.py
import hashlib, io, re
from pathlib import Path
import pdfplumber

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 60
MAX_DOCS_PER_USER = 10
UPLOAD_DIR = Path("data/uploads")


def register_document(conn, owner: str, filename: str, data: bytes, label: str | None = None):
    """Validate and store an uploaded PDF. Returns (doc_id, created)."""
    # owner ends up in a file path, so it must be a plain token (blocks '../' tricks)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", owner):
        raise ValueError("Invalid user id")
    if len(data) > MAX_BYTES:
        raise ValueError("File is larger than 20 MB")
    if not data.startswith(b"%PDF"):
        raise ValueError("Only PDF files are supported")
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
    except Exception:
        raise ValueError("Could not read this PDF")
    if pages == 0 or pages > MAX_PAGES:
        raise ValueError(f"PDF must have 1 to {MAX_PAGES} pages (this one has {pages})")

    file_hash = hashlib.sha256(data).hexdigest()
    existing = conn.execute(
        "select id from documents where owner_id=%s and file_hash=%s", (owner, file_hash)
    ).fetchone()
    if existing:
        return existing[0], False            # same file uploaded twice: reuse, don't reprocess

    count = conn.execute("select count(*) from documents where owner_id=%s", (owner,)).fetchone()[0]
    if count >= MAX_DOCS_PER_USER:
        raise ValueError(f"Upload limit reached ({MAX_DOCS_PER_USER} documents)")

    path = UPLOAD_DIR / owner / f"{file_hash}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    name = Path(filename).name[:200]
    doc_id = conn.execute(
        """insert into documents
           (owner_id, doc_type, filename, file_hash, status, label, stored_path, page_count, progress)
           values (%s,'notes',%s,%s,'queued',%s,%s,%s,0) returning id""",
        (owner, name, file_hash, (label or Path(name).stem)[:100], str(path), pages),
    ).fetchone()[0]
    conn.commit()
    return doc_id, True