# ingestion/generate_insights.py
import os, json, time
import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(
        timeout=40_000,
        retry_options=types.HttpRetryOptions(attempts=1),   # my loop does the retrying
    ),
)
MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3-flash-preview", "gemini-3.6-flash"]
OWNER = "dev-user"

PROMPT = """You are helping a student revise from their own class notes.
Using ONLY the notes below (do not add outside facts), return JSON with exactly this shape:
{{"key_points": ["...", "..."], "likely_questions": ["...", "..."]}}

Rules:
- key_points: 5 to 7 short revision bullets, each under 25 words, the things worth memorising.
- likely_questions: 3 to 5 exam-style questions that the notes can answer (a mix of short and long answer).
- Use the notes' own terms. Do not invent facts, numbers or examples that are not in the notes.

Section: {title}

Notes:
{text}
"""


def generate(title: str, text: str) -> tuple[dict, str]:
    last = None
    for attempt in range(6):
        model = MODELS[attempt % len(MODELS)]
        try:
            r = client.models.generate_content(
                model=model,
                contents=PROMPT.format(title=title, text=text),
                config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=1024),
            )
            data = json.loads(r.text)
            kp, lq = data["key_points"], data["likely_questions"]
            if not (isinstance(kp, list) and isinstance(lq, list) and kp and lq):
                raise ValueError("empty or wrong shape")
            return {"key_points": kp, "likely_questions": lq}, model
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last = f"bad output: {e}"
            print(f"  {model}: {last}, retrying", flush=True)
        except Exception as e:
            last = str(e)
            retryable = ("429", "500", "503", "504", "UNAVAILABLE", "imeout", "timed out", "DEADLINE")
            if any(c in last for c in retryable):
                wait = 60 if "429" in last else 3 * (attempt + 1)
                print(f"  {model} failed ({last[:50]}), waiting {wait}s", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"insight generation failed: {last}")


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        todo = conn.execute(
            """select c.id, c.unit, c.section_title, c.text
               from chunks c left join topic_insights i on i.chunk_id = c.id
               where c.owner_id=%s and i.chunk_id is null
               order by c.unit, c.page_start""", (OWNER,)).fetchall()
        print(f"{len(todo)} sections need insights", flush=True)

        for n, (cid, unit, title, text) in enumerate(todo, start=1):
            print(f"[{n}/{len(todo)}] {unit} - {title}", flush=True)
            data, model = generate(title, text)
            conn.execute(
                """insert into topic_insights (chunk_id, key_points, likely_questions, model)
                   values (%s,%s,%s,%s)""",
                (cid, Jsonb(data["key_points"]), Jsonb(data["likely_questions"]), model))
            conn.commit()          # commit per section so a crash loses nothing
            time.sleep(4)          # stay under the free-tier per-minute limit


if __name__ == "__main__":
    main()