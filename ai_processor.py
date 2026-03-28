"""
ai_processor.py
Uses Groq API to:
  1. Transcribe meeting audio  → whisper-large-v3
  2. Extract summary, tasks (with urgency/deadline/assignee),
     and key decisions       → llama-3.3-70b-versatile

Free tier: 7,200s audio/day  +  30,000 tokens/minute — very generous.
Get a free key at: https://console.groq.com
"""
import os
import json
import time
import datetime
from dotenv import load_dotenv

load_dotenv()

try:
    from groq import Groq
    GROQ_API_KEY = (os.getenv("GROQ_API_KEY", "") or os.getenv("Groq", "")).strip()
    if GROQ_API_KEY:
        _client  = Groq(api_key=GROQ_API_KEY)
        _GROQ_OK = True
    else:
        _GROQ_OK = False
        print("[AI] ⚠️  GROQ_API_KEY not found in .env — AI disabled.")
except ImportError:
    _GROQ_OK = False
    print("[AI] ⚠️  groq package not installed. Run: pip install groq")

_EMPTY_RESULT = {
    "transcript":        "",
    "summary":           "AI processing not available.",
    "tasks":             [],
    "learning_outcomes": []
}

TRANSCRIPTION_MODEL = "whisper-large-v3"
ANALYSIS_MODEL      = "llama-3.3-70b-versatile"
MAX_PROMPT_CHARS    = 8000


def _dedupe_lines(text: str) -> list[str]:
    """De-duplicate consecutive lines and remove empty lines."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not lines or line != lines[-1]:
            lines.append(line)
    return lines


def _compact_lines_for_prompt(lines: list[str], max_chars: int = MAX_PROMPT_CHARS) -> str:
    """
    Build a compact transcript for prompting the model.
    Keeps high-signal lines first, then samples remaining lines for coverage.
    """
    if not lines:
        return ""

    full_text = "\n".join(lines)
    if len(full_text) <= max_chars:
        return full_text

    signal_words = (
        "task", "todo", "action", "deadline", "urgent", "asap", "by ", "due",
        "decide", "decision", "issue", "bug", "blocker", "fix", "next",
        "summary", "plan", "deliver", "submit", "review", "meeting",
    )

    # Keep lines that are likely to carry key actions/decisions.
    high_signal = []
    for line in lines:
        low = line.lower()
        if any(w in low for w in signal_words):
            high_signal.append(line)

    selected = []
    seen = set()

    def _try_add(line: str) -> bool:
        if line in seen:
            return False
        tentative = ("\n".join(selected + [line]))
        if len(tentative) > max_chars:
            return False
        selected.append(line)
        seen.add(line)
        return True

    # 1) Add high-signal lines first.
    for line in high_signal:
        if not _try_add(line):
            break

    # 2) Add sampled lines across the whole meeting for context coverage.
    if len(selected) < 12:
        stride = max(1, len(lines) // 40)
        for i in range(0, len(lines), stride):
            if not _try_add(lines[i]):
                break

    # 3) If still tiny, add short first lines.
    if len(selected) < 6:
        for line in lines[:20]:
            if not _try_add(line):
                break

    compact = "\n".join(selected).strip()
    return compact if compact else full_text[:max_chars]


def _prepare_transcript_for_prompt(transcript: str, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """Normalize, dedupe and compact transcript to reduce prompt token usage."""
    lines = _dedupe_lines(transcript)
    compact = _compact_lines_for_prompt(lines, max_chars=max_chars)
    if len(compact) < len(transcript):
        print(f"[AI] ✂️ Compacted transcript from {len(transcript)} to {len(compact)} chars for lower token usage.")
    return compact


def _safe_json_parse(raw: str) -> dict | None:
    """Parse model JSON safely, including fenced responses."""
    if not raw:
        return None
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) >= 3 else parts[-1]
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        return None


def _chat_json(prompt: str, max_tokens: int, temperature: float = 0.2) -> tuple[dict | None, str]:
    """Call LLM and parse JSON response safely."""
    try:
        response = _client.chat.completions.create(
            model=ANALYSIS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = (response.choices[0].message.content or "").strip()
        return _safe_json_parse(raw), raw
    except Exception as e:
        print(f"[AI] ❌ Model call failed: {e}")
        return None, ""


def _normalize_task_list(tasks: list) -> list[dict]:
    """Normalize tasks into a consistent schema."""
    out = []
    for t in tasks or []:
        if isinstance(t, dict):
            out.append({
                "task": (t.get("task") or "").strip(),
                "assignee": (t.get("assignee") or "Unassigned").strip() or "Unassigned",
                "deadline": (t.get("deadline") or "No deadline mentioned").strip() or "No deadline mentioned",
                "urgent": bool(t.get("urgent", False)),
                "has_deadline": bool(t.get("has_deadline", False)),
            })
        elif isinstance(t, str) and t.strip():
            out.append({
                "task": t.strip(),
                "assignee": "Unassigned",
                "deadline": "No deadline mentioned",
                "urgent": False,
                "has_deadline": False,
            })
    return out


def _fallback_compact_summary(transcript_clean: str) -> dict:
    """Cheap local fallback if model JSON parsing fails repeatedly."""
    lines = _dedupe_lines(transcript_clean)
    bullets = lines[:5]
    summary = " ".join(bullets[:3])[:550] if bullets else "Meeting discussion captured, but structured extraction was limited."
    if not summary:
        summary = "Meeting discussion captured, but structured extraction was limited."

    return {
        "summary": summary,
        "tasks": [],
        "learning_outcomes": [
            "Reviewed key points discussed in the meeting.",
            "Observed implementation concerns and architecture notes.",
            "Identified next areas to continue in the next session.",
        ],
        "key_decisions": [],
    }


def _two_pass_structured_analysis(transcript_clean: str, meeting_date: str) -> dict:
    """
    Two-pass analysis:
      1) Tiny extraction pass (tasks/decisions/risks/context)
      2) Final summary pass from extracted points
    """
    extract_prompt = f"""
You are an extraction engine. Read the compact transcript and extract only high-signal facts.

Return ONLY valid JSON:
{{
  "meeting_objective": "one-line objective",
  "themes": ["theme1", "theme2", "theme3"],
  "decisions": ["decision1", "decision2"],
  "risks": ["risk1", "risk2"],
  "tasks": [
    {{
      "task": "what needs to be done",
      "assignee": "person name, or 'Unassigned'",
      "deadline": "specific date/time, or 'No deadline mentioned'",
      "urgent": true,
      "has_deadline": true
    }}
  ],
  "context_notes": ["short context line 1", "short context line 2"],
  "learning_signals": ["concept learned 1", "concept learned 2", "concept learned 3"]
}}

Rules:
- Keep each item concise and factual.
- Extract only what is supported by transcript.
- If missing, return empty arrays.

Transcript:
{transcript_clean}
"""

    extraction, raw_extract = _chat_json(extract_prompt, max_tokens=900, temperature=0.1)
    if not extraction:
        print("[AI] ⚠️ Extraction pass parse failed — using compact fallback.")
        return _fallback_compact_summary(transcript_clean)

    extraction.setdefault("meeting_objective", "")
    extraction.setdefault("themes", [])
    extraction.setdefault("decisions", [])
    extraction.setdefault("risks", [])
    extraction.setdefault("tasks", [])
    extraction.setdefault("context_notes", [])
    extraction.setdefault("learning_signals", [])

    build_prompt = f"""
You are a professional meeting summarizer for engineering internship notes.
Date: {meeting_date}

Use ONLY the extracted structured points below to generate final output.

Extracted points JSON:
{json.dumps(extraction, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "summary": "3-5 sentence meeting summary",
  "tasks": [
    {{
      "task": "what needs to be done",
      "assignee": "person name, or 'Unassigned'",
      "deadline": "specific date/time, or 'No deadline mentioned'",
      "urgent": true,
      "has_deadline": true
    }}
  ],
  "key_decisions": ["decision1", "decision2"],
  "learning_outcomes": [
    "First explicit learning point from the meeting",
    "Second explicit learning point from the meeting",
    "Third explicit learning point from the meeting"
  ]
}}

Rules:
- Maintain factual consistency with extracted points.
- learning_outcomes should be exactly 3 plain text points when possible.
- Keep summary concise, clear, and student-oriented.
"""

    final_obj, raw_final = _chat_json(build_prompt, max_tokens=1100, temperature=0.2)
    if not final_obj:
        print("[AI] ⚠️ Final summary pass parse failed — building from extraction.")
        return {
            "summary": (
                "Meeting covered ongoing implementation updates, architecture considerations, and next execution steps."
            ),
            "tasks": _normalize_task_list(extraction.get("tasks", [])),
            "key_decisions": extraction.get("decisions", []),
            "learning_outcomes": (extraction.get("learning_signals", []) or [])[:3],
        }

    final_obj.setdefault("summary", "")
    final_obj["tasks"] = _normalize_task_list(final_obj.get("tasks", []))
    final_obj.setdefault("key_decisions", extraction.get("decisions", []))

    los = final_obj.get("learning_outcomes", [])
    if not isinstance(los, list):
        los = []
    los = [str(x).strip() for x in los if str(x).strip()]
    if len(los) < 3:
        for s in extraction.get("learning_signals", []):
            if len(los) >= 3:
                break
            s = str(s).strip()
            if s and s not in los:
                los.append(s)
    while len(los) < 3:
        los.append("Strengthened understanding of implementation flow and architecture decisions.")
    final_obj["learning_outcomes"] = los[:3]

    return final_obj


def _humanize_summary_layer(summary: str, learning_outcomes: list[str], meeting_date: str) -> tuple[str, list[str]]:
    """
    Third layer: rewrite summary + learning outcomes into natural student tone
    without changing factual meaning.
    """
    if not summary and not learning_outcomes:
        return summary, learning_outcomes

    humanize_prompt = f"""
Rewrite the content in a natural, human, student-like tone.
Date: {meeting_date}

Input summary:
{summary}

Input learning_outcomes:
{json.dumps(learning_outcomes, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "summary": "humanized 3-5 sentence summary",
  "learning_outcomes": [
    "humanized point 1",
    "humanized point 2",
    "humanized point 3"
  ]
}}

Rules:
- Preserve facts, tasks context, and intent.
- Do not add new technical claims.
- Keep language simple, clear, and not robotic.
- learning_outcomes must stay plain text.
"""

    obj, _ = _chat_json(humanize_prompt, max_tokens=700, temperature=0.45)
    if not obj:
        return summary, learning_outcomes

    hs = str(obj.get("summary", "")).strip() or summary
    hlo = obj.get("learning_outcomes", learning_outcomes)
    if not isinstance(hlo, list):
        hlo = learning_outcomes
    hlo = [str(x).strip() for x in hlo if str(x).strip()]
    if not hlo:
        hlo = learning_outcomes
    while len(hlo) < 3:
        hlo.append("Improved clarity on implementation and architecture decisions.")
    return hs, hlo[:3]


def _load_meeting_history() -> list[dict]:
    """Load flattened meeting records from meetings_db.json."""
    path = "meetings_db.json"
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except Exception:
        return []

    rows = []
    for date_str, records in (db or {}).items():
        if not isinstance(records, list):
            records = [records]
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rows.append({
                "date": date_str,
                "summary": (rec.get("summary") or "").strip(),
                "tasks": rec.get("tasks") or [],
                "learning_outcomes": rec.get("learning_outcomes") or [],
            })

    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def _recent_history(meeting_date: str, lookback_days: int = 14) -> list[dict]:
    """Return recent records before meeting_date."""
    try:
        target = datetime.datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except Exception:
        target = datetime.date.today()

    out = []
    for row in _load_meeting_history():
        try:
            d = datetime.datetime.strptime(row["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        delta = (target - d).days
        if 0 < delta <= lookback_days:
            out.append(row)
    return out


def _rule_based_no_record_entry(meeting_date: str, history: list[dict], is_friday: bool) -> dict:
    """Create a local fallback summary when AI is unavailable."""
    if not history:
        return {
            "summary": (
                "No meeting record was captured today, so I used the day to revisit the current module, "
                "clean pending code paths, and document the next implementation steps for tomorrow."
            ),
            "tasks": [],
            "learning_outcomes": [
                "Revisited project structure and identified where to improve reliability.",
                "Practiced debugging flow for browser automation edge cases.",
                "Planned next small milestones to keep daily progress consistent.",
            ],
        }

    dates = []
    points = []
    for row in history[:6]:
        if row.get("date") and row["date"] not in dates:
            dates.append(row["date"])
        if row.get("summary"):
            points.append(row["summary"])

    if is_friday:
        joined_dates = ", ".join(sorted(set(dates))[:5])
        summary = (
            "No fresh meeting transcript was available today, so I prepared a weekly recap by revisiting this "
            f"week's work ({joined_dates}). I consolidated implementation progress, open blockers, and next "
            "execution priorities so Monday can start with a clear action plan."
        )
    else:
        latest = points[0] if points else "continued implementation and review"
        summary = (
            "No meeting transcript was captured today. I used the session to revisit previous progress and continue "
            f"work based on recent updates, mainly focusing on: {latest[:180]}"
        )

    return {
        "summary": summary,
        "tasks": [],
        "learning_outcomes": [
            "Strengthened continuity by connecting today's work with earlier meeting outcomes.",
            "Identified recurring gaps and converted them into concrete next actions.",
            "Improved weekly-level understanding of priorities and delivery sequence.",
        ],
    }


def generate_no_record_entry(meeting_date: str) -> dict:
    """
    Build an enhanced summary when no transcript/report is available.
    Uses recent days as context; on Fridays, prefers a weekly recap style.
    """
    try:
        target = datetime.datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except Exception:
        target = datetime.date.today()
        meeting_date = target.strftime("%Y-%m-%d")

    is_friday = target.weekday() == 4
    history = _recent_history(meeting_date, lookback_days=14)

    # If API isn't available, still provide context-aware fallback.
    if not _GROQ_OK:
        local = _rule_based_no_record_entry(meeting_date, history, is_friday)
        return {
            "transcript": "",
            "summary": local["summary"],
            "tasks": local.get("tasks", []),
            "learning_outcomes": local.get("learning_outcomes", []),
        }

    history_block = []
    for row in history[:8]:
        s = (row.get("summary") or "").strip()
        if s:
            history_block.append(f"- {row['date']}: {s[:220]}")
    history_text = "\n".join(history_block) if history_block else "- No prior records available"

    mode = "weekly recap" if is_friday else "daily continuity summary"
    prompt = f"""
You are writing an internship diary summary for {meeting_date}.
No transcript or meeting captions are available for today.

Style mode: {mode}

Prior meeting history (most recent first):
{history_text}

Return ONLY valid JSON:
{{
  "summary": "4-6 sentence natural student-style summary",
  "tasks": [],
  "learning_outcomes": [
    "learning point 1",
    "learning point 2",
    "learning point 3"
  ]
}}

Rules:
- Keep tone natural and realistic for a student intern.
- If today is Friday, produce a weekly reflection/recap style summary.
- If not Friday, continue from recent days and mention carry-forward progress.
- Do not invent very specific claims like production deployment unless strongly implied.
- learning_outcomes must be exactly 3 plain-text points.
"""

    try:
        response = _client.chat.completions.create(
            model=ANALYSIS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.35,
            max_tokens=1200,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = _safe_json_parse(raw)
        if parsed:
            parsed.setdefault("tasks", [])
            parsed.setdefault("learning_outcomes", [])
            return {
                "transcript": "",
                "summary": parsed.get("summary", ""),
                "tasks": parsed.get("tasks", []),
                "learning_outcomes": parsed.get("learning_outcomes", []),
            }
    except Exception as e:
        print(f"[AI] ⚠️  No-record AI generation failed: {e}")

    local = _rule_based_no_record_entry(meeting_date, history, is_friday)
    return {
        "transcript": "",
        "summary": local["summary"],
        "tasks": local.get("tasks", []),
        "learning_outcomes": local.get("learning_outcomes", []),
    }


def analyze_text(transcript: str, meeting_date: str) -> dict:
    """
    Send a text transcript directly to LLaMA for analysis.
    No audio file needed — used when captions are scraped from Meet DOM.
    Returns dict: transcript, summary, tasks, key_decisions.
    """
    if not transcript or not transcript.strip():
        print("[AI] ⚠️  Empty transcript — generating contextual no-record summary.")
        generated = generate_no_record_entry(meeting_date)
        generated["transcript"] = transcript or ""
        return generated

    if not _GROQ_OK:
        return {
            **_EMPTY_RESULT,
            "summary": "Groq API key not configured in .env",
            "transcript": transcript,
        }

    # ── Normalize and compact transcript for lower token usage ──
    transcript_clean = _prepare_transcript_for_prompt(transcript, max_chars=MAX_PROMPT_CHARS)

    print(f"[AI] 🧠 Analysing {len(transcript_clean)} chars with token-efficient 2-pass pipeline...")
    try:
        analysis = _two_pass_structured_analysis(transcript_clean, meeting_date)

        human_summary, human_los = _humanize_summary_layer(
            analysis.get("summary", ""),
            analysis.get("learning_outcomes", []),
            meeting_date,
        )
        analysis["summary"] = human_summary
        analysis["learning_outcomes"] = human_los

        analysis.setdefault("transcript", transcript)
        analysis.setdefault("tasks", [])
        analysis.setdefault("key_decisions", [])

        t = len(analysis["tasks"])
        u = sum(1 for t_ in analysis["tasks"] if t_.get("urgent"))
        d = sum(1 for t_ in analysis["tasks"] if t_.get("has_deadline"))
        print(f"[AI] ✅ Done — Tasks: {t}, Urgent: {u}, With deadlines: {d}")
        return analysis
    except Exception as e:
        print(f"[AI] ❌ Analysis error: {e}")
        return {**_EMPTY_RESULT, "transcript": transcript, "summary": f"Analysis error: {e}"}


def transcribe_and_analyze(audio_path: str | None, meeting_date: str) -> dict:
    """
    Transcribe the audio file then extract a structured meeting analysis.
    Returns dict: transcript, summary, tasks, key_decisions.
    Gracefully falls back on any error.
    """
    if not _GROQ_OK:
        return {**_EMPTY_RESULT, "summary": "Groq API key not configured in .env"}

    if not audio_path or not os.path.exists(audio_path):
        print(f"[AI] ⚠️  Audio file not found: {audio_path}")
        return {**_EMPTY_RESULT, "summary": "No audio recording found."}

    # ── Step 1: Transcription (Whisper) ───────────────────
    print(f"[AI] 🎙️  Transcribing with Whisper ({TRANSCRIPTION_MODEL})...")
    transcript = ""
    try:
        with open(audio_path, "rb") as f:
            result = _client.audio.transcriptions.create(
                file            = (os.path.basename(audio_path), f),
                model           = TRANSCRIPTION_MODEL,
                response_format = "verbose_json",
                language        = "en",
            )
        transcript = result.text.strip() if hasattr(result, "text") else str(result).strip()
        print(f"[AI] ✅ Transcript ready ({len(transcript)} chars).")
    except Exception as e:
        print(f"[AI] ❌ Transcription failed: {e}")
        return {**_EMPTY_RESULT, "summary": f"Transcription error: {e}"}

    if not transcript:
        print("[AI] ⚠️  Empty transcript — no speech detected in recording.")
        return {**_EMPTY_RESULT, "transcript": "", "summary": "No speech detected."}

    # ── Step 2: Two-pass analysis + humanization ──────────
    compact = _prepare_transcript_for_prompt(transcript, max_chars=MAX_PROMPT_CHARS)
    print(f"[AI] 🧠 Analysing with token-efficient 2-pass pipeline ({ANALYSIS_MODEL})...")
    try:
        analysis = _two_pass_structured_analysis(compact, meeting_date)

        human_summary, human_los = _humanize_summary_layer(
            analysis.get("summary", ""),
            analysis.get("learning_outcomes", []),
            meeting_date,
        )
        analysis["summary"] = human_summary
        analysis["learning_outcomes"] = human_los

        analysis.setdefault("transcript", transcript)
        analysis.setdefault("tasks", [])
        analysis.setdefault("key_decisions", [])

        t = len(analysis["tasks"])
        u = sum(1 for t_ in analysis["tasks"] if t_.get("urgent"))
        d = sum(1 for t_ in analysis["tasks"] if t_.get("has_deadline"))
        print(f"[AI] ✅ Done — Tasks: {t}, Urgent: {u}, With deadlines: {d}")
        return analysis
    except Exception as e:
        print(f"[AI] ❌ Analysis failed: {e}")
        return {
            "transcript": transcript,
            "summary": f"Analysis error: {e}",
            "tasks": [],
            "learning_outcomes": []
        }
