# ingestion/search.py
import os, re, sys
import psycopg
from dotenv import load_dotenv
from embed_and_load import embed, vec   # reuse the embedding code

load_dotenv()
OWNER = "dev-user"
STOP = {"what", "is", "are", "the", "a", "an", "of", "in", "to", "and", "or", "how",
        "do", "does", "between", "difference", "explain", "about", "with", "for", "vs"}


def vector_search(conn, qvec, k=10):
    return conn.execute(
        """select id, unit, section_title, page_start
           from chunks where owner_id=%s
           order by embedding <=> %s::vector limit %s""",
        (OWNER, vec(qvec), k),
    ).fetchall()


def keyword_search(conn, query, k=10):
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in STOP]
    if not words:
        return []
    tsq = " | ".join(words)   # OR semantics: natural questions rarely match every word
    return conn.execute(
        """select id, unit, section_title, page_start
           from chunks
           where owner_id=%s and tsv @@ to_tsquery('english', %s)
           order by ts_rank(tsv, to_tsquery('english', %s)) desc limit %s""",
        (OWNER, tsq, tsq, k),
    ).fetchall()


def rrf(lists, weights, k=60):
    scores, rows = {}, {}
    for lst, w in zip(lists, weights):
        for rank, row in enumerate(lst, start=1):
            scores[row[0]] = scores.get(row[0], 0) + w / (k + rank)
            rows[row[0]] = row
    return [rows[i] for i in sorted(scores, key=scores.get, reverse=True)]

def search(conn, query, qvec=None, mode="hybrid", top=5):
    if mode in ("hybrid", "vector") and qvec is None:
        qvec = embed([query], task="RETRIEVAL_QUERY")[0]
    v = vector_search(conn, qvec) if mode in ("hybrid", "vector") else []
    kw = keyword_search(conn, query) if mode in ("hybrid", "keyword") else []
    if mode == "vector":
        return v[:top]
    if mode == "keyword":
        return kw[:top]
    return rrf([v, kw], weights=[3, 1])[:top]

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "elements of communication"
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for _id, unit, title, page in search(conn, q):
            print(f"{unit} | {title} (p{page})")