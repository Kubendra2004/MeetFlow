"""
update_twilio_webhook.py
========================
Automatically fetches the current ngrok public URL and updates
the Twilio WhatsApp Sandbox webhook — so you never have to do it manually!

Run after ngrok starts (already called by startup_meetflow.bat).
"""

import os
import time
import json
import urllib.request
import urllib.parse
import urllib.error
from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip().strip('"')
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "").strip().strip('"')
NGROK_API          = "http://localhost:4040/api/tunnels"   # ngrok local API
WEBHOOK_PATH       = "/whatsapp"

def get_ngrok_url(retries: int = 10, delay: float = 3.0) -> str | None:
    """Poll ngrok local API until a public https tunnel URL appears."""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(NGROK_API, timeout=3) as resp:
                data   = json.loads(resp.read())
                for tunnel in data.get("tunnels", []):
                    url = tunnel.get("public_url", "")
                    if url.startswith("https://"):
                        print(f"[Webhook] ✅ ngrok URL found: {url}")
                        return url
        except Exception as e:
            print(f"[Webhook] Attempt {attempt}/{retries} — ngrok not ready yet: {e}")
        time.sleep(delay)
    return None


def update_twilio_webhook(public_url: str) -> bool:
    """
    Update the Twilio WhatsApp Sandbox incoming webhook URL via REST API.
    Uses the /2010-04-01/Accounts/{SID}/IncomingPhoneNumbers/Sandbox.json endpoint
    (sandbox-only route for WhatsApp).
    """
    webhook_url = public_url.rstrip("/") + WEBHOOK_PATH
    print(f"[Webhook] Setting Twilio webhook to: {webhook_url}")

    # Twilio Sandbox uses a special endpoint
    api_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"
        f"/IncomingPhoneNumbers/Sandbox.json"
    )

    data = urllib.parse.urlencode({
        "SmsSandboxWebhookUrl": webhook_url,
        "SmsSandboxWebhookMethod": "POST",
    }).encode("utf-8")

    # Basic Auth with SID:Token
    import base64
    credentials = base64.b64encode(
        f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
    ).decode()

    req = urllib.request.Request(
        api_url,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            print(f"[Webhook] ✅ Twilio webhook updated successfully!")
            print(f"[Webhook] Webhook URL: {webhook_url}")
            # Save to a local file so other scripts can read the current URL
            with open("current_ngrok_url.txt", "w") as f:
                f.write(webhook_url)
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[Webhook] ❌ Twilio API error {e.code}: {body}")
        # The sandbox endpoint may vary — fallback: just save the URL
        print("[Webhook] Saving URL to current_ngrok_url.txt for manual update.")
        with open("current_ngrok_url.txt", "w") as f:
            f.write(webhook_url)
        print(f"\n{'='*54}")
        print(f"  ⚠️  MANUAL STEP REQUIRED (one-time):")
        print(f"  Go to Twilio Sandbox settings and paste this URL:")
        print(f"  {webhook_url}")
        print(f"{'='*54}\n")
        return False
    except Exception as e:
        print(f"[Webhook] ❌ Failed to update webhook: {e}")
        return False


if __name__ == "__main__":
    print("[Webhook] Fetching ngrok public URL...")
    url = get_ngrok_url(retries=10, delay=3)

    if not url:
        print("[Webhook] ❌ Could not get ngrok URL. Is ngrok running?")
        exit(1)

    update_twilio_webhook(url)
