# ingestion/split_sections.py
import re, json
from pathlib import Path

# Repeating page header lines, e.g.
#   "AL301 • TECHNICAL COMMUNICATION"
#   "UNIT 2 NOTES • PAGE 7"
HEADER_RES = [
    re.compile(r"^AL\d+\b.*TECHNICAL COMMUNICATION\s*$", re.I),
    re.compile(r"^UNIT\s*\d+\s*NOTES\b.*PAGE\s*\d+\s*$", re.I),
]
# Numbered heading, e.g. "7. Barriers to Communication"
HEADING_RE = re.compile(r"^(\d{1,2})\.\s+([A-Z].{2,100})$")


def is_header(line: str) -> bool:
    return any(r.match(line) for r in HEADER_RES)


def split_sections(pages: list[dict], unit: str) -> list[dict]:
    sections, current, expected = [], None, 1

    for p in pages:
        for line in p["text"].splitlines():
            line = line.strip()
            if not line or is_header(line):
                continue

            m = HEADING_RE.match(line)
            # Only accept the NEXT number in sequence. This stops stray
            # numbered lines inside a section from becoming fake headings.
            if m and int(m.group(1)) == expected:
                if current:
                    sections.append(current)
                current = {
                    "unit": unit,
                    "number": expected,
                    "title": m.group(2).strip(),
                    "page_start": p["page"],
                    "page_end": p["page"],
                    "lines": [],
                }
                expected += 1
                continue

            if current:
                current["lines"].append(line)
                current["page_end"] = p["page"]
            # Text before heading 1 (the cover page) is ignored.

    if current:
        sections.append(current)

    for s in sections:
        s["text"] = "\n".join(s.pop("lines"))
    return sections


if __name__ == "__main__":
    pages = json.loads(Path("data/processed/AL301_Unit_2_Detailed_Notes.json").read_text())
    sections = split_sections(pages, unit="Unit 2")

    out = Path("data/processed/unit2_sections.json")
    out.write_text(json.dumps(sections, indent=2, ensure_ascii=False))

    print(f"{len(sections)} sections\n")
    for s in sections:
        print(f"{s['number']:>2}. {s['title'][:55]:<55} p{s['page_start']}-{s['page_end']}  {len(s['text'])} chars")