# backend/main.py
import os, sys
sys.path.insert(0, "ingestion")
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from search import search

load_dotenv()
OWNER = "dev-user"   # replaced by the logged-in user later

app = FastAPI(title="Study Map API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def db():
    return psycopg.connect(os.environ["DATABASE_URL"])


@app.get("/topics")
def topics():
    with db() as conn:
        rows = conn.execute(
            """select id, unit, section_title, page_start from chunks
               where owner_id=%s order by unit, page_start""", (OWNER,)).fetchall()
    out = {}
    for id_, unit, title, page in rows:
        out.setdefault(unit, []).append({"id": id_, "title": title, "page": page})
    return out


@app.get("/topics/{chunk_id}")
def topic(chunk_id: int):
    with db() as conn:
        r = conn.execute(
            """select id, unit, section_title, page_start, text from chunks
               where id=%s and owner_id=%s""", (chunk_id, OWNER)).fetchone()
    if not r:
        raise HTTPException(404, "Topic not found")
    return {"id": r[0], "unit": r[1], "title": r[2], "page": r[3], "text": r[4]}


@app.get("/search")
def search_api(q: str, top: int = 5):
    with db() as conn:
        results = search(conn, q, top=top)
        ids = [r[0] for r in results]
        snippets = dict(conn.execute(
            "select id, left(text, 200) from chunks where id = any(%s)", (ids,)).fetchall())
    return [{"id": i, "unit": u, "title": t, "page": p, "snippet": snippets[i]}
            for i, u, t, p in results]