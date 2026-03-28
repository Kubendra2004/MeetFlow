# MeetFlow — Intelligent Meeting Automator

MeetFlow automates your entire Google Meet workflow end-to-end:
joining meetings, capturing live captions, generating AI summaries,
saving reports, **automatically sending them to your WhatsApp via Twilio**,
and letting you **query any past report by date directly from WhatsApp**.
Everything starts automatically on Windows login — zero manual steps.

---

## How It Works

```
Windows Login
      ↓
startup_meetflow.bat runs automatically
      ↓
┌─────────────────────────────────────────────────────┐
│  1. 🌐 Flask WhatsApp Bot Server starts (port 5000) │
│  2. 🔗 ngrok tunnel opens (public URL)              │
│  3. 🔄 Twilio webhook auto-updated with ngrok URL   │
│  4. 🤖 Meet Joiner starts, waits for scheduled time │
└─────────────────────────────────────────────────────┘
      ↓
Meeting joins automatically at scheduled time
      ↓
Captions captured → AI analysis → Report saved (.txt)
      ↓
📲 WhatsApp report sent via Twilio (Auto-Send)
      ↓
📝 VTU Internship Diary updated (Auto-Fill)
      ↓
💬 Query past reports anytime via WhatsApp ("today", "list", etc.)
```

---

## Full Feature List

### Meeting Join Automation

- Scheduled join by IST time from `config.json`.
- Immediate run mode via CLI: `python meet_joiner.py --now`.
- One-time dynamic meet link override (`setlink` WhatsApp command).
- Persistent Chrome profile for login/session reuse.
- Auto mic and camera mute before joining.
- Popup-safe join flow with repeated dialog dismissal.
- Handles join label variations: Ask to join, Join now, Ready to join, Rejoin, Try again.
- Waiting-room detection (waits for host admission without false failure).
- In-meeting state detection to stop retry loops once admitted.
- Clear failure reasons (signed out, host not admitted, join controls missing).

### Resilience and Recovery

- Detects transient Meet errors and attempts recovery.
- Rejoin/retry actions for temporary Meet issue screens.
- Auto refresh attempts under transient failures.
- Detects logout redirects to Google sign-in and reports explicitly.

### Live Monitoring and Capture

- Live captions enabled automatically after joining.
- Caption scraping every 5 seconds.
- Smart filtering by importance score (deadlines, tasks, keywords).
- Chat panel auto-open and periodic chat scraping.
- Captures pasted links from chat messages.
- Deduplicates repeated caption and chat lines.
- Filters known Google Meet UI noise from transcript text.
- Farewell phrase detection in captions to leave gracefully.

### Meeting End Detection

- Detects end states via URL changes, page text patterns, and title checks.
- Differentiates `host_ended`, `kicked`, `left`, `error` outcomes.
- Participant-count-based end detection (leaves when only 1 person remains).
- Max-duration guard (`max_duration_minutes`) to avoid endless sessions.

### AI and Reporting

- AI transcript analysis using Groq LLaMA pipeline.
- Extracts: summary, tasks (with urgency + deadlines), key decisions, learning outcomes.
- Fallback content generation if transcript is sparse or empty.
- Writes structured text report to `reports/YYYY-MM-DD_HH-MM.txt`.
- Stores meeting history and AI output in `meetings_db.json`.

### WhatsApp Integration (Twilio)

#### Auto-Send After Every Meeting
- After every class ends, the full report is **automatically sent** to your WhatsApp.
- Includes: AI summary, key decisions, urgent action items with deadlines.
- Sent in chunks if content is long (Twilio 1500-char limit handled).

#### Interactive WhatsApp Bot (Query Any Report)
Send any of these commands to the Twilio WhatsApp Sandbox number:

| Command | What You Get |
|---|---|
| `help` | Full command menu |
| `today` | Today's full meeting report |
| `yesterday` | Yesterday's report |
| `list` | All available report dates |
| `2026-03-28` | Full report for any specific date |
| `stats` | All-time totals (sessions, time, files) |
| `setlink <URL>` | Override the next meeting link |

Also sends alerts for:
- ✅ Join success notification
- ❌ Join failure with reason
- ⏰ 20-minute pre-join reminder

### Auto-Startup (Zero Manual Steps)

- **Windows Registry** startup entry added via `add_to_startup.py`.
- `startup_meetflow.bat` launches all services in the background on login.
- `update_twilio_webhook.py` auto-fetches ngrok's new URL and updates Twilio.
- All service output logged to `logs/` folder.

### VTU Internship Diary Automation

- Runs automatically after meeting ends.
- Can run standalone: `--test` and `--date YYYY-MM-DD` flags.
- Uses dedicated persistent profile (`chrome_profile_vtu`).
- Auto-fills summary/learnings/hours/skills from latest report.

### System and Scheduling

- Sleep prevention while bot is active (Windows execution state API).
- Optional scheduled shutdown based on `shutdown_time_ist`.
- Windows launcher batch scripts for all services.

---

## Project Structure

```
MeetFlow/
├── meet_joiner.py            # Core scheduler + Google Meet automation
├── ai_processor.py           # Transcript analysis and structured AI output
├── whatsapp_notifier.py      # Twilio notifications, auto-send after meeting
├── whatsapp_bot_server.py    # WhatsApp command bot (query reports by date)
├── update_twilio_webhook.py  # Auto-updates Twilio webhook with new ngrok URL
├── send_to_whatsapp.py       # Manual one-shot: send today's report to WhatsApp
├── add_to_startup.py         # Registers MeetFlow in Windows startup (registry)
├── startup_meetflow.bat      # Master launcher: Flask + ngrok + webhook + bot
├── run_meet_joiner.bat       # Windows launcher for scheduler/join-now
├── run_whatsapp_server.bat   # Starts WhatsApp bot server + ngrok manually
├── vtu_diary.py              # VTU diary form automation
├── setup_login.py            # One-time Google login setup helper
├── config.json               # Runtime configuration
├── requirements.txt          # Python dependencies
├── .env                      # Secrets and credentials
├── reports/                  # Generated .txt report files (one per session)
├── logs/                     # Service logs (bot_server, ngrok, meet_joiner)
├── meetings_db.json          # Meeting history database (JSON)
├── chrome_profile/           # Google Meet browser profile (persistent session)
└── chrome_profile_vtu/       # VTU portal browser profile
```

---

## Setup Guide

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create `.env`

```env
GROQ_API_KEY=your_groq_api_key
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
VTU_USERNAME=your_vtu_email@gmail.com
VTU_PASSWORD=yourPassword
```

### 3. One-time Google login session

```bash
python setup_login.py
```

### 4. Configure your meeting

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

### 5. Register auto-startup (one-time)

```bash
python add_to_startup.py
```

This adds MeetFlow to the Windows Registry startup — everything will run automatically on every login from now on.

### 6. One-time: Set Twilio WhatsApp Sandbox webhook

On the **very first run**, `update_twilio_webhook.py` will print a URL like:

```
https://abcd-1234.ngrok-free.app/whatsapp
```

Go to [Twilio Sandbox Settings](https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox) and paste it as the **"WHEN A MESSAGE COMES IN"** webhook URL. After this, it updates itself automatically on every restart.

---

## Usage

### Fully Automatic (Recommended)

After running `python add_to_startup.py` once, just **log into Windows** — everything starts by itself.

### Manual Launch

```bash
# Start all services at once
startup_meetflow.bat

# Or start individual services:
python meet_joiner.py          # Join at scheduled time
python meet_joiner.py --now    # Join immediately
python whatsapp_bot_server.py  # Start WhatsApp bot server
python send_to_whatsapp.py     # Manually send today's report to WhatsApp
```

### Get a Report via WhatsApp

Send any of these to **+1 415 523 8886** on WhatsApp:

```
today               ← today's full report
yesterday           ← yesterday's report
2026-03-28          ← any specific date
list                ← all available dates
stats               ← totals summary
help                ← command menu
setlink https://meet.google.com/xxx-yyy-zzz
```

### VTU Diary

```bash
python vtu_diary.py --test
python vtu_diary.py --date 2026-03-28
```

---

## Troubleshooting

| Issue | Likely Cause | Fix |
|---|---|---|
| No WhatsApp reply to commands | Bot server not running or webhook not set | Run `startup_meetflow.bat`, check ngrok window for URL |
| Twilio webhook keeps changing | ngrok URL resets on restart | `update_twilio_webhook.py` handles this automatically |
| Could not find Join button | Waiting-room, signed-out session | Re-run `setup_login.py`, verify Chrome profile |
| Redirected to Google login | Session expired in profile | Sign in again using `setup_login.py` |
| Chrome version mismatch | `CHROME_VER` differs from browser | Update `CHROME_VER` constant in `meet_joiner.py` |
| No WhatsApp notifications | Missing Twilio credentials | Verify `.env` values |
| No report generated | Meeting too short or AI failed | Check `logs/meet_joiner.log` |
| Auto-startup not working | Registry entry missing | Re-run `python add_to_startup.py` |
| PC not waking for scheduler | Wake timers disabled | Enable wake timers in Windows power settings |

---

## Security Notes

**Never publish or share:**

- `chrome_profile/` — active Google session
- `chrome_profile_vtu/` — active VTU session
- `.env` — API keys and passwords
- `meetings_db.json` — personal meeting records

---

## Tech Stack

| Component | Technology |
|---|---|
| Meeting automation | Python + Selenium + undetected-chromedriver |
| AI analysis | Groq API (LLaMA 3.3 70B + Whisper) |
| WhatsApp notifications | Twilio WhatsApp Sandbox |
| WhatsApp bot server | Flask |
| ngrok tunnel | ngrok (auto-updated via REST API) |
| Auto-startup | Windows Registry Run key |
| Config | python-dotenv + config.json |
| Runtime | Python 3.10+ |
