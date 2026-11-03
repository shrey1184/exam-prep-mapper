import os, time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(timeout=20_000),
)

for m in client.models.list():
    name = m.name.replace("models/", "")
    actions = getattr(m, "supported_actions", None) or []
    if "generateContent" not in actions or "flash" not in name:
        continue
    t = time.time()
    try:
        r = client.models.generate_content(model=name, contents="Say hi in 3 words")
        print(f"OK    {name:<40} {time.time()-t:.1f}s  {r.text.strip()[:30]}", flush=True)
    except Exception as e:
        print(f"FAIL  {name:<40} {str(e)[:70]}", flush=True)