# scripts/debug_ocr.py
import os, io, time
import pdfplumber
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(timeout=60_000),  # 60 s, in milliseconds
)
MODEL = "gemini-3.6-flash"   # same value as in ocr_scanned.py
PDF = "data/raw/notes/unit1.pdf"   # use your real file name

t = time.time()
print("1. text-only call...", flush=True)
r = client.models.generate_content(model=MODEL, contents="Say hi in 3 words")
print("   ok:", r.text.strip(), f"({time.time()-t:.1f}s)", flush=True)

t = time.time()
print("2. rendering page 1...", flush=True)
with pdfplumber.open(PDF) as pdf:
    img = pdf.pages[0].to_image(resolution=150).original
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png = buf.getvalue()
print(f"   ok: {len(png)/1024:.0f} KB ({time.time()-t:.1f}s)", flush=True)

t = time.time()
print("3. image call...", flush=True)
r = client.models.generate_content(
    model=MODEL,
    contents=[types.Part.from_bytes(data=png, mime_type="image/png"),
              "Transcribe the title of this page."],
)
print("   ok:", r.text.strip()[:100], f"({time.time()-t:.1f}s)", flush=True)