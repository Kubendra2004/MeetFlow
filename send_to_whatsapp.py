"""
send_to_whatsapp.py
Sends today's latest meeting report to your own WhatsApp
using pywhatkit (WhatsApp Web) — no Twilio needed!
"""

import os
import glob
import datetime
import time

# ── Settings ─────────────────────────────────────────────────────────────────
# Your WhatsApp number with country code (e.g. India +91)
MY_PHONE = "+917022949724"

REPORTS_DIR = "reports"
# ─────────────────────────────────────────────────────────────────────────────



def get_todays_report() -> str:
    """Find and return the latest report file from today."""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    pattern = os.path.join(REPORTS_DIR, f"{today}_*.txt")
    files = sorted(glob.glob(pattern))

    if not files:
        return None, None

    latest_file = files[-1]

    with open(latest_file, encoding="utf-8") as f:
        content = f.read()

    return latest_file, content


def extract_summary_section(content: str) -> str:
    """Extract everything before the CAPTIONS section for a clean message."""
    lines = content.split("\n")
    short_lines = []
    for line in lines:
        if "CAPTIONS" in line:
            break
        short_lines.append(line)

    return "\n".join(short_lines).strip()


def send_report():
    """Main function to read and send today's report via WhatsApp Web."""
    try:
        import pywhatkit
    except ImportError:
        print("📦 pywhatkit not installed. Installing now...")
        os.system("pip install pywhatkit")
        import pywhatkit

    # ── Find today's report ───────────────────────────────────────────────
    filepath, content = get_todays_report()

    if not content:
        print("❌ No report found for today!")
        print(f"   Looked in: {REPORTS_DIR}/ for today's date")
        return

    print(f"✅ Found report: {filepath}")

    # ── Format the message ────────────────────────────────────────────────
    clean_report = extract_summary_section(content)

    # Add a nice header
    now = datetime.datetime.now()
    header = f"📋 *MeetFlow — Today's Meeting Report*\n{'─'*34}\n"
    message = header + clean_report

    # ── Split into chunks (WhatsApp limit ~65535 chars, pywhatkit ~1000) ──
    MAX_CHUNK = 900
    chunks = [message[i:i+MAX_CHUNK] for i in range(0, len(message), MAX_CHUNK)]

    print(f"\n📤 Sending {len(chunks)} message(s) to {MY_PHONE} via WhatsApp Web...")
    print("⚠️  WhatsApp Web will open in your browser. Keep it open until done!\n")

    for i, chunk in enumerate(chunks):
        print(f"   Sending part {i+1}/{len(chunks)}...")
        # instantly=True sends immediately without waiting for a scheduled time
        pywhatkit.sendwhatmsg_instantly(
            phone_no=MY_PHONE,
            message=chunk,
            wait_time=10,     # seconds to wait for WhatsApp Web to load
            tab_close=False,  # keep tab open so next chunk can send
            close_time=3
        )
        print(f"   ✅ Part {i+1} sent!")
        if i < len(chunks) - 1:
            time.sleep(5)     # small pause between chunks

    print(f"\n🎉 Done! Report sent to your WhatsApp ({MY_PHONE})")
    print("   Check your WhatsApp — you should see the message from yourself.")


if __name__ == "__main__":
    send_report()
