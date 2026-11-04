# scripts/test_pipeline.py
import os, sys
sys.path.insert(0, "ingestion")
from pathlib import Path
import psycopg
from dotenv import load_dotenv
from documents import register_document
from pipeline import run

load_dotenv()
pdf, owner = sys.argv[1], sys.argv[2]
label = sys.argv[3] if len(sys.argv) > 3 else None

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    doc_id, created = register_document(conn, owner, Path(pdf).name, Path(pdf).read_bytes(), label)
print("document", doc_id, "(new)" if created else "(already uploaded)", flush=True)
run(doc_id)
print("done")