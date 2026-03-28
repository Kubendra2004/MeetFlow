# MeetFlow - Intelligent Meeting Automator

MeetFlow automates your Google Meet workflow end to end:
joining meetings, handling popups, collecting captions/chat, generating AI summaries,
saving reports, updating internship diary entries, and
shutting down your PC on schedule.

## Overview

This project is designed for reliable unattended operation on Windows (and supports Linux profile paths too).

Flow summary:

1. Scheduler waits for the configured join time.
2. Meet bot launches Chrome with a persistent profile.
3. Bot mutes mic/camera, dismisses popups, joins safely.
4. Bot monitors meeting state, captures captions and chat.
5. AI generates summary, action items, decisions, learning outcomes.
6. Report is saved locally and meeting record is written to JSON DB.
7. VTU diary auto-fill runs after meeting end.
8. Optional timed shutdown is scheduled.

## Full Feature List

### Meeting Join Automation

- Scheduled join by IST time from config.
- Immediate run mode via CLI: `python meet_joiner.py --now`.
- One-time dynamic meet link override (`dynamic_link_override`) consumed automatically.
- Persistent Chrome profile for login/session reuse.
- Strict pre-join gate: waits for microphone and camera controls to be visible.
- Automatically disables microphone and camera before trying to join.
- Popup-safe join flow with repeated dialog dismissal.
- Handles join label variations: Ask to join, Join now, Ready to join, Rejoin, Try again.
- Waiting-room detection after Ask to join (waits for host admission instead of false failure).
- In-meeting state detection to stop retry loops once admitted.
- One-time automatic full Meet page reload if join controls are missing.
- Clear failure reasons (signed out, host did not admit in time, join controls missing).

### Resilience and Recovery

- Detects transient Meet errors and attempts recovery.
- Rejoin/retry actions for temporary Meet issue screens.
- Auto refresh attempts under transient failures.
- Auto rejoin once if removed (kicked) from meeting.
- Detects logout redirects to Google sign-in and reports this explicitly.
- Chrome launch retries and DOM-ready waits added for startup reliability.

### Live Monitoring and Capture

- Live captions enable attempt after join.
- Caption scraping every 15 minutes (interval configurable in code).
- Chat panel open attempts and periodic chat scraping.
- Captures pasted links from chat messages.
- Deduplicates repeated caption and chat lines.
- Filters known Google Meet UI noise from transcript text.
- Farewell phrase detection in captions to leave gracefully.

### Meeting End Detection

- Detects end states via URL changes, page text patterns, and title checks.
- Differentiates `host_ended`, `kicked`, `left`, `error` outcomes.
- Max-duration guard (`max_duration_minutes`) to avoid endless sessions.

### AI and Reporting

- AI transcript analysis using Groq LLaMA pipeline.
- Extracts summary, tasks, key decisions, learning outcomes.
- Context-aware fallback generation when transcript is empty.
- On no-record days, generates continuity summaries from recent days.
- On Fridays, generates weekly recap style summary.
- Writes structured text report to `reports/YYYY-MM-DD_HH-MM.txt`.
- Stores meeting history and AI output in `meetings_db.json`.

### Optional WhatsApp Tools (Separate from Meet Joiner)

- `meet_joiner.py` is now local-first and does not require WhatsApp or Twilio.
- `whatsapp_notifier.py` and `whatsapp_bot_server.py` remain available as optional separate utilities.

### VTU Internship Diary Automation

- Runs automatically after meeting ends (host ended or left states).
- Can run standalone with test mode (`--test`) and date override (`--date YYYY-MM-DD`).
- Uses dedicated persistent profile (`chrome_profile_vtu`).
- Auto-fills summary/learnings/hours/skills from latest report.
- Adds extra skill tags from detected keywords (for example Google/Cloud).

### System and Scheduling

- Sleep prevention while bot is active (Windows execution state API).
- Optional scheduled shutdown based on `shutdown_time_ist`.
- Windows launcher batch script with user menu:
  - scheduler mode
  - join-now mode
- Ready for Windows Task Scheduler unattended runs.
- Works with system Python directly (virtual environment is optional).

## Project Structure

```
MeetFlow/
|- meet_joiner.py            # Core scheduler + Google Meet automation
|- ai_processor.py           # Transcript analysis and structured AI output
|- vtu_diary.py              # VTU diary form automation
|- whatsapp_notifier.py      # Twilio notifications and DB updates
|- whatsapp_bot_server.py    # WhatsApp command webhook server
|- setup_login.py            # One-time Google login setup helper
|- config.json               # Runtime configuration
|- requirements.txt          # Python dependencies
|- run_meet_joiner.bat       # Windows launcher for scheduler/join-now
|- run_whatsapp_server.bat   # Starts WhatsApp bot server
|- reports/                  # Generated report files
|- chrome_profile/           # Google Meet browser profile
|- chrome_profile_vtu/       # VTU portal browser profile
|- meetings_db.json          # Meeting history database
|- .env                      # Secrets and credentials
```

## Configuration Reference

Edit `config.json`:

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

Key fields:

- `meet_link`: default meeting URL.
- `dynamic_link_override`: one-time replacement link (usually set by WhatsApp `setlink`).
- `dynamic_link_override`: one-time replacement link (consumed at actual join time).
- `join_time_ist`: scheduler join time.
- `shutdown_time_ist`: target shutdown time after run.
- `max_duration_minutes`: hard meeting cutoff.
- `vtu_hours`: default diary hours fallback.
- `vtu_skills`: baseline diary skills list.

## Setup

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Create `.env`

```env
GROQ_API_KEY=your_groq_api_key
VTU_USERNAME=your_vtu_email@gmail.com
VTU_PASSWORD=yourPassword
```

Optional only if you use WhatsApp helper scripts:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
```

### 3) One-time Google login session

```bash
python setup_login.py
```

### 4) One-time VTU portal session check

```bash
python vtu_diary.py --test
```

## Usage

### Start scheduler mode

```bash
python meet_joiner.py
```

### Join immediately

```bash
python meet_joiner.py --now
```

### Use batch launcher (Windows)

Double-click `run_meet_joiner.bat` and choose:

1. Scheduler mode
2. Join right now

### VTU diary manual runs

```bash
python vtu_diary.py --test
python vtu_diary.py --date 2026-03-22
```

### WhatsApp webhook server

```bash
python whatsapp_bot_server.py
```

Expose with ngrok and point Twilio sandbox webhook to:

`https://<your-ngrok-domain>/whatsapp`

## Troubleshooting

| Issue                       | Likely Cause                                         | Fix                                                                   |
| --------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------- |
| Could not find Join button  | Waiting-room state, signed-out session, UI variation | Re-run `setup_login.py`, confirm profile path, keep updated selectors |
| Join controls never appear  | Transient Meet page state                            | Bot now auto-reloads once; if still failing, re-open link and retry   |
| Redirected to Google login  | Session expired in profile                           | Sign in again using `setup_login.py`                                  |
| Chrome version mismatch     | `CHROME_VER` differs from installed browser          | Update `CHROME_VER` in scripts                                        |
| AI fallback not running     | `GROQ_API_KEY` missing                               | Add `GROQ_API_KEY` in `.env`                                          |
| VTU login failure           | Invalid creds/session expired                        | Verify `.env` and re-login with `vtu_diary.py --test`                 |
| No reports generated        | Meeting ended too early or AI path failed            | Check console logs and `reports/` write permissions                   |
| PC not waking for scheduler | Wake timers disabled                                 | Enable wake timers in Windows power settings                          |

## Security Notes

Never publish or share:

- `chrome_profile/`
- `chrome_profile_vtu/`
- `.env`
- `meetings_db.json`

These contain active sessions, credentials, and personal records.

## Tech Stack

- Python 3.10+
- Selenium + undetected-chromedriver
- Groq API (LLaMA)
- Flask (optional WhatsApp webhook utility)
- Twilio WhatsApp Sandbox (optional utility)
- python-dotenv
