# MeetFlow

![Project Type](https://img.shields.io/badge/Project-Personal-0f172a)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-blue)
![Status](https://img.shields.io/badge/Status-Active-success)

> MeetFlow is a personal meeting automation engine that reliably joins Google Meet sessions,
> captures discussion context, generates structured AI summaries with a token-efficient pipeline,
> and converts meeting outcomes into practical daily documentation.

---

## Project Description

MeetFlow was built to solve a real daily workflow problem: joining recurring meetings consistently, capturing what was actually discussed, and turning noisy live captions into clean and useful outputs.

Instead of being just a join bot, it behaves like a local meeting assistant with reliability-first automation:

- safe join flow with pre-join mic/camera checks
- popup and transient error recovery
- compact multi-stage AI analysis for long transcripts
- human-like summary and learning outcome generation
- report generation and VTU diary handoff

---

## Why MeetFlow

- Reliable join behavior with popup-safe recovery logic
- Cost-aware AI summarization for long caption streams
- Human-readable reports and learning outcomes
- Local-first execution with optional utilities

---

## Quick Comparison

| Before MeetFlow                               | With MeetFlow                                         |
| --------------------------------------------- | ----------------------------------------------------- |
| Manual meeting join every day                 | Reliable scheduled joins with recovery handling       |
| Frequent misses due to popups or late joins   | Pre-join media safety and one-time join-page reload   |
| Long raw captions with repeated noise         | Token-efficient AI pipeline for long transcripts      |
| Unstructured notes and forgotten action items | Human-like summary with structured tasks and outcomes |
| Separate manual diary effort                  | Automatic report generation and VTU diary handoff     |

---

## End-to-End Flow

1. Scheduler waits for configured IST join time.
2. Chrome launches with persistent profile and media permissions.
3. Bot waits for visible mic/camera controls, disables both, then joins.
4. Bot captures captions and chat while monitoring meeting state.
5. AI pipeline runs: compact -> extract -> summarize -> humanize.
6. Report and meeting record are saved locally.
7. VTU diary can auto-fill from generated report context.
8. Optional shutdown is scheduled after session completion.

---

## Architecture Diagram

```mermaid
flowchart TD
  A[Scheduler<br/>meet_joiner.py] --> B[Launch Chrome Profile]
  B --> C[Pre-Join Guard<br/>Mic Off + Camera Off]
  C --> D[Join Logic<br/>Popup-safe + One-time Reload]
  D --> E[In-Meeting Monitor]

  E --> F[Capture Layer<br/>Captions + Chat + Dedup]
  F --> G[AI Layer 1<br/>Compact Transcript]
  G --> H[AI Layer 2<br/>Tiny Extraction<br/>Tasks + Decisions + Risks]
  H --> I[AI Layer 3<br/>Final Summary + Humanization]

  I --> J[Reports Folder<br/>reports/YYYY-MM-DD_HH-MM.txt]
  I --> K[Meeting DB<br/>meetings_db.json]
  J --> L[VTU Diary Auto-Fill<br/>vtu_diary.py]

  E --> M[End-State Detection<br/>host_ended | kicked | left | error]
  M --> N[Optional Shutdown Scheduler]

  O[Optional Utilities<br/>whatsapp_notifier.py / whatsapp_bot_server.py] -. independent .-> A
```

---

## Core Capabilities

### Join Reliability

- Scheduled mode and immediate mode (`python meet_joiner.py --now`)
- Strict pre-join media gate (mic/camera must be visible and OFF)
- Join selector coverage for Ask to join, Join now, Ready to join, Rejoin, Try again
- Waiting-room detection and host-admission handling
- One-time full Meet page reload when join controls are missing
- Chrome startup retry and page readiness checks

### Stability and Recovery

- Detects transient Meet errors and attempts recovery actions
- Rejoin behavior for removed/kicked scenarios
- URL and title-based end-state detection
- Max-duration safety guard

### Capture and Signal Quality

- Caption capture with UI-noise filtering
- Chat scraping with link extraction
- Deduplication of repetitive lines before AI processing

### AI Summary Engine (Token-Efficient)

- Layer 1: compact transcript preparation
- Layer 2: tiny extraction pass (tasks, decisions, risks, context)
- Layer 3: final summary pass from extracted points
- Layer 4: humanization pass for student-like natural language output
- Empty/no-record fallback with continuity summaries
- Friday weekly-recap style fallback when transcript is absent

### Reporting and Storage

- Report output: `reports/YYYY-MM-DD_HH-MM.txt`
- Persistent meeting record store: `meetings_db.json`
- Structured fields for summary, tasks, transcript, outcomes

### VTU Diary Automation

- Standalone test mode and date override
- Uses latest report context for summary and learning outcomes
- Supports additional skill tagging based on detected content

### Optional Utilities

- Meet joiner runs local-first and does not require WhatsApp/Twilio
- WhatsApp helper files remain available as optional utilities

---

## Project Structure

```text
MeetFlow/
|- meet_joiner.py            # Scheduler + Google Meet automation core
|- ai_processor.py           # Multi-layer AI analysis pipeline
|- vtu_diary.py              # VTU diary automation
|- setup_login.py            # One-time Google session setup
|- config.json               # Runtime configuration
|- requirements.txt          # Python dependencies
|- run_meet_joiner.bat       # Windows launcher
|- reports/                  # Generated meeting reports
|- chrome_profile/           # Meet browser profile
|- chrome_profile_vtu/       # VTU browser profile
|- meetings_db.json          # Local meeting record database
|- .env.example              # Environment template
|- .env                      # Local secrets (do not commit)
|- whatsapp_notifier.py      # Optional utility
|- whatsapp_bot_server.py    # Optional utility
|- run_whatsapp_server.bat   # Optional utility launcher
```

---

## Configuration

`config.json` example:

```json
{
  "meet_link": "https://meet.google.com/your-code-here",
  "dynamic_link_override": null,
  "join_time_ist": "13:00",
  "shutdown_time_ist": "15:30",
  "max_duration_minutes": 90,
  "vtu_hours": 1.0,
  "vtu_skills": ["Android Studio", "Kotlin"]
}
```

Field guide:

- `meet_link`: default meeting URL
- `dynamic_link_override`: one-time override consumed at actual join
- `join_time_ist`: daily scheduled join time
- `shutdown_time_ist`: scheduled machine shutdown target
- `max_duration_minutes`: guardrail for long sessions
- `vtu_hours`: fallback hours for diary entry
- `vtu_skills`: baseline skills list for diary submission

---

## Quick Start

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Create environment file

```bash
copy .env.example .env
```

Required values:

```env
GROQ_API_KEY=your_groq_api_key
VTU_USERNAME=your_vtu_email@gmail.com
VTU_PASSWORD=yourPassword
```

Optional values (only for WhatsApp utilities):

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
```

### 3) One-time session setup

```bash
python setup_login.py
python vtu_diary.py --test
```

### 4) Run

```bash
python meet_joiner.py
```

Immediate mode:

```bash
python meet_joiner.py --now
```

---

## Troubleshooting

| Issue                      | Likely Cause                                        | Recommended Fix                                          |
| -------------------------- | --------------------------------------------------- | -------------------------------------------------------- |
| Could not find Join button | Waiting room, signed-out session, selector mismatch | Run `setup_login.py`, verify profile session, retry      |
| Join controls not visible  | Transient Meet UI state                             | Built-in one-time full reload will trigger automatically |
| Redirected to Google login | Session expired                                     | Re-authenticate via `setup_login.py`                     |
| AI output missing          | Missing `GROQ_API_KEY`                              | Add key to `.env` and rerun                              |
| VTU diary login fails      | Invalid credentials/session                         | Verify `.env`, rerun `python vtu_diary.py --test`        |
| Scheduler does not wake PC | Windows wake timers disabled                        | Enable wake timers in power options                      |

---

## Security

Never share or commit these:

- `chrome_profile/`
- `chrome_profile_vtu/`
- `.env`
- `meetings_db.json`

---

## Tech Stack

- Python 3.10+
- Selenium + undetected-chromedriver
- Groq API (LLaMA family)
- python-dotenv
- Flask + Twilio (optional utilities)
