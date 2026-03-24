# 🤖 Google Meet Auto-Joiner v2

Automatically joins Google Meet at a scheduled time, records audio, generates an AI summary with tasks and deadlines, and sends everything to your WhatsApp. Shuts down your PC when the host ends the meeting.

---

## ⚠️ SECURITY — READ FIRST

> **NEVER share the `chrome_profile/`, `.env`, or `meetings_db.json` files.**
> - `chrome_profile/` = your Google login session (like giving someone your password)
> - `.env` = your Twilio and Gemini API keys
>
> When sharing with friends, only send: `meet_joiner.py`, `test_meet.py`, `requirements.txt`, `run_meet_joiner.bat`, `README.md`, `audio_recorder.py`, `ai_processor.py`, `whatsapp_notifier.py`, `whatsapp_bot_server.py`
>
> Your friend **must do their own setup** (Step 5 below) to create their own login session.

---

## 🚀 What It Does

```
12:45 PM  → PC wakes from sleep (Task Scheduler)
           ↓
           Bot starts, fetches real IST time from internet
           ↓
1:00 PM   → Chrome opens (resource-optimised)
           → Mic & camera auto-muted
           → "Ask to join" / "Join now" clicked
           ↓
           In meeting:
           → Audio recorded (16kHz, speech quality)
           → Popups auto-dismissed
           → Monitors for host-end / being kicked
           ↓
If KICKED → Auto-rejoins once (15s delay)
           ↓
Host ends → Audio recording stops
         → Gemini AI transcribes & analyses
         → WhatsApp report sent (summary + tasks + deadlines)
         → PC shuts down
```

---

## 📋 Requirements

1. **Windows PC**
2. **Google Chrome** — [Download](https://www.google.com/chrome/)
3. **Python 3.10+** — [Download](https://www.python.org/downloads/) *(tick "Add to PATH"!)*
4. **Twilio account** (free) — [Sign up](https://www.twilio.com/)
5. **Google Gemini API key** — [Get one](https://aistudio.google.com/app/apikey)

---

## 🛠️ Setup (Step by Step)

### Step 1 — Put All Files in One Folder
Example: `C:\Users\YourName\google meet joiner\`

### Step 2 — Open Terminal in That Folder
Click the address bar in File Explorer, type `cmd`, press Enter.

### Step 3 — Install Libraries
```
pip install -r requirements.txt
```

### Step 4 — Fill in Your Credentials
Create a file called `.env` in the folder with:
```
Gemini=YOUR_GEMINI_API_KEY
TWILIO_ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_AUTH_TOKEN = "your_auth_token_here"
```

### Step 5 — Configure Your Meeting
Edit `config.json`:
```json
{
  "meet_link": "https://meet.google.com/your-code-here",
  "dynamic_link_override": null,
  "join_time_ist": "13:00"
}
```

### Step 6 — Sign into Google (One-Time)
1. In `meet_joiner.py`, set `TEST_MODE = True`
2. Run: `python meet_joiner.py`
3. Sign into Google in the Chrome window that opens
4. Press Ctrl+C to stop
5. Set `TEST_MODE = False` again

### Step 7 — Set Up Twilio WhatsApp Sandbox (One-Time)
1. Open WhatsApp → message **+1 415 523 8886**
2. Send: `join <your-sandbox-keyword>` (find keyword in [Twilio Console](https://console.twilio.com/))

### Step 8 — Test Everything
```
python test_meet.py
```
All 7 tests should pass. Press Ctrl+C after Test 7 starts.

---

## 🏃 How to Run

### Manual
Double-click `run_meet_joiner.bat` — or in cmd:
```
python meet_joiner.py
```

### Fully Automatic (Task Scheduler)
1. Press `Win+R` → `taskschd.msc` → Enter
2. Click **Create Task**
3. **General:** Name it, tick *Run with highest privileges*
4. **Triggers → New:** Daily at **12:45 PM**, tick ✅ *Wake the computer*
5. **Actions → New:** Program = full path to `run_meet_joiner.bat`
6. **Settings:** Tick *Allow task to be run on demand*
7. OK → enter Windows password

**Enable wake timers:** Settings → Power & Sleep → Advanced power settings → Sleep → Allow wake timers → **Enable**

---

## 💬 WhatsApp Bot Commands

Run `run_whatsapp_server.bat` (requires [ngrok](https://ngrok.com/) to expose it publicly).

| Text this | Bot replies with |
|-----------|-----------------|
| `hello` / `help` | Overview + available commands |
| `2026-02-28` | Full meeting record for that date |
| `today` | Today's meeting record |
| `stats` | Total meetings + hours |
| `setlink https://meet.google.com/xxx` | Override today's meeting link |

---

## 📱 WhatsApp Report (After Meeting)

```
🤖 Google Meet Bot — Meeting Report
==============================
📅 2026-02-28  |  ⏱️ Duration: 1h 15m

📝 Summary:
The team reviewed sprint progress...

🔑 Key Decisions:
🔑 Launch confirmed for March 15

📋 Action Items:

🚨 [URGENT] Finalise mockups for client
    👤 Kubi
    ⏰ Deadline: Tomorrow

✅ Update API docs
    ⏰ Deadline: End of week

💤 Shutting down PC in 10 seconds...
```

---

## ⚡ Resource Optimisations Applied

| Area | Optimisation | Saving |
|------|-------------|--------|
| Chrome | 12 efficiency flags | ~30% less RAM |
| Chrome | Images blocked | ~50% less render memory |
| Chrome | V8 heap capped at 512 MB | Prevents memory bloat |
| Scheduler | Adaptive sleep (60s/30s/5s) | ~95% less CPU while idle |
| Monitoring | JS body text vs full page_source | ~80% less memory per check |
| Audio | 16kHz sample rate (was 44100) | ~4x smaller files |
| Process | BELOWNORMAL priority (bat file) | PC stays responsive |

---

## 📁 File Guide

| File | Purpose |
|------|---------|
| `meet_joiner.py` | Main bot |
| `audio_recorder.py` | Mic recording during meeting |
| `ai_processor.py` | Gemini transcription + task extraction |
| `whatsapp_notifier.py` | WhatsApp alerts |
| `whatsapp_bot_server.py` | Flask bot server for queries |
| `test_meet.py` | 7-test verification suite |
| `config.json` | Meeting link + join time |
| `run_meet_joiner.bat` | Launch bot (low priority) |
| `run_whatsapp_server.bat` | Launch Flask bot server |
| `recordings/` | Meeting audio files |
| `meetings_db.json` | ⚠️ Meeting history — don't share |
| `chrome_profile/` | ⚠️ Google login — **NEVER share** |
| `.env` | ⚠️ API keys — **NEVER share** |

---

## 🔧 Troubleshooting

| Problem | Fix |
|---------|-----|
| Chrome version error | Update `CHROME_VER = 145` in `meet_joiner.py` to match your Chrome version |
| Not signed in | Delete `chrome_profile/`, redo Step 6 |
| PC doesn't wake | Enable wake timers in Power Options |
| No WhatsApp messages | Check `.env` Twilio credentials; ensure you joined the Sandbox (Step 7) |
| Gemini errors | Check your `Gemini` API key in `.env` |
