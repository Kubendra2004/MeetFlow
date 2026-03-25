"""
whatsapp_notifier.py
Sends WhatsApp notifications via Twilio and logs all meeting records
to meetings_db.json.
"""
import os
import json
import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip().strip('"')
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "").strip().strip('"')
TWILIO_WA_NUMBER   = "whatsapp:+14155238886"    # Twilio Sandbox number
MY_PHONE_NUMBER    = "whatsapp:+917022949724" #  Your WhatsApp number

DB_FILE = "meetings_db.json"
IST     = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def _get_client():
    """Return a Twilio client, or None if credentials are missing."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("[WhatsApp] ⚠️  Twilio credentials missing in .env — WhatsApp disabled.")
        return None
    try:
        from twilio.rest import Client
        return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except ImportError:
        print("[WhatsApp] ⚠️  twilio package not installed.")
        return None


def send_whatsapp(message: str):
    """Send any WhatsApp message. Silently skips if credentials are missing."""
    client = _get_client()
    if not client:
        return
    try:
        msg = client.messages.create(
            from_=TWILIO_WA_NUMBER,
            body=message,
            to=MY_PHONE_NUMBER
        )
        print(f"[WhatsApp] ✅ Sent (SID: {msg.sid})")
    except Exception as e:
        print(f"[WhatsApp] ❌ Failed: {e}")


# ── Public notification functions ─────────────────────────

def notify_joined(meet_link: str, join_time: datetime.datetime):
    """Alert sent as soon as the bot successfully joins."""
    date_str = join_time.strftime("%Y-%m-%d")
    time_str = join_time.strftime("%I:%M %p IST")

    send_whatsapp(
        f"🤖 *Google Meet Bot*\n"
        f"✅ *Joined meeting!*\n\n"
        f"📅 {date_str}  🕐 {time_str}\n"
        f"🔗 {meet_link}"
    )

    _log_meeting(date_str, {
        "meet_link":        meet_link,
        "joined_at":        join_time.isoformat(),
        "ended_at":         None,
        "duration_minutes": None,
        "summary":          "Auto-joined by bot",
        "tasks":            [],
        "key_decisions":    [],
        "transcript":       ""
    })


def notify_failed(meet_link: str, error: str):
    """Alert sent when the bot fails to join."""
    send_whatsapp(
        f"🤖 *Google Meet Bot*\n"
        f"❌ *Failed to join!*\n\n"
        f"� {meet_link}\n"
        f"⚠️ {error}\n\n"
        f"_Check Chrome sign-in or the link._"
    )


def notify_reminder(meet_link: str, minutes_before: int, join_time: datetime.datetime):
    """Reminder alert sent N minutes before the meeting."""
    time_str = join_time.strftime("%I:%M %p IST")
    send_whatsapp(
        f"🤖 *Google Meet Bot*\n"
        f"⏰ *Meeting in {minutes_before} minutes!*\n\n"
        f"🕐 Joining at {time_str}\n"
        f"🔗 {meet_link}\n\n"
        f"_Mic & camera will be muted automatically._"
    )


def notify_ended_with_summary(meet_link: str,
                               join_time: datetime.datetime,
                               end_time:  datetime.datetime,
                               ai_results: dict):
    """
    Full post-meeting report:
      duration | AI summary | key decisions | tasks (🚨 urgent, ⏰ deadline, 👤 assignee)
    """
    delta      = end_time - join_time
    total_mins = max(0, int(delta.total_seconds() // 60))
    hours, mins = divmod(total_mins, 60)
    date_str   = join_time.strftime("%Y-%m-%d")
    dur_str    = f"{hours}h {mins}m" if hours else f"{mins}m"

    summary       = ai_results.get("summary", "No summary available.")
    tasks         = ai_results.get("tasks",         [])
    key_decisions = ai_results.get("key_decisions", [])

    # ── Format tasks ───────────────────────────────────────
    task_lines = []
    for t in tasks:
        if isinstance(t, dict):
            text     = t.get("task", "")
            assignee = t.get("assignee", "Unassigned")
            deadline = t.get("deadline", "")
            urgent   = t.get("urgent",       False)
            has_dl   = t.get("has_deadline", False)

            line = f"🚨 *[URGENT]* {text}" if urgent else f"✅ {text}"
            if assignee and assignee.lower() not in ("unassigned", ""):
                line += f"\n    👤 _{assignee}_"
            if has_dl and deadline and "no deadline" not in deadline.lower():
                line += f"\n    ⏰ *Deadline: {deadline}*"
            task_lines.append(line)
        else:
            task_lines.append(f"✅ {t}")

    task_block = ("\n\n".join(task_lines)) if task_lines else "No specific tasks identified."

    # ── Format key decisions ───────────────────────────────
    dec_block = ""
    if key_decisions:
        dec_block = "\n\n*🔑 Key Decisions:*\n" + "\n".join(f"🔑 {d}" for d in key_decisions)

    message = (
        f"🤖 *Google Meet Bot — Meeting Report*\n"
        f"{'─'*32}\n"
        f"📅 {date_str}  |  ⏱️ {dur_str}\n"
        f"🔗 {meet_link}\n\n"
        f"*📝 Summary:*\n{summary}"
        f"{dec_block}\n\n"
        f"*📋 Action Items:*\n\n"
        f"{task_block}\n\n"
        f"💤 _Shutting down in 10 seconds..._"
    )

    send_whatsapp(message)
    _update_meeting_end(date_str, end_time.isoformat(), total_mins)


# ── DB helpers ────────────────────────────────────────────
def _load_db() -> dict:
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[DB] Failed to load {DB_FILE}: {e}")
    return {}


def _save_db(db: dict):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[DB] Failed to save {DB_FILE}: {e}")


def _log_meeting(date_str: str, record: dict):
    db = _load_db()
    db.setdefault(date_str, [])
    db[date_str].append(record)
    _save_db(db)
    print(f"[DB] Meeting logged for {date_str}.")


def _update_meeting_end(date_str: str, ended_at: str, duration_minutes: int):
    db = _load_db()
    if date_str in db and db[date_str]:
        db[date_str][-1]["ended_at"]         = ended_at
        db[date_str][-1]["duration_minutes"] = duration_minutes
        _save_db(db)
        print(f"[DB] End time updated for {date_str}.")


def _update_meeting_analysis(date_str: str, summary: str,
                              tasks: list, transcript: str = ""):
    """Save AI-generated content to the last meeting record of the given date."""
    db = _load_db()
    if date_str in db and db[date_str]:
        db[date_str][-1]["summary"]    = summary
        db[date_str][-1]["tasks"]      = tasks
        db[date_str][-1]["transcript"] = transcript
        _save_db(db)
        print(f"[DB] AI analysis saved for {date_str}.")
