"""
whatsapp_bot_server.py
Flask server that receives incoming WhatsApp messages via Twilio webhook.

Run with:  python whatsapp_bot_server.py
Expose publicly with ngrok: ngrok http 5000
Set Twilio Sandbox webhook to: https://<ngrok-url>/whatsapp

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AVAILABLE COMMANDS (send via WhatsApp):
  help          → show this menu
  today         → today's full report
  yesterday     → yesterday's full report
  list          → list all available report dates
  YYYY-MM-DD    → full report for that date (e.g. 2026-03-28)
  stats         → all-time meeting totals
  setlink URL   → override meet link for next joining
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os
import glob
import json
import datetime
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

try:
    from twilio.twiml.messaging_response import MessagingResponse
    from twilio.rest import Client as TwilioClient
    _TWILIO_OK = True
except ImportError:
    _TWILIO_OK = False

app        = Flask(__name__)
DB_FILE    = "meetings_db.json"
CONFIG     = "config.json"
REPORTS_DIR = "reports"
IST        = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip().strip('"')
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "").strip().strip('"')
TWILIO_WA_NUMBER   = "whatsapp:+14155238886"
MY_PHONE_NUMBER    = "whatsapp:+917022949724"


# ── Twilio proactive sender (for multi-part replies) ──────
def _send_wa(message: str):
    """Send outbound WhatsApp message via Twilio (for long chunked replies)."""
    if not _TWILIO_OK or not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        chunks = [message[i:i+1500] for i in range(0, len(message), 1500)]
        for chunk in chunks:
            client.messages.create(
                from_=TWILIO_WA_NUMBER,
                body=chunk,
                to=MY_PHONE_NUMBER
            )
    except Exception as e:
        print(f"[BotServer] WhatsApp send error: {e}")


# ── Health check ──────────────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    reports = _list_report_dates()
    dates_html = "".join(f"<li>{d}</li>" for d in reports[-10:]) if reports else "<li>None yet</li>"
    return (
        "<h1 style='font-family:sans-serif;color:green'>🟢 MeetFlow Bot Server Running!</h1>"
        "<p style='font-family:sans-serif'>"
        "Twilio webhook: <code>/whatsapp</code><br><br>"
        "<b>Commands:</b><br>"
        "<code>help</code> | <code>today</code> | <code>yesterday</code> | "
        "<code>list</code> | <code>stats</code> | "
        "<code>2026-03-28</code> | <code>setlink https://meet.google.com/xxx</code>"
        "</p>"
        f"<p><b>Recent reports:</b><ul>{dates_html}</ul></p>"
    )


# ── WhatsApp webhook ──────────────────────────────────────
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    if not _TWILIO_OK:
        return "Twilio not installed", 500

    incoming       = request.values.get("Body", "").strip()
    incoming_lower = incoming.lower().strip()

    resp = MessagingResponse()
    msg  = resp.message()

    db = _load_db()

    # ── setlink ───────────────────────────────────────────
    if incoming_lower.startswith("setlink "):
        new_link = incoming.split(" ", 1)[1].strip()
        if "meet.google.com/" in new_link:
            cfg = _load_config()
            cfg["dynamic_link_override"] = new_link
            _save_config(cfg)
            msg.body(
                f"🤖 *MeetFlow Bot*\n"
                f"✅ *Next meeting link updated!*\n\n"
                f"🔗 {new_link}\n\n"
                f"_Bot will join this link next time._"
            )
        else:
            msg.body(
                "❌ Invalid Meet link.\n"
                "Format: `setlink https://meet.google.com/xxx-xxxx-xxx`"
            )
        return str(resp)

    # ── help / greeting ───────────────────────────────────
    if incoming_lower in ("hi", "hello", "help", "start", "menu", ""):
        dates = _list_report_dates()
        recent = ", ".join(dates[-5:]) if dates else "None yet"
        msg.body(
            "🤖 *MeetFlow — WhatsApp Bot*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "*📋 Report Commands:*\n"
            "📅 `today` → today's full report\n"
            "📅 `yesterday` → yesterday's report\n"
            "📋 `list` → all available report dates\n"
            "🗓️ `2026-03-28` → report for that date\n\n"
            "*📊 Other Commands:*\n"
            "📊 `stats` → all-time meeting totals\n"
            "🔗 `setlink <URL>` → override meeting link\n\n"
            f"_Recent reports:_ {recent}"
        )
        return str(resp)

    # ── list all dates ────────────────────────────────────
    if incoming_lower == "list":
        dates = _list_report_dates()
        if not dates:
            msg.body("📭 No reports found yet.\nReports are saved after each meeting ends.")
            return str(resp)

        lines = ["📋 *Available Meeting Reports*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        for d in reversed(dates):   # newest first
            # count sessions for that date
            day_files = glob.glob(os.path.join(REPORTS_DIR, f"{d}_*.txt"))
            lines.append(f"📅 {d}  ({len(day_files)} session{'s' if len(day_files)!=1 else ''})")
        lines.append("\n_Send a date (e.g. 2026-03-28) to get that report._")
        msg.body("\n".join(lines))
        return str(resp)

    # ── today ─────────────────────────────────────────────
    if incoming_lower == "today":
        today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
        reply = _build_report_reply(today)
        _send_chunked_reply(msg, resp, reply)
        return str(resp)

    # ── yesterday ─────────────────────────────────────────
    if incoming_lower == "yesterday":
        yesterday = (datetime.datetime.now(IST) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        reply = _build_report_reply(yesterday)
        _send_chunked_reply(msg, resp, reply)
        return str(resp)

    # ── stats ─────────────────────────────────────────────
    if incoming_lower == "stats":
        total_days     = len(db)
        total_meetings = sum(len(v) if isinstance(v, list) else 1 for v in db.values())
        total_mins     = 0
        for day_data in db.values():
            records = day_data if isinstance(day_data, list) else [day_data]
            for r in records:
                total_mins += r.get("duration_minutes") or 0
        h, m = divmod(total_mins, 60)

        # Also count raw .txt files
        all_txts = glob.glob(os.path.join(REPORTS_DIR, "*.txt"))
        msg.body(
            f"🤖 *MeetFlow — All-Time Stats*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 Days with meetings: *{total_days}*\n"
            f"🔢 Total sessions:     *{total_meetings}*\n"
            f"⏱️ Total time:          *{h}h {m}m*\n"
            f"📄 Report files saved: *{len(all_txts)}*"
        )
        return str(resp)

    # ── date lookup (YYYY-MM-DD) ──────────────────────────
    import re
    if re.match(r"^\d{4}-\d{2}-\d{2}$", incoming):
        reply = _build_report_reply(incoming)
        _send_chunked_reply(msg, resp, reply)
        return str(resp)

    # ── unknown command ───────────────────────────────────
    msg.body(
        f"🤖 I didn't understand `{incoming}`.\n\n"
        "Send *help* to see all commands.\n"
        "Or send a date like *2026-03-28* to get that report."
    )
    return str(resp)


# ── Report builders ───────────────────────────────────────

def _list_report_dates() -> list[str]:
    """Return sorted list of unique dates that have .txt report files."""
    files = glob.glob(os.path.join(REPORTS_DIR, "*.txt"))
    dates = set()
    for f in files:
        basename = os.path.basename(f)          # e.g. 2026-03-28_13-26.txt
        date_part = basename[:10]               # e.g. 2026-03-28
        if len(date_part) == 10 and date_part[4] == "-" and date_part[7] == "-":
            dates.add(date_part)
    return sorted(dates)


def _build_report_reply(date_str: str) -> str:
    """
    Build the full reply string for a given date.
    Reads .txt report files for that date.
    Falls back to meetings_db.json if no .txt found.
    """
    # ── Find .txt files for this date ──────────────────────
    pattern = os.path.join(REPORTS_DIR, f"{date_str}_*.txt")
    files   = sorted(glob.glob(pattern))

    if not files:
        # Fall back to DB
        db = _load_db()
        if date_str in db:
            return _format_db_reply(date_str, db[date_str])
        dates = _list_report_dates()
        recent = ", ".join(reversed(dates[-5:])) if dates else "None yet"
        return (
            f"📭 No report found for *{date_str}*.\n\n"
            f"_Available dates:_ {recent}\n\n"
            f"Send *list* to see all dates."
        )

    # ── Read and format each session's .txt file ──────────
    parts = [f"📅 *Meeting Report — {date_str}*\n{'━'*30}\n"]

    for idx, filepath in enumerate(files, 1):
        session_label = f"📌 *Session {idx}*\n" if len(files) > 1 else ""
        parts.append(session_label + _extract_txt_summary(filepath))

    parts.append(f"\n_Send *list* to see other available dates._")
    return "\n".join(parts)


def _extract_txt_summary(filepath: str) -> str:
    """
    Read a .txt report and extract everything before the CAPTIONS section.
    Returns a clean, WhatsApp-ready string.
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"❌ Could not read report: {e}"

    lines = content.splitlines()
    clean = []
    for line in lines:
        if line.strip() in ("CAPTIONS", "CHAT LOG", "TRANSCRIPT") or \
           line.strip().startswith("---") and len(line.strip()) > 10:
            # Keep the section header but stop after CAPTIONS content
            if line.strip() == "CAPTIONS":
                break
            if line.strip() == "CHAT LOG":
                break
            if line.strip() == "TRANSCRIPT":
                break
        clean.append(line)

    # Trim trailing dashes/equals lines
    while clean and set(clean[-1].strip()) <= {"=", "-", " "}:
        clean.pop()

    return "\n".join(clean).strip()


def _format_db_reply(date_str: str, day_data) -> str:
    """Format a reply from meetings_db.json data (fallback)."""
    records = day_data if isinstance(day_data, list) else [day_data]
    lines = [f"📅 *Records for {date_str}*\n{'━'*30}\n"]

    for i, r in enumerate(records, 1):
        joined   = (r.get("joined_at") or "?")[:16].replace("T", " ")
        ended    = r.get("ended_at")
        ended    = ended[:16].replace("T", " ") if ended else "In progress"
        dur_mins = r.get("duration_minutes")
        dur      = f"{dur_mins//60}h {dur_mins%60}m" if dur_mins else "N/A"
        link     = r.get("meet_link", "N/A")
        summary  = r.get("summary", "N/A")
        tasks    = r.get("tasks", [])

        if len(records) > 1:
            lines.append(f"*Meeting {i}*")
        lines.append(f"🔗 {link}")
        lines.append(f"🕐 Joined:   {joined}  🔴 Ended: {ended}")
        lines.append(f"⏱️ Duration: {dur}")
        lines.append(f"📝 Summary: {summary}")

        if tasks:
            lines.append("\n*Tasks:*")
            for t in tasks:
                if isinstance(t, dict):
                    icon = "🚨" if t.get("urgent") else "✅"
                    task_line = f"  {icon} {t.get('task','')}"
                    if t.get("has_deadline"):
                        task_line += f" ⏰ {t.get('deadline','')}"
                    lines.append(task_line)
                else:
                    lines.append(f"  ✅ {t}")
        lines.append("")

    return "\n".join(lines).strip()


def _send_chunked_reply(msg, resp, text: str):
    """
    Send a potentially long reply. First chunk goes in the webhook response,
    additional chunks are sent proactively via Twilio REST API.
    """
    MAX = 1500
    chunks = [text[i:i+MAX] for i in range(0, len(text), MAX)]

    if not chunks:
        msg.body("📭 No content found.")
        return

    # First chunk → webhook inline response
    msg.body(chunks[0])

    # Additional chunks → proactive outbound messages
    for chunk in chunks[1:]:
        _send_wa(chunk)


# ── DB / Config helpers ───────────────────────────────────
def _load_db() -> dict:
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG):
            with open(CONFIG, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_config(cfg: dict):
    try:
        with open(CONFIG, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[BotServer] Failed to save config: {e}")


if __name__ == "__main__":
    print("=" * 54)
    print("  MeetFlow WhatsApp Bot Server — port 5000")
    print("  Local:  http://localhost:5000")
    print("  Expose: ngrok http 5000")
    print("  Set Twilio webhook → https://<ngrok-url>/whatsapp")
    print("=" * 54)
    print()
    print("  WhatsApp Commands:")
    print("    help          → command menu")
    print("    today         → today's report")
    print("    yesterday     → yesterday's report")
    print("    list          → all available dates")
    print("    2026-03-28    → report for that date")
    print("    stats         → all-time totals")
    print("    setlink <URL> → override meeting link")
    print("=" * 54)
    app.run(port=5000, debug=False)
