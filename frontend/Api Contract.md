# Study Map: API contract for the frontend

Build a mobile-first web app (students use phones) on top of this API. Three screens: topic map, topic view, search.

**Base URL:** `http://127.0.0.1:8000` (make it one config constant). JSON only. CORS is open. No auth yet.

## Endpoints

### `GET /topics`
All sections grouped by unit. Use it for the home screen.

```json
{
  "Unit 1": [
    { "id": 1, "title": "Introduction to Technical Communication", "page": 1 },
    { "id": 2, "title": "Meaning and Definition of Communication", "page": 2 }
  ],
  "Unit 2": [
    { "id": 14, "title": "Unit 2 at a Glance", "page": 2 }
  ]
}
```
Units arrive in order. Sections within a unit are in page order. Currently 13 sections in Unit 1 and 19 in Unit 2.

### `GET /topics/{id}`
One section with its revision aids. Use it for the topic screen.

```json
{
  "id": 3,
  "unit": "Unit 1",
  "title": "Process of Communication",
  "page": 3,
  "text": "### 3.1 What is Process of Communication?\n\n* Process of communication refers to ...\n\n| Step | Description | Example |\n| --- | --- | --- |\n| 1. Sender (Source) | ... | ... |\n\n[Diagram: Flowchart of steps ...]",
  "key_points": ["Communication is a continuous, dynamic process ...", "..."],
  "likely_questions": ["List and explain the nine steps involved in the process of communication.", "..."]
}
```
- `text` is **markdown**: `###` headings, `*` bullets, pipe tables, and lines like `[Diagram: ...]`, and sometimes circled digits (①②). Render it with a markdown renderer that supports tables. Show `[Diagram: ...]` lines as a small muted callout, not as raw text.
- `key_points` (5 to 7 short bullets) and `likely_questions` (3 to 5) are AI-generated. They can be empty arrays (`[]`) if not generated yet.
- Returns `404` with `{"detail": "Topic not found"}` for an unknown id.

### `GET /search?q=<text>&top=5`
Hybrid search (meaning plus keywords). Takes about 1 to 2 seconds, because the query is embedded on each call.

```json
[
  {
    "id": 18,
    "unit": "Unit 2",
    "title": "Major Categories of Non-verbal Communication",
    "page": 6,
    "snippet": "Category Meaning Example / professional use\nKinesics Body movement: ..."
  }
]
```
- Results are ranked best first. The list is **always up to `top` items, even when nothing is relevant**, because there is no relevance cutoff yet. Don't present results as "answers" or claim "best match". Label the list "Top results".
- `snippet` is the first 200 characters of the section, raw and sometimes starting inside a table. Strip markdown symbols (`|`, `#`, `*`) and collapse whitespace before showing it, or show only the title, unit and page.
- `q` must not be empty. Don't send a request for fewer than 2 characters.

## Screens

**1. Home / topic map (`/`)**
- Search bar at the top (goes to the search screen).
- One collapsible block per unit, with its section count. Each section is a row showing title and "p. N". Tap opens the topic screen.
- Loading: skeleton rows. Error: "Couldn't load your notes" with a Retry button.

**2. Topic view (`/topic/:id`)**
- Header: title, with "Unit 2 · page 10" beneath it (this is the source reference).
- Order: **Key points**, then **Likely questions**, then **Full notes** (collapsed by default, expandable).
- Show a small label by the key points and questions: "AI-generated from your notes. Check against the source page." The generated text can contain mistakes.
- Previous / next section buttons, using the order from `/topics`.
- If `key_points` and `likely_questions` are both empty, hide those blocks and show the notes directly.
- 404: "This topic doesn't exist" with a link home.

**3. Search (`/search?q=`)**
- Debounce input by about 400 ms, or search on Enter. Don't fire on every keystroke, because each search costs an embedding call.
- Show a spinner or skeleton for 1 to 2 seconds. Show each result as title, "Unit · p. N" and a cleaned snippet. Tap opens the topic screen.
- Empty query: show a few example searches ("what is proxemics", "barriers to listening").
- Network error: Retry button.

## Not built yet (don't build screens for these)
Uploading notes, user accounts, past-paper (PYQ) mapping, the frequency heatmap and the exam planner. If you want to hint at them, add one disabled "Upload your notes, coming soon" card on the home screen, nothing more.

## Design notes
- Clean, calm, study-app feel. Large tap targets. Readable body text for long notes.
- Light and dark mode.
- Persist nothing in the browser except an optional "last opened topic".