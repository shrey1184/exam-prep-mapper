# backend/main.py
import os, sys
sys.path.insert(0, "ingestion")
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import ConnectionPool
from search import search

load_dotenv()
OWNER = "dev-user"   # replaced by the logged-in user later

pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5, open=True)

app = FastAPI(title="Study Map API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}


@app.get("/topics")
def topics():
    with pool.connection() as conn:
        rows = conn.execute(
            """select id, unit, section_title, page_start from chunks
               where owner_id=%s order by unit, page_start""", (OWNER,)).fetchall()
    out = {}
    for id_, unit, title, page in rows:
        out.setdefault(unit, []).append({"id": id_, "title": title, "page": page})
    return out


@app.get("/topics/{chunk_id}")
def topic(chunk_id: int):
    with pool.connection() as conn:
        r = conn.execute(
            """select c.id, c.unit, c.section_title, c.page_start, c.text,
                      i.key_points, i.likely_questions
               from chunks c left join topic_insights i on i.chunk_id = c.id
               where c.id=%s and c.owner_id=%s""", (chunk_id, OWNER)).fetchone()
    if not r:
        raise HTTPException(404, "Topic not found")
    return {"id": r[0], "unit": r[1], "title": r[2], "page": r[3], "text": r[4],
            "key_points": r[5] or [], "likely_questions": r[6] or []}


@app.get("/search")
def search_api(q: str, top: int = 5):
    with pool.connection() as conn:
        results = search(conn, q, top=top)
        ids = [r[0] for r in results]
        snippets = dict(conn.execute(
            "select id, left(text, 200) from chunks where id = any(%s)", (ids,)).fetchall())
    return [{"id": i, "unit": u, "title": t, "page": p, "snippet": snippets[i]}
            for i, u, t, p in results]