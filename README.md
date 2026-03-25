# MeetFlow — Intelligent Meeting Assistant & Internship Diary Automator

> A personal productivity tool that automates the full lifecycle of an online meeting — from auto-joining and real-time transcription to AI-powered report generation and internship diary submission.

---

## ✨ Overview

**MeetFlow** is a Python-based automation pipeline designed to streamline online meeting management and post-meeting reporting. It leverages AI to extract meaningful insights from meetings and automatically populates structured daily logs on a student internship portal.

### What it does
```
Scheduled Start
  → Chrome opens silently in the background
  → Joins Google Meet at the scheduled time (mic & camera muted)
  → Quietly collects live captions every 15 minutes
  ↓
Meeting Ends (detected automatically)
  → AI processes the session transcript (Groq LLaMA)
  → Generates a 3-point Learning Outcomes summary in plain text
  → Saves a structured daily report  (reports/YYYY-MM-DD.txt)
  ↓
Internship Portal Submission (fully automated)
  → Headless Chrome logs into the internship portal
  → Fills date, work summary, hours (randomised 8–12), learning outcomes & skills
  → Detects keywords (e.g. "cloud", "Google") and adds relevant skills dynamically
  → Diary submitted automatically — no user interaction needed
  ↓
Session Complete
  → PC shuts down on schedule
```

---

## 🧠 AI Pipeline

| Stage | Model / Library | Purpose |
|-------|----------------|---------|
| Caption cleanup | Python regex | Filter UI noise from raw captions |
| Transcript analysis | Groq LLaMA 3 | Summarise, extract tasks & learning outcomes |
| Fallback generation | Groq LLaMA 3 | Generate realistic diary entry if no captions |
| Output formatting | JSON schema | Structured 3-point plain-text learning outcomes |

---

## 📁 Project Structure

```
MeetFlow/
│
├── meet_joiner.py          # Core bot: joins meeting, scrapes captions, triggers pipeline
├── ai_processor.py         # AI: transcript cleaning, analysis, fallback generation
├── vtu_diary.py            # Portal automation: headless diary submission
├── whatsapp_notifier.py    # Post-meeting WhatsApp notification helper
├── whatsapp_bot_server.py  # Flask-based WhatsApp query bot
│
├── config.json             # Meeting link, join time, skills, hours config
├── requirements.txt        # Python dependencies
├── run_meet_joiner.bat     # One-click Windows launcher (low-priority process)
├── run_whatsapp_server.bat # Starts the WhatsApp bot Flask server
│
├── reports/                # Auto-generated daily meeting reports (gitignored)
├── chrome_profile/         # Persistent Chrome session (gitignored — never share)
├── chrome_profile_vtu/     # Persistent VTU portal session (gitignored — never share)
├── .env                    # API keys (gitignored — never share)
└── meetings_db.json        # Meeting history database (gitignored)
```

---

## ⚙️ Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure credentials
Create a `.env` file:
```
GROQ_API_KEY=your_groq_api_key
VTU_USERNAME=your_vtu_email@gmail.com
VTU_PASSWORD=yourPassword
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
```

### 3. Configure your meeting
Edit `config.json`:
```json
{
  "meet_link": "https://meet.google.com/your-code-here",
  "join_time_ist": "13:00",
  "vtu_skills": ["Android Studio", "Kotlin"],
  "vtu_hours": 9.0
}
```

### 4. One-time Google login
1. Set `TEST_MODE = True` in `meet_joiner.py`
2. Run `python meet_joiner.py`
3. Log into Google in the Chrome window that opens
4. Press `Ctrl+C`, then set `TEST_MODE = False`

### 5. One-time VTU login
```bash
python vtu_diary.py --test
```
Log in manually in the Chrome window. Future runs will use the saved session.

---

## 🚀 Usage

### Run manually
```bash
python meet_joiner.py
# or double-click:
run_meet_joiner.bat
```

### Test VTU diary submission (no submit click)
```bash
python vtu_diary.py --test
```

### Submit diary for a specific past date
```bash
python vtu_diary.py --date 2026-03-22
```

### Fully automatic via Windows Task Scheduler
1. `Win+R` → `taskschd.msc`
2. Create Task → Trigger: Daily at 12:45 PM, *Wake computer*
3. Action: Full path to `run_meet_joiner.bat`
4. Enable wake timers in Power Options → Sleep → Allow wake timers

---

## 💬 WhatsApp Bot Commands

Run `run_whatsapp_server.bat` (requires [ngrok](https://ngrok.com/)):

| Command | Response |
|---------|----------|
| `hello` / `help` | Available commands |
| `today` | Today's meeting record |
| `2026-03-25` | Report for that date |
| `stats` | Total meetings and hours |
| `setlink https://meet.google.com/xxx` | Override meeting link |

---

## 🔧 Troubleshooting

| Problem | Fix |
|---------|-----|
| Chrome version mismatch | Update `CHROME_VER` in `meet_joiner.py` to match your Chrome version |
| Not signed in to Google | Delete `chrome_profile/`, redo the one-time login step |
| VTU portal login lost | Delete `chrome_profile_vtu/`, redo the VTU login step |
| AI errors (400/context too long) | Captions are now scraped every 15 min — should not occur |
| PC doesn't wake | Enable wake timers in Power Options |

---

## 🔐 Security

> **NEVER share or upload these files/folders:**
> - `chrome_profile/` and `chrome_profile_vtu/` — your login sessions
> - `.env` — your API keys
> - `meetings_db.json` — your meeting history

All three are listed in `.gitignore` and will never be committed to version control.

---

## 🛠️ Tech Stack

- **Python 3.10+**
- **Selenium / undetected-chromedriver** — browser automation
- **Groq API (LLaMA 3)** — AI transcript analysis
- **Flask** — WhatsApp bot server
- **python-dotenv** — credential management
