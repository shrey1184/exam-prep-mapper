# Study Map (hybridrag)

Upload your class notes, get a topic map and instant search over them. No chat window: the product is the topic list, the search box and the per-topic view.

Later versions add past-paper (PYQ) uploads, which unlock a frequency heatmap showing which topics matter most.

## Status

| Piece | State |
|---|---|
| Postgres + pgvector schema (Supabase) | Done |
| PDF text extraction, per-page scan detection | Done |
| Section splitting for text PDFs (Unit 2) | Done, 19/19 sections |
| Vision-LLM OCR for scanned PDFs (Unit 1) | Done, 13/13 pages |
| Embeddings and loading into `chunks` | Done, 32 chunks |
| Hybrid search (vector + keyword, RRF) | Working, being tuned |
| Retrieval eval script | Done, 22 queries |
| FastAPI endpoints (`/topics`, `/topics/{id}`, `/search`) | Done, `/topics` speed to check |
| Per-topic key points and likely questions | Next |
| Private uploads, PYQ mapping, heatmap, shared pool | Planned |

Test data: two real notes files for AL301 Technical Communication (RGPV), Unit 1 (scanned images) and Unit 2 (text PDF).

## How it works

```
notes PDF
  -> parse_pdf.py        extract text per page, flag pages with too little text as scans
  -> split_sections.py   text PDFs: strip repeating headers, split on numbered headings
  -> ocr_scanned.py      scanned PDFs: page image -> Gemini vision -> markdown, one section per page
  -> embed_and_load.py   embed each section (768-dim), store in chunks + topics
  -> search.py           vector search + keyword search, merged with reciprocal rank fusion
  -> backend/main.py     FastAPI endpoints for the frontend
```

RAG here is indexing, not training. Adding a new document means parse, embed and insert. Nothing about the models changes.

## Stack

- Python 3.14, venv in `.venv`
- Postgres with pgvector and `tsvector` on Supabase (use the **Session pooler** connection string, the direct host is IPv6-only)
- Gemini API for OCR (vision) and embeddings (`gemini-embedding-001`, 768 dimensions)
- FastAPI + uvicorn
- `pdfplumber` for PDF parsing
- Frontend: to be generated, will call the API below

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install pdfplumber "psycopg[binary]" python-dotenv fastapi uvicorn google-genai pillow
```

Create `.env` (never commit it):

```
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
GEMINI_API_KEY=your_key
# optional
EMBED_MODEL=gemini-embedding-001
```

In the Supabase SQL editor, run `create extension if not exists vector;` first, then the schema below.

## Database schema

```sql
create table documents (
  id serial primary key,
  owner_id text not null,
  doc_type text not null default 'notes',   -- notes | pyq | syllabus
  filename text not null,
  file_hash text not null,
  status text default 'queued',             -- queued | parsing | ready | failed
  error text,
  created_at timestamptz default now(),
  unique (owner_id, file_hash)
);

create table chunks (
  id serial primary key,
  document_id int references documents(id) on delete cascade,
  owner_id text not null,
  unit text,
  section_title text,
  page_start int,
  page_end int,
  text text not null,
  embedding vector(768),
  tsv tsvector generated always as (to_tsvector('english', text)) stored
);

create table topics (
  id serial primary key,
  owner_id text not null,
  document_id int references documents(id) on delete cascade,
  unit text,
  name text not null,
  parent_id int references topics(id),
  source text default 'notes'               -- notes | syllabus
);

create index on chunks using gin (tsv);
create index on chunks (owner_id);
```

Everything is scoped by `owner_id` so one user's files never appear in another's results. Right now the owner is the placeholder `dev-user`.

## Project structure

```
hybridrag/
├── README.md
├── .env                      # secrets, not committed
├── data/
│   ├── raw/notes/            # unit1.pdf, unit2.pdf
│   └── processed/            # parsed JSON/TXT, unit*_sections.json, unit1_ocr/page_NN.md
├── ingestion/
│   ├── parse_pdf.py          # text extraction + scan detection
│   ├── split_sections.py     # numbered-heading splitter for text PDFs
│   ├── ocr_scanned.py        # Gemini vision OCR for scanned pages (cached per page)
│   ├── embed_and_load.py     # embeddings + insert into chunks/topics (skips files already loaded)
│   └── search.py             # vector, keyword and hybrid (RRF) search
├── backend/
│   └── main.py               # FastAPI app
└── scripts/
    ├── test_db.py            # check the database connection
    ├── debug_ocr.py          # time text, render and image calls
    ├── list_models.py        # list Gemini models your key can use
    ├── try_models.py         # test which flash models respond right now
    └── eval_search.py        # retrieval eval: top-1 / top-3 per mode
```

## Running the pipeline

From the project root, with the venv active:

```bash
python ingestion/parse_pdf.py           # writes data/processed/*.json and *.txt
python ingestion/split_sections.py      # unit2 -> unit2_sections.json (expect 19)
python ingestion/ocr_scanned.py         # unit1 -> unit1_sections.json (expect 13)
python ingestion/embed_and_load.py      # embeds and loads all sections
```

Each step is safe to re-run. OCR caches finished pages, and the loader skips files already in the database (matched by file hash).

## API

```bash
uvicorn backend.main:app --reload
```

Interactive docs at `http://127.0.0.1:8000/docs`.

| Endpoint | Returns |
|---|---|
| `GET /topics` | Sections grouped by unit: `{ "Unit 1": [{id, title, page}], ... }` |
| `GET /topics/{id}` | Full text of one section |
| `GET /search?q=...&top=5` | Ranked sections with a 200-character snippet |

## Evaluating search

```bash
python scripts/eval_search.py
```

Runs 22 queries (16 close to the section titles, 6 paraphrased) in vector, keyword and hybrid modes and prints top-1 and top-3 scores plus misses. Rerun it after any change to chunking, the embedding model or retrieval.

Latest results:

| Mode | Top-1 | Top-3 |
|---|---|---|
| vector | 22/22 | 22/22 |
| keyword | 10/22 | 18/22 |
| hybrid (equal weights) | 21/22 | 21/22 |

Keyword search misses paraphrased queries. Hybrid lost one query to keyword noise, so the next change is weighting vector results higher in the merge.

### Pending fix: weighted RRF

In `ingestion/search.py`, `rrf` must take weights, and the call in `search` must pass them:

```python
def rrf(lists, weights, k=60):
    scores, rows = {}, {}
    for lst, w in zip(lists, weights):
        for rank, row in enumerate(lst, start=1):
            scores[row[0]] = scores.get(row[0], 0) + w / (k + rank)
            rows[row[0]] = row
    return [rows[i] for i in sorted(scores, key=scores.get, reverse=True)]

# in search():
return rrf([v, kw], weights=[3, 1])[:top]
```

If only `rrf` is changed and the call is not, you get `TypeError: rrf() missing 1 required positional argument: 'weights'`.

## Known issues and notes

- **Gemini model names change often and overload often.** `503 UNAVAILABLE` means the model is busy, `429` means free-tier quota. Run `scripts/try_models.py` to see which models respond, and set the working one in the scripts. Always set a client timeout so a call cannot hang.
- **Free-tier quota:** pause between OCR pages and wait about 60 seconds after a 429. Cached pages are never re-sent.
- **Hub chunks:** "Quick Revision Sheet" sections are close to every query, so they show up in lower ranks. Down-weight or filter them later.
- **No relevance cutoff yet.** Vector search always returns its top k, so weak matches need a threshold before they are shown as answers.
- **`/topics` may be slow** because each request opens a new database connection. A connection pool fixes it.
- **Filenames:** keep them simple (`unit1.pdf`, `unit2.pdf`). Cache folders and output files are named after the PDF.

## Roadmap

1. Tune hybrid weights, confirm `/topics` speed, add a relevance cutoff
2. Per-topic key points and likely exam questions, generated once and cached (`topic_insights` table)
3. Private uploads: upload endpoint, background job queue, `documents.status` progress, per-user `owner_id`, upload limits
4. PYQ upload: split into questions, map to topics with a confidence check, `unmapped` bucket for review
5. Frequency heatmap and "last 3 days" planner
6. Optional shared community pool: dedupe, moderation, takedown path
7. Frontend (AI-generated) on top of the API