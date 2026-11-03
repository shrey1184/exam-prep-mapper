# scripts/eval_search.py
import os, sys
sys.path.insert(0, "ingestion")
import psycopg
from dotenv import load_dotenv
from embed_and_load import embed
from search import search

load_dotenv()

# (query, unit or None, acceptable title substrings)
TESTS = [
    ("What are the elements of communication?", "Unit 1", ["Elements of Communication"]),
    ("Steps in the process of communication with feedback", "Unit 1", ["Process of Communication"]),
    ("What is brevity in communication?", "Unit 1", ["Brevity"]),
    ("Tips to achieve clarity", "Unit 1", ["Clarity"]),
    ("What is unity in a message?", "Unit 1", ["Unity"]),
    ("Scope of communication in different fields", "Unit 1", ["Scope"]),
    ("Difference between hearing and listening", "Unit 2", ["Listening Skills"]),
    ("Ethos logos pathos", "Unit 2", ["Persuasion"]),
    ("What is proxemics?", "Unit 2", ["Major Categories of Non-verbal"]),
    ("Types of barriers semantic psychological physical", "Unit 2", ["Barriers to Communication", "Language, Psychological"]),
    ("Direct vs indirect approach for bad news", "Unit 2", ["Bad News"]),
    ("Position versus interest in negotiation", "Unit 2", ["Negotiation Skills"]),
    ("Assertive passive aggressive styles", "Unit 2", ["Interpersonal"]),
    ("How to overcome barriers to listening", "Unit 2", ["Barriers to Listening"]),
    ("Culture and hierarchy differences in communication", "Unit 2", ["Culture and Communication"]),
    ("Challenges of communication in a globalized world", None, ["Global"]),
    ("why do people misunderstand each other at work", "Unit 2", ["Barriers"]),
    ("how do I say no to a request politely", "Unit 2", ["Bad News", "Bad-News"]),
    ("saying the same thing in fewer words", "Unit 1", ["Brevity"]),
    ("how should I behave when talking to people from other countries", None, ["Culture", "Global"]),
    ("body language during presentations", "Unit 2", ["Non-verbal"]),
    ("what makes a speaker believable", "Unit 2", ["Persuasion"]),
]


def hit_rank(results, unit, subs):
    for i, (_id, u, title, _p) in enumerate(results, start=1):
        if (unit is None or u == unit) and any(s.lower() in title.lower() for s in subs):
            return i
    return None


with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    qvecs = embed([t[0] for t in TESTS], task="RETRIEVAL_QUERY")
    for mode in ("vector", "keyword", "hybrid"):
        hits, fails = 0, []
        for (q, unit, subs), qv in zip(TESTS, qvecs):
            res = search(conn, q, qvec=qv, mode=mode, top=5)
            r = hit_rank(res, unit, subs)
            if r and r <= 3:
                hits += 1
            else:
                fails.append((q, r))
        print(f"{mode:<8} top-3: {hits}/{len(TESTS)}")
        for q, r in fails:
            print(f"    miss: {q}  (rank: {r or 'not in top 5'})")