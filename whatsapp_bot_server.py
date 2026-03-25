"""
whatsapp_bot_server.py
Flask server that receives incoming WhatsApp messages via Twilio webhook.
Run with:  python whatsapp_bot_server.py
Then expose publicly with ngrok:  ngrok http 5000
Set Twilio Sandbox webhook to: https://<ngrok-url>/whatsapp
"""
import os
import json
import datetime
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

try:
    from twilio.twiml.messaging_response import MessagingResponse
    _TWILIO_OK = True
except ImportError:
    _TWILIO_OK = False

app     = Flask(__name__)
DB_FILE = "meetings_db.json"
CONFIG  = "config.json"
IST     = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


# ── Health check ──────────────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return (
        "<h1 style='font-family:sans-serif;color:green'>"
        "🟢 WhatsApp Bot Server is Running!</h1>"
        "<p style='font-family:sans-serif'>"
        "Twilio webhook endpoint: <code>/whatsapp</code><br>"
        "Commands: <code>help</code> | <code>today</code> | <code>stats</code> | "
        "<code>2026-02-28</code> | <code>setlink https://meet.google.com/xxx</code>"
        "</p>"
    )


# ── WhatsApp webhook ──────────────────────────────────────
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    if not _TWILIO_OK:
        return "Twilio not installed", 500

    incoming       = request.values.get("Body", "").strip()
    incoming_lower = incoming.lower()

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
                f"🤖 *Google Meet Bot*\n"
                f"✅ *Dynamic link set for next join!*\n\n"
                f"🔗 {new_link}\n\n"
                f"_The bot will use this link instead of the default one._"
            )
        else:
            msg.body(
                "❌ Invalid Meet link.\n"
                "Format: `setlink https://meet.google.com/xxx-xxxx-xxx`"
            )
        return str(resp)

    # ── help / greeting ───────────────────────────────────
    if incoming_lower in ("hi", "hello", "help", "start", ""):
        recent = ", ".join(sorted(db.keys(), reverse=True)[:5]) if db else "None yet"
        msg.body(
            "🤖 *Google Meet Bot*\n\n"
            "I auto-join Google Meet, record, and send AI summaries!\n\n"
            "*Commands:*\n"
            "📅 `2026-02-28` → records for that date\n"
            "📋 `today` → today's meeting\n"
            "📊 `stats` → all-time totals\n"
            "🔗 `setlink https://meet.google.com/xxx` → override today's link\n\n"
            f"_Recent dates:_ {recent}"
        )
        return str(resp)

    # ── today ─────────────────────────────────────────────
    if incoming_lower == "today":
        today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
        if today in db:
            _reply_for_date(msg, db, today)
        else:
            msg.body(f"📭 No meeting records for today ({today}) yet.")
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
        msg.body(
            f"🤖 *Google Meet Bot — Stats*\n\n"
            f"📅 Days with meetings: {total_days}\n"
            f"🔢 Total meetings:     {total_meetings}\n"
            f"⏱️ Total time:         {h}h {m}m"
        )
        return str(resp)

    # ── date lookup (YYYY-MM-DD) ──────────────────────────
    if len(incoming) == 10 and incoming[4] == "-" and incoming[7] == "-":
        if incoming in db:
            _reply_for_date(msg, db, incoming)
        else:
            recent = ", ".join(sorted(db.keys(), reverse=True)[:5]) if db else "None"
            msg.body(
                f"📭 No records for `{incoming}`.\n\n"
                f"_Available dates:_ {recent}"
            )
        return str(resp)

    # ── unknown ───────────────────────────────────────────
    msg.body(
        f"🤖 I didn't understand `{incoming}`.\n"
        "Send *help* to see available commands."
    )
    return str(resp)


# ── Helpers ───────────────────────────────────────────────
def _reply_for_date(msg, db: dict, date_str: str):
    records = db[date_str]
    if not isinstance(records, list):
        records = [records]

    reply = f"📅 *Records for {date_str}*\n\n"
    for i, r in enumerate(records, 1):
        joined   = (r.get("joined_at") or "?")[:16].replace("T", " ")
        ended    = r.get("ended_at")
        ended    = ended[:16].replace("T", " ") if ended else "In progress"
        dur_mins = r.get("duration_minutes")
        dur      = f"{dur_mins//60}h {dur_mins%60}m" if dur_mins else "N/A"
        link     = r.get("meet_link", "N/A")
        summary  = r.get("summary", "N/A")
        tasks    = r.get("tasks", [])

        reply += f"*Meeting {i}*\n"
        reply += f"🔗 {link}\n"
        reply += f"🕐 Joined:  {joined}\n"
        reply += f"🔴 Ended:   {ended}\n"
        reply += f"⏱️ Duration: {dur}\n"
        reply += f"📝 Summary: {summary}\n"

        if tasks:
            reply += "\n*Tasks:*\n"
            for t in tasks:
                if isinstance(t, dict):
                    label = "🚨" if t.get("urgent") else "✅"
                    reply += f"  {label} {t.get('task','')}"
                    if t.get("has_deadline"):
                        reply += f" ⏰ {t.get('deadline','')}"
                    reply += "\n"
                else:
                    reply += f"  ✅ {t}\n"
        reply += "\n"

    msg.body(reply.strip())


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
    print("=" * 50)
    print("  WhatsApp Bot Server — port 5000")
    print("  Open: http://localhost:5000")
    print("  Set Twilio webhook → http://<ngrok-url>/whatsapp")
    print("=" * 50)
    app.run(port=5000, debug=False)
