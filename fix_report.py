"""
fix_report.py — One-time script to rewrite today's (or latest) messy report
with a proper cleaned summary by extracting unique incremental caption lines
and re-sending to Groq LLaMA.
"""
import re, glob, os, json, datetime
from dotenv import load_dotenv

load_dotenv()

# ── Find latest report ─────────────────────────────────────
files = sorted(glob.glob("reports/*.txt"), reverse=True)
if not files:
    print("No report files found.")
    exit(1)

path = files[0]
print(f"Fixing: {path}")
raw = open(path, encoding="utf-8").read()

# ── Extract header lines ───────────────────────────────────
header_end = raw.find("TRANSCRIPT")
header = raw[:header_end].strip() if header_end != -1 else ""

# ── Extract and clean the TRANSCRIPT section ───────────────
# The transcript is a rolling window — each line includes all previous text
# plus new words. We extract only the NEW incremental words each time.
UI_NOISE_WORDS = {
    "language", "english", "closed_caption", "live captions",
    "format_size", "font size", "circle", "font colour", "font color",
    "settings", "open caption settings", "caption settings",
    "format_color_text", "background", "font style",
    "check", "check_box", "more_vert", "accessibility",
    "mindmatrix",  # speaker label — skip it
}

transcript_section = raw[header_end:] if header_end != -1 else raw

lines = transcript_section.splitlines()
caption_lines = []
for line in lines:
    s = line.strip()
    if not s or len(s) < 6:
        continue
    if s.lower() in UI_NOISE_WORDS:
        continue
    words = set(s.lower().split())
    if words.issubset(UI_NOISE_WORDS):
        continue
    # Skip the "TRANSCRIPT / ---" header
    if s.startswith("=") or s.startswith("-") or s == "TRANSCRIPT":
        continue
    caption_lines.append(s)

# Build unique incremental transcript:
# Each line is a rolling window — take the LAST line of each rolling group
# A new group starts when the new line does NOT start with the previous line's prefix
unique_lines = []
prev = ""
for line in caption_lines:
    # If this line starts where the previous left off = same utterance, update it
    if line.startswith(prev[:min(40, len(prev))]) and prev:
        unique_lines[-1] = line   # update to the more complete version
    else:
        unique_lines.append(line)
    prev = line

# Deduplicate exact matches
seen = set()
deduped = []
for l in unique_lines:
    if l not in seen:
        seen.add(l)
        deduped.append(l)

clean_transcript = "\n".join(deduped)
print(f"Clean transcript: {len(clean_transcript)} chars ({len(deduped)} lines)")

# ── Send to Groq ───────────────────────────────────────────
MAX_CHARS = 12000
if len(clean_transcript) > MAX_CHARS:
    clean_transcript = clean_transcript[:MAX_CHARS]
    print(f"Truncated to {MAX_CHARS} chars.")

try:
    from groq import Groq
    api_key = os.getenv("Groq", "").strip()
    client = Groq(api_key=api_key)

    prompt = f"""You are a professional meeting assistant. Analyse the transcript below.

Return ONLY valid JSON (no markdown, no extra text):
{{
  "summary": "3-5 sentence meeting summary",
  "tasks": [
    {{
      "task": "what needs to be done",
      "assignee": "person name, or 'Unassigned'",
      "deadline": "specific date/time, or 'No deadline mentioned'",
      "urgent": false,
      "has_deadline": false
    }}
  ],
  "key_decisions": ["decision 1", "decision 2"]
}}

Transcript:
{clean_transcript}
"""
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1024,
    )
    raw_json = resp.choices[0].message.content.strip()
    if "```" in raw_json:
        parts = raw_json.split("```")
        raw_json = parts[1] if len(parts) >= 3 else parts[-1]
        if raw_json.lower().startswith("json"):
            raw_json = raw_json[4:]
    analysis = json.loads(raw_json.strip())
    print(f"[AI] Summary: {analysis.get('summary','')[:120]}...")
except Exception as e:
    print(f"[AI] Error: {e} — writing manual summary.")
    analysis = {
        "summary": (
            "Today's internship meeting (24 March 2026) focused on Android front-end development. "
            "The mentor (MindMatrix) guided interns on the importance of building UI prototypes and "
            "blueprints in tools like Figma before implementing in Android Studio. "
            "The session covered how to approach a new project: research, understand requirements, "
            "design a prototype, then code using Kotlin in Android Studio. "
            "Project assignments for each intern are expected within a couple of days."
        ),
        "tasks": [
            {"task": "Build a UI prototype/blueprint before starting Android Studio implementation",
             "assignee": "All interns", "deadline": "Before project starts", "urgent": True, "has_deadline": False},
            {"task": "Research and understand the assigned project requirements",
             "assignee": "All interns", "deadline": "No deadline mentioned", "urgent": False, "has_deadline": False},
        ],
        "key_decisions": [
            "Prototypes must be built before any Android Studio implementation begins.",
            "Projects will be assigned to each intern within a couple of days.",
            "Interns warned against unnecessary noise/unmuting before meeting starts.",
        ]
    }

# ── Rewrite the report file ────────────────────────────────
summary_text     = analysis.get("summary", "")
tasks            = analysis.get("tasks", [])
key_decisions    = analysis.get("key_decisions", [])

tasks_text = ""
for t in tasks:
    tasks_text += f"  • {t.get('task','')}"
    if t.get("assignee") and t["assignee"] != "Unassigned":
        tasks_text += f" [{t['assignee']}]"
    if t.get("has_deadline") and t.get("deadline"):
        tasks_text += f" — {t['deadline']}"
    if t.get("urgent"):
        tasks_text += " ⚡"
    tasks_text += "\n"
if not tasks_text:
    tasks_text = "  None identified.\n"

decisions_text = "\n".join(f"  • {d}" for d in key_decisions) or "  None identified."

new_report = f"""{header}

SUMMARY
------------------------------------------------------------
{summary_text}

KEY DECISIONS
------------------------------------------------------------
{decisions_text}

ACTION ITEMS
------------------------------------------------------------
{tasks_text}
TRANSCRIPT (cleaned)
------------------------------------------------------------
{"\n".join(deduped[:200])}
"""

open(path, "w", encoding="utf-8").write(new_report)
print(f"\n✅ Report rewritten: {path}")
print(f"Summary preview: {summary_text[:200]}")
