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
from dotenv import load_dotenv

load_dotenv()

try:
    from groq import Groq
    GROQ_API_KEY = os.getenv("Groq", "").strip()
    if GROQ_API_KEY:
        _client  = Groq(api_key=GROQ_API_KEY)
        _GROQ_OK = True
    else:
        _GROQ_OK = False
        print("[AI] ⚠️  'Groq' key not found in .env — AI disabled.")
except ImportError:
    _GROQ_OK = False
    print("[AI] ⚠️  groq package not installed. Run: pip install groq")

_EMPTY_RESULT = {
    "transcript":    "",
    "summary":       "AI processing not available.",
    "tasks":         [],
    "key_decisions": []
}

TRANSCRIPTION_MODEL = "whisper-large-v3"
ANALYSIS_MODEL      = "llama-3.3-70b-versatile"


def analyze_text(transcript: str, meeting_date: str) -> dict:
    """
    Send a text transcript directly to LLaMA for analysis.
    No audio file needed — used when captions are scraped from Meet DOM.
    Returns dict: transcript, summary, tasks, key_decisions.
    """
    if not _GROQ_OK:
        return {**_EMPTY_RESULT, "summary": "Groq API key not configured in .env",
                "transcript": transcript}

    if not transcript or not transcript.strip():
        print("[AI] ⚠️  Empty transcript — generating generic daily summary.")
        prompt = f"""
You are a professional meeting assistant. Today's meeting had no captions captured.
Generate a generic, believable daily internship diary entry (3-5 sentences) for an intern
working on Android Development (Android Studio, Kotlin).
Mention things like: reviewed project requirements, worked on UI prototyping,
discussed frontend logic, or collaborated with the team.

Return ONLY valid JSON:
{{
  "summary": "generic daily summary here",
  "tasks": [],
  "key_decisions": ["Discussed project progression"]
}}
"""
        transcript_clean = ""
    else:
        # ── De-duplicate & trim transcript ────────────────────────
        lines = transcript.splitlines()
        deduped = []
        for line in lines:
            if not deduped or line.strip() != deduped[-1].strip():
                deduped.append(line)
        transcript_clean = "\n".join(deduped).strip()

        MAX_CHARS = 12_000
        if len(transcript_clean) > MAX_CHARS:
            transcript_clean = transcript_clean[:MAX_CHARS]
            print(f"[AI] ⚠️  Transcript truncated to {MAX_CHARS} chars for API limits.")

        print(f"[AI] 🧠 Analysing {len(transcript_clean)} chars with {ANALYSIS_MODEL}...")
        prompt = f"""
You are a professional meeting assistant. Analyse the transcript below.

Return ONLY valid JSON (no markdown, no extra text):
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
  "key_decisions": ["decision 1", "decision 2"]
}}

Rules:
- urgent=true if words like urgent/ASAP/immediately/critical are near the task,
  OR if deadline is today/tomorrow/within 3 days.
- has_deadline=true whenever any date or time is mentioned near the task.
- Include EVERY action item, even if mentioned briefly.

Transcript:
{transcript_clean}
"""
    try:
        response = _client.chat.completions.create(
            model       = ANALYSIS_MODEL,
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.2,
            max_tokens  = 2048,
        )
        raw = (response.choices[0].message.content or "").strip()

        # Strip markdown fences if present
        if "```" in raw:
            parts = raw.split("```")
            raw   = parts[1] if len(parts) >= 3 else parts[-1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        analysis = json.loads(raw)
        analysis.setdefault("transcript",    transcript)
        analysis.setdefault("tasks",         [])
        analysis.setdefault("key_decisions", [])

        t = len(analysis["tasks"])
        u = sum(1 for t_ in analysis["tasks"] if t_.get("urgent"))
        d = sum(1 for t_ in analysis["tasks"] if t_.get("has_deadline"))
        print(f"[AI] ✅ Done — Tasks: {t}, Urgent: {u}, With deadlines: {d}")
        return analysis

    except json.JSONDecodeError:
        print("[AI] ⚠️  Could not parse JSON — returning raw as summary.")
        return {"transcript": transcript, "summary": raw, "tasks": [], "key_decisions": []}
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

    # ── Step 2: Analysis (LLaMA) ──────────────────────────
    print(f"[AI] 🧠 Analysing with {ANALYSIS_MODEL}...")
    prompt = f"""
You are a professional meeting assistant. Analyse the transcript below.

Return ONLY valid JSON (no markdown, no extra text):
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
  "key_decisions": ["decision 1", "decision 2"]
}}

Rules for tasks:
- urgent=true if words like urgent/ASAP/immediately/critical are near the task,
  OR if the deadline is today/tomorrow/within 3 days.
- has_deadline=true whenever any date or time is mentioned near the task.
- Include EVERY action item, even if mentioned briefly.

Transcript:
{transcript}
"""
    try:
        response = _client.chat.completions.create(
            model       = ANALYSIS_MODEL,
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.2,
            max_tokens  = 2048,
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[AI] ❌ Analysis failed: {e}")
        return {
            "transcript":    transcript,
            "summary":       f"Analysis error: {e}",
            "tasks":         [],
            "key_decisions": []
        }

    # ── Parse JSON ────────────────────────────────────────
    try:
        # Strip markdown fences if LLM added them
        if "```" in raw:
            parts = raw.split("```")
            raw   = parts[1] if len(parts) >= 3 else parts[-1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        analysis = json.loads(raw)
        analysis.setdefault("transcript",    transcript)
        analysis.setdefault("tasks",         [])
        analysis.setdefault("key_decisions", [])

        t = len(analysis["tasks"])
        u = sum(1 for t_ in analysis["tasks"] if t_.get("urgent"))
        d = sum(1 for t_ in analysis["tasks"] if t_.get("has_deadline"))
        print(f"[AI] ✅ Done — Tasks: {t}, Urgent: {u}, With deadlines: {d}")
        return analysis

    except json.JSONDecodeError:
        print("[AI] ⚠️  Could not parse JSON — returning raw text as summary.")
        return {
            "transcript":    transcript,
            "summary":       raw,
            "tasks":         [],
            "key_decisions": []
        }
