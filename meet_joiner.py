"""
meet_joiner.py  —  Google Meet Auto-Joiner v2
=============================================
Joins a Google Meet at a scheduled time, mutes mic/camera,
records audio, sends AI summary to WhatsApp, and shuts down
the PC when the host ends the meeting.

Edit config.json to change the meeting link or join time.
"""
import time
import traceback
import os
import sys
import json
import ntplib
import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import whatsapp_notifier as wa
import ai_processor

# ── Constants ────────────────────────────────────────────
CONFIG_FILE = "config.json"
PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile")
IST_OFFSET  = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
CHROME_VER  = 146   # ← MATCHED TO YOUR BROWSER VERSION
CHROMIUM_BIN = None # Optional: Set path to chromium binary for Linux systems

# Smart Filtering Constants
IGNORE_PHRASES = {"thank you", "okay", "yes", "no", "hmm", "right", "yeah", "ok"}
IMPORTANT_WORDS = [
    "deadline", "submit", "assignment", "exam", "project", 
    "important", "note", "remember", "must", "should", 
    "today", "tomorrow", "due"
]
ACTION_WORDS = ["submit", "complete", "prepare", "bring", "revise", "study"]

# Testing mode: set True to join immediately without waiting.
# Or run:  python meet_joiner.py --now
TEST_MODE     = False
JOIN_WINDOW_M = 30 # join if within this many minutes past the scheduled time
# ─────────────────────────────────────────────────────────



# ── Config helpers ────────────────────────────────────────
def load_config() -> dict:
    """Load config.json safely, returning {} on any error."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[Config] Failed to read config.json: {e}")
    return {}


def save_config(cfg: dict):
    """Save config.json safely."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[Config] Failed to write config.json: {e}")


def get_active_link() -> str:
    """
    Returns the dynamic override link if set (and clears it),
    otherwise returns the default meeting link.
    """
    cfg = load_config()
    override = cfg.get("dynamic_link_override")
    if override:
        print(f"[Config] 🔗 Dynamic link override active: {override}")
        cfg["dynamic_link_override"] = None   # one-time use — clear after reading
        save_config(cfg)
        return override
    link = cfg.get("meet_link", "")
    if not link:
        raise ValueError("No meet_link found in config.json and no dynamic override set.")
    return link


def get_join_time() -> tuple:
    """Returns (hour, minute) from config.json."""
    cfg = load_config()
    t = cfg.get("join_time_ist", "13:00")
    try:
        h, m = map(int, t.split(":"))
        return h, m
    except Exception:
        print("[Config] Invalid join_time_ist — defaulting to 13:00.")
        return 13, 0


# ── Time helpers ──────────────────────────────────────────
def get_ntp_time_ist() -> datetime.datetime:
    """Fetch accurate IST time from NTP internet servers, fall back to system."""
    for server in ["pool.ntp.org", "time.google.com", "time.cloudflare.com"]:
        try:
            c = ntplib.NTPClient()
            r = c.request(server, version=3, timeout=1)
            utc = datetime.datetime.fromtimestamp(r.tx_time, tz=datetime.timezone.utc)
            return utc.astimezone(IST_OFFSET)
        except Exception:
            continue
    print("[WARNING] NTP unreachable — falling back to system clock.")
    return datetime.datetime.now(IST_OFFSET)


# ── Chrome helpers ────────────────────────────────────────
def build_chrome_options() -> uc.ChromeOptions:
    """Build Chrome options with all resource-efficiency flags."""
    options = uc.ChromeOptions()

    # Ensure profile directory exists
    os.makedirs(PROFILE_DIR, exist_ok=True)
    print(f"[Chrome] Using profile: {PROFILE_DIR}")

    # Allow mic/camera without popup prompts
    options.add_argument("--use-fake-ui-for-media-stream")
    # Use the persistent profile (keeps you signed in)
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")

    # Linux keyring integration can fail under automation and make sessions appear signed out.
    if sys.platform.startswith("linux"):
        options.add_argument("--password-store=basic")

    # ── Session persistence ──
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    # ── Resource efficiency ──
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_argument("--js-flags=--max-old-space-size=512")
    # NOTE: --disable-background-networking and --disable-sync removed
    # They break Google session auth and WebRTC (Meet won't load correctly)
    # NOTE: --disable-default-apps removed - it can clear session cookies

    # Grant mic and camera permissions at browser level
    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.media_stream_mic": 1,
        "profile.default_content_setting_values.media_stream_camera": 1,
        "profile.default_content_setting_values.notifications": 2,  # Block notifications
    })
    
    # Open Chrome visibly so the user can see the meeting.
    # We do NOT use --headless=new because it breaks Google Meet WebRTC/media permissions.
    options.add_argument("--start-maximized")
    options.add_argument("--window-position=0,0")
    
    return options


def verify_device_muted(driver, keyword: str) -> bool:
    """Returns True if the device is confirmed to be OFF (Muted)."""
    try:
        # If 'Turn on' is in the internal label, it means the device is currently OFF.
        # This works across most Google Meet versions and languages because 'Turn on' 
        # is the primary suggestion when muted.
        off_markers = [
            f"Turn on {keyword}", f"Unmute {keyword}", f"Start {keyword}",
            f"turn on {keyword}", f"unmute {keyword}", f"start {keyword}"
        ]
        
        # Check all buttons for those markers
        all_btns = driver.find_elements(By.XPATH, f"//*[contains(@aria-label, '{keyword}') or contains(@aria-label, '{keyword.capitalize()}')]")
        for btn in all_btns:
            label = (btn.get_attribute("aria-label") or "").lower()
            if any(m.lower() in label for m in off_markers):
                return True
        return False
    except Exception:
        return False

def force_mute(driver, keyword: str, attempts: int = 3) -> bool:
    """
    Stronger mute enforcement loop.
    Tries to mute and verifies multiple times before continuing.
    """
    for i in range(attempts):
        if verify_device_muted(driver, keyword):
            print(f"[Join] Verification: {keyword.capitalize()} is OFF ✅")
            return True
        
        print(f"[Fix] Forcing {keyword} OFF (attempt {i+1}/{attempts})...")
        mute_device(driver, keyword)
        time.sleep(0.7)
    
    final_state = verify_device_muted(driver, keyword)
    if not final_state:
        print(f"[Fix] ⚠️ Could not verify {keyword} as OFF after {attempts} attempts.")
    return final_state

def mute_device(driver, keyword: str):
    """
    Find the mic or camera toggle button on the preview screen
    and click it if it is currently ON. Safe — never crashes.
    """
    try:
        btns = driver.find_elements(
            By.XPATH,
            f"//*[contains(@aria-label, '{keyword}') "
            f"or contains(@aria-label, '{keyword.capitalize()}')]"
        )
        for btn in btns:
            label = (btn.get_attribute("aria-label") or "").lower()
            if "turn off" in label and keyword in label:
                btn.click()
                print(f"[Join] {keyword.capitalize()} muted ✅")
                return
            if "turn on" in label and keyword in label:
                print(f"[Join] {keyword.capitalize()} already OFF ✅")
                return
    except Exception as e:
        print(f"[Join] Could not control {keyword}: {e}")


def _are_captions_on(driver) -> bool:
    """
    Returns True if captions are currently ENABLED.
    Detection method: look for the 'Turn off captions' button in the toolbar.
    That button only appears when captions are ON — it replaces 'Turn on captions'.
    We do NOT check for caption text, because speech may not be happening yet.
    """
    try:
        result = driver.execute_script("""
            var labels = [
                'turn off captions', 'turn off closed captions',
                'captions on', 'disable captions'
            ];
            var all = document.querySelectorAll('[aria-label]');
            for (var i = 0; i < all.length; i++) {
                var lbl = (all[i].getAttribute('aria-label') || '').toLowerCase();
                for (var j = 0; j < labels.length; j++) {
                    if (lbl.indexOf(labels[j]) !== -1) return true;
                }
            }
            return false;
        """)
        return bool(result)
    except Exception:
        return False


def enable_captions(driver) -> bool:
    """
    Turn on Google Meet live captions.
    Checks if already ON first to avoid toggling them OFF.
    Tries aria-label button click, then 'c' hotkey, then More Options menu.
    Returns True if captions are confirmed active.
    """
    # Already on — don't toggle
    if _are_captions_on(driver):
        print("[Bot] Captions already active ✅")
        return True

    # Strategy 1: Click the CC / Turn-on-captions button directly
    cc_xpaths = [
        "//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'turn on captions')]",
        "//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'turn on closed captions')]",
        "//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'closed captions')]",
        "//*[@aria-label='Captions' or @aria-label='CC']",
    ]
    for xp in cc_xpaths:
        try:
            for btn in driver.find_elements(By.XPATH, xp):
                if btn.is_displayed():
                    try:
                        driver.execute_script("arguments[0].click();", btn)
                    except Exception:
                        btn.click()
                    time.sleep(0.8)
                    if _are_captions_on(driver):
                        print("[Bot] Captions enabled via button click ✅")
                        return True
        except Exception:
            pass

    # Strategy 2: 'c' hotkey (only works when inside the meeting, not on preview)
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys("c")
        time.sleep(1.0)
        if _are_captions_on(driver):
            print("[Bot] Captions enabled via 'c' hotkey ✅")
            return True
    except Exception:
        pass

    # Strategy 3: Open More Options (⋮) and click Turn on captions from the menu
    try:
        more_btns = driver.find_elements(
            By.XPATH,
            "//button[contains(@aria-label,'More options') or contains(@aria-label,'more options')"
            " or contains(@aria-label,'Options') or @data-tooltip='More options']"
        )
        for btn in more_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.8)
                # Now look for the caption item in the dropdown
                for item in driver.find_elements(
                    By.XPATH,
                    "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'turn on captions')"
                    " or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'captions')]"
                ):
                    if item.is_displayed():
                        driver.execute_script("arguments[0].click();", item)
                        time.sleep(0.8)
                        if _are_captions_on(driver):
                            print("[Bot] Captions enabled via More Options menu ✅")
                            return True
                break
    except Exception:
        pass

    return False


def scrape_captions(driver) -> str:
    """
    Extract current caption text visible on screen.
    Tries multiple selectors that Google Meet uses across versions.
    Filters out Google Meet UI strings and adds Speaker Detection.
    """
    UI_NOISE = {
        "language", "english", "closed_caption", "live captions",
        "format_size", "font size", "circle", "font colour", "font color",
        "settings", "open caption settings", "caption settings",
        "format_color_text", "text", "background", "font style",
        "check", "check_box", "more_vert", "close", "done",
        "auto", "accessibility", "captions", "cc",
    }

    try:
        raw = driver.execute_script("""
            var selectors = [
                '[jsname="tgaKEf"]',
                '.a4cQT',
                '[class*="caption"] span',
                '[class*="Caption"] span',
                '.iTTPOb',
                '[data-is-live-caption]',
            ];
            for (var s of selectors) {
                var els = document.querySelectorAll(s);
                if (els.length > 0) {
                    var parts = [];
                    els.forEach(function(e) {
                        var t = (e.innerText || '').trim();
                        if (t) parts.push(t);
                    });
                    if (parts.length) return parts.join(' ');
                }
            }
            return '';
        """) or ""

        if not raw:
            return ""

        clean_lines = []
        for line in raw.splitlines():
            line = line.strip()
            if len(line) < 5:
                continue
            if line.lower() in UI_NOISE:
                continue
            words = set(line.lower().split())
            if words and words.issubset(UI_NOISE):
                continue
            clean_lines.append(line)

        # ── Speaker Detection (Structured Output) ──
        structured = []
        for line in clean_lines:
            line = line.strip()
            if ":" in line:
                # Basic speaker split
                parts = line.split(":", 1)
                name = parts[0].strip()
                text = parts[1].strip() if len(parts) > 1 else ""
                
                if 2 < len(name) < 40: # avoid garbage UI text
                    structured.append(f"[{name}]: {text}")
                else:
                    structured.append(line)
            else:
                structured.append(line)

        return "\n".join(structured)

    except Exception:
        return ""


def get_participant_count(driver) -> int:
    """
    Detect number of participants. 
    Tries aria-labels and text-based markers.
    """
    import re
    try:
        # Method 1: Bottom toolbar aria-label
        # Example: "Show everyone (5)" or "5 participants"
        elems = driver.find_elements(By.XPATH, "//*[contains(@aria-label, 'participant')]")
        for el in elems:
            label = (el.get_attribute("aria-label") or "").lower()
            match = re.search(r"(\d+)", label)
            if match:
                return int(match.group(1))

        # Method 2: Text markers (e.g. at bottom or in panel)
        elems = driver.find_elements(By.XPATH, "//*[contains(text(), 'participant')]")
        for el in elems:
            txt = (el.text or "").lower()
            match = re.search(r"(\d+)", txt)
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return -1


def _open_chat_panel(driver) -> bool:
    """
    Open Google Meet chat panel if it is closed.
    Safe to call repeatedly; returns True if chat appears open/accessible.
    """
    try:
        chat_toggle_xpaths = [
            "//button[contains(@aria-label,'Chat')]",
            "//div[@role='button' and contains(@aria-label,'Chat')]",
            "//button[contains(@data-tooltip,'Chat')]",
        ]
        for xp in chat_toggle_xpaths:
            btns = driver.find_elements(By.XPATH, xp)
            for btn in btns:
                if btn.is_displayed():
                    try:
                        label = (btn.get_attribute("aria-label") or "").lower()
                        # If label suggests panel is closed, click to open.
                        if "open chat" in label or "chat with everyone" in label or "chat" in label:
                            btn.click()
                            time.sleep(0.3)
                            return True
                    except Exception:
                        pass
        return False
    except Exception:
        return False


def scrape_chat_messages(driver) -> list[str]:
    """
    Scrape visible Google Meet chat lines (including pasted links when present).
    Returns a best-effort list of message strings.
    """
    try:
        data = driver.execute_script("""
            const selectors = [
                '[role="log"] [role="listitem"]',
                '[aria-live="polite"] [role="listitem"]',
                '[class*="chat"] [role="listitem"]',
                '[data-message-text]',
                '[data-is-chat-message]'
            ];

            const out = [];
            const seen = new Set();

            for (const s of selectors) {
                const nodes = document.querySelectorAll(s);
                for (const n of nodes) {
                    const txt = (n.innerText || '').trim();
                    if (!txt || txt.length < 2) continue;

                    // Pull links explicitly if present in the node.
                    const anchors = Array.from(n.querySelectorAll('a[href]'));
                    const hrefs = anchors.map(a => (a.href || '').trim()).filter(Boolean);
                    const merged = hrefs.length ? `${txt} | links: ${hrefs.join(' , ')}` : txt;

                    if (!seen.has(merged)) {
                        seen.add(merged);
                        out.push(merged);
                    }
                }
            }

            return out;
        """) or []

        clean = []
        for line in data:
            line = (line or "").strip()
            if not line:
                continue
            clean.append(line)
        return clean
    except Exception:
        return []


def click_join_button(driver) -> bool:
    """
    Try all known XPaths for Ask-to-join / Join-now buttons.
    Returns True if found and clicked, False otherwise.
    Waits up to 15 seconds total.
    """
    xpaths = [
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'ask to join')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'join now')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'ready to join')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'rejoin')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'join call')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'try again')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'rejoin')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'rejoin')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'try again')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
    ]
    for xpath in xpaths:
        try:
            btns = driver.find_elements(By.XPATH, xpath)
            for btn in btns:
                try:
                    if not btn.is_displayed():
                        continue
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.1)
                    try:
                        btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _is_in_meeting_ui(driver) -> bool:
    """
    Detect if user is truly inside the meeting room (not on preview screen).
    """
    try:
        # Check for the presence of a "Join" button. If it exists, we are NOT in the meeting yet.
        join_markers = [
            "//span[contains(text(), 'Join now')]",
            "//span[contains(text(), 'Ask to join')]",
            "//button[contains(., 'Join now')]",
            "//button[contains(., 'Ask to join')]",
        ]
        for marker in join_markers:
            if driver.find_elements(By.XPATH, marker):
                return False

        # Check for elements unique to the meeting room
        meeting_markers = [
            "//button[contains(@aria-label,'Leave call')]",
            "//button[contains(@aria-label,'Hang up')]",
            "//button[contains(@aria-label,'Chat with everyone')]",
            "//button[contains(@aria-label,'Meeting details')]",
            "//button[contains(@aria-label,'Raise hand')]",
        ]
        for xp in meeting_markers:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed():
                    return True
        return False
    except Exception:
        return False


def _is_waiting_for_admission(driver) -> bool:
    """
    Detect waiting-room states after clicking "Ask to join".
    """
    try:
        page_text = driver.execute_script("return document.body ? document.body.textContent : '';") or ""
        p = page_text.lower()
    except Exception:
        p = ""

    markers = [
        "asking to join",
        "ask to join sent",
        "request sent",
        "you'll join when",
        "someone in the call needs to let you in",
        "waiting for someone to let you in",
        "you cannot join this call",
    ]
    if any(m in p for m in markers):
        return True

    try:
        waiting_badges = driver.find_elements(
            By.XPATH,
            "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'asking to join')"
            " or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'request sent')"
            " or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'waiting for someone to let you in')]"
        )
        return any(el.is_displayed() for el in waiting_badges)
    except Exception:
        return False


def join_with_popup_retries(driver, timeout_s: int = 120) -> bool:
    """
    Retry join flow while dismissing popups so transient dialogs
    do not block meeting entry.
    """
    end_at = time.time() + max(30, timeout_s)
    last_mute_at = 0.0
    waiting_logged = False

    while time.time() < end_at:
        # Stop retrying if we are already admitted.
        if _is_in_meeting_ui(driver):
            return True

        dismiss_popups(driver)

        # Avoid spamming mute checks every loop.
        now = time.time()
        if now - last_mute_at >= 5:
            mute_device(driver, "microphone")
            mute_device(driver, "camera")
            last_mute_at = now

        if click_join_button(driver):
            time.sleep(1.5)
            if _is_in_meeting_ui(driver):
                return True

        # Ask-to-join flow can hide the join button while waiting for host approval.
        if _is_waiting_for_admission(driver):
            if not waiting_logged:
                print("[Join] Ask-to-join sent. Waiting for host approval...")
                waiting_logged = True
            time.sleep(2.0)
            continue

        time.sleep(1.2)
    return False


def click_rejoin_or_retry(driver) -> bool:
    """
    Click recovery actions aggressively when Meet shows transient error pages.
    Returns True if a likely recovery action was clicked.
    """
    recover_xpaths = [
        "//span[contains(text(), 'Rejoin')]",
        "//span[contains(text(), 'Join now')]",
        "//span[contains(text(), 'Join call')]",
        "//span[contains(text(), 'Try again')]",
        "//button[contains(., 'Rejoin')]",
        "//button[contains(., 'Join now')]",
        "//button[contains(., 'Join call')]",
        "//button[contains(., 'Try again')]",
    ]
    for xp in recover_xpaths:
        try:
            btns = driver.find_elements(By.XPATH, xp)
            for btn in btns:
                if btn.is_displayed():
                    btn.click()
                    print(f"[Join] Recovery action clicked: {xp}")
                    return True
        except Exception:
            pass
    return False


def _click_leave(driver):
    """
    Try to click the Leave / Hang-up button in Google Meet.
    Tries multiple selectors since Google changes these frequently.
    """
    leave_selectors = [
        # aria-label based (most stable)
        "[aria-label='Leave call']",
        "[aria-label='Hang up']",
        "[aria-label='Leave meeting']",
        # data-tooltip based
        "[data-tooltip='Leave call']",
        "[data-tooltip='Hang up']",
    ]
    leave_xpaths = [
        "//button[contains(@aria-label,'Leave')]",
        "//button[contains(@aria-label,'Hang up')]",
        "//div[@role='button' and contains(@aria-label,'Leave')]",
    ]
    for sel in leave_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed():
                btn.click()
                print("[Bot] Clicked Leave button.")
                time.sleep(2)
                return True
        except Exception:
            pass
    for xp in leave_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn.is_displayed():
                btn.click()
                print("[Bot] Clicked Leave button (xpath).")
                time.sleep(2)
                return True
        except Exception:
            pass
    print("[Bot] Could not find Leave button — Chrome will be force-closed.")
    return False


def is_important_line(text: str) -> bool:
    """Check if line contains high-priority keywords or action words."""
    import re
    words = re.findall(r"\b\w+\b", text.lower())
    # Use startswith to catch variations like "submitted", "deadlines", etc.
    important = any(w.startswith(tuple(IMPORTANT_WORDS)) for w in words)
    actionable = any(w.startswith(tuple(ACTION_WORDS)) for w in words)
    return important or actionable


def score_line(text: str) -> int:
    """
    Assign importance score based on keywords, action words, and structure.
    """
    score = 0
    t = text.lower()

    # 🔥 High importance keywords
    for word in IMPORTANT_WORDS:
        if word in t:
            score += 3

    # ⚡ Action words (tasks)
    for word in ACTION_WORDS:
        if word in t:
            score += 5

    # 📅 Time-related (deadlines)
    if any(x in t for x in ["today", "tomorrow", "deadline", "due"]):
        score += 4

    # 👤 Speaker present → more metadata is better
    if text.startswith("[") and "]:" in text:
        score += 2

    # 📏 Longer meaningful sentences
    if len(text.split()) > 8:
        score += 1

    return score


# ── Core join function ────────────────────────────────────
def join_meet(meet_link: str) -> str:
    """
    Opens Chrome, mutes mic/camera, joins the meeting, scrapes live
    captions, runs LLaMA analysis, sends WhatsApp report.
    No audio file is created — captions are read directly from the DOM.

    Returns one of: 'host_ended' | 'kicked' | 'left' | 'error'
    """
    now             = get_ntp_time_ist()
    join_start_time = now
    driver          = None
    result          = "error"
    caption_lines: list[str] = []      # accumulated full transcript
    chunk_buffer: list[tuple[str, int]] = []  # (scored lines) for AI context
    chat_lines: list[str] = []         # accumulated chat lines
    seen_chat_lines: set[str] = set()
    last_caption    = ""              # dedup: skip repeated lines

    print(f"\n{'='*54}")
    print(f"  [{now.strftime('%Y-%m-%d %H:%M:%S')} IST] Joining: {meet_link}")
    print(f"{'='*54}")

    try:
        options = build_chrome_options()
        
        # Use Chromium binary on Linux if detected
        try:
            if sys.platform.startswith("linux") and CHROMIUM_BIN:
                print(f"[Join] Using Chromium binary: {CHROMIUM_BIN}")
                driver = uc.Chrome(options=options, version_main=CHROME_VER, browser_executable_path=CHROMIUM_BIN)
            else:
                driver = uc.Chrome(options=options, version_main=CHROME_VER)
        except Exception as e:
            print(f"[Join] Failed to initialize Chrome: {e}")
            wa.notify_failed(meet_link, f"Chrome Error: {e}")
            return "error"
        
        # ── Bring Chrome window to the front ──────────────
        driver.maximize_window()
        driver.switch_to.window(driver.current_window_handle)
        # Windows blocks focus-stealing from background processes by default.
        # Use ctypes to force the Chrome window to the foreground.
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = driver.execute_script(
                    "return window.screenX;"  # just a ping to get focus context
                )
                # Use win32gui via ctypes to bring the window forward
                ctypes.windll.user32.SetForegroundWindow(
                    ctypes.windll.kernel32.GetConsoleWindow()
                )
                time.sleep(0.3)
                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)          # ALT down
                ctypes.windll.user32.keybd_event(0x12, 0, 0x0002, 0)     # ALT up
            except Exception:
                pass
        
        driver.get(meet_link)
        print("[Join] Page loaded. Waiting for preview screen...")
        time.sleep(3)
        
        # Dismiss any popups that appear on page load
        dismiss_popups(driver)
        time.sleep(1)

        # ── Mute mic & camera + robust popup-aware join ────
        joined = join_with_popup_retries(driver, timeout_s=180)
        if not joined:
            current_url = ""
            try:
                current_url = driver.current_url
            except Exception:
                pass

            if "accounts.google.com" in current_url or "servicelogin" in current_url.lower():
                err = "Google account not signed in for this Chrome profile."
            elif _is_waiting_for_admission(driver):
                err = "Join request sent, but host did not admit in time."
            else:
                err = "Join button not found on preview screen."

            print(f"[Join] Could not complete join flow: {err}")
            wa.notify_failed(meet_link, err)
            return "error"

        join_start_time = get_ntp_time_ist()
        print("[Join] Joined the meeting!")
        wa.notify_joined(meet_link, join_start_time)
        
        # Dismiss any popups that appear after joining
        time.sleep(1)
        dismiss_popups(driver)
        time.sleep(1)

        # ── Enable live captions (with retry loop) ─────────
        # We are confirmed inside the meeting at this point.
        # Wait up to 30 s for the toolbar to fully render then enable captions.
        # Key: we check for the 'Turn off captions' button (not caption text)
        # because no speech may be happening right after joining.
        print("[Bot] Enabling captions...")
        time.sleep(3)   # let the meeting toolbar animate in fully
        captions_enabled = False
        caption_deadline = time.time() + 30   # try for up to 30 seconds
        attempt = 0
        while time.time() < caption_deadline:
            attempt += 1
            print(f"[Bot] Caption attempt #{attempt}...")
            if enable_captions(driver):
                captions_enabled = True
                break
            time.sleep(3)
        if not captions_enabled:
            print("[Bot] ⚠️  Could not enable captions after 30s — transcript may be empty.")
        time.sleep(1)

        # ── Monitor meeting + scrape captions ──────────────
        # Extract just the meeting code from the link for URL change detection
        meet_code = meet_link.rstrip("/").split("/")[-1]   # e.g. "zdg-jzev-sjb"

        HOST_END = ["call ended", "the call has ended", "has ended the call",
                    "meeting ended", "the meeting has ended", "this call has ended",
                    "returned to the home screen"]
        KICKED   = ["you've been removed", "you were removed", "you have been removed"]
        LEFT     = ["you left the call", "you left the meeting"]

        # Caption-based farewell — exit when host says goodbye
        FAREWELL = [
            "thank you for attending", "thanks for attending",
            "that's all for today", "thats all for today",
            "see you next time", "see you all", "bye everyone",
            "goodbye everyone", "bye for now", "good bye everyone",
            "meeting is concluded", "this concludes", "that wraps up",
            "we'll wrap up", "lets wrap up", "that's a wrap",
            "have a good day", "have a great day", "take care everyone",
            "end of meeting", "session is over", "thank you all for joining",
            "thanks for joining", "meeting adjourned", "see you tomorrow",
        ]

        cfg_max      = load_config().get("max_duration_minutes", 120)
        max_end_time = join_start_time + datetime.timedelta(minutes=cfg_max)

        print(f"[Bot] Monitoring meeting (max {cfg_max} min)...")
        consecutive_errors = 0
        farewell_detected   = False
        transient_retries   = 0
        MAX_TRANSIENT_RETRIES = 5
        last_caption_scrape = time.time()
        CAPTION_INTERVAL    = 5             # 5s interval (better CPU usage)
        last_chat_scrape    = 0.0
        CHAT_INTERVAL       = 6             # seconds
        last_chat_open_try  = 0.0
        CHAT_OPEN_INTERVAL  = 25            # seconds
        PARTICIPANT_CHECK_INTERVAL = 30     # check every 30s
        last_participant_check = 0.0

        while True:
            time.sleep(4)

            # ── Safety net: max duration ────────────────────
            if get_ntp_time_ist() >= max_end_time:
                result = "host_ended"
                print(f"[Bot] Max duration ({cfg_max} min) reached — leaving.")
                _click_leave(driver)
                break

            try:
                url = driver.current_url

                # ── URL left the meeting room ───────────────
                # Try recovery first; Meet often redirects briefly to error/rejoin pages.
                if meet_code not in url:
                    if "accounts.google.com" in url or "ServiceLogin" in url:
                        result = "error"
                        print("[Bot] Session appears signed out (redirected to Google login).")
                        wa.notify_failed(meet_link, "Google session signed out. Run setup_login.py once on this OS profile.")
                        break
                    if "meet.google.com" in url:
                        if click_rejoin_or_retry(driver) or click_join_button(driver):
                            print(f"[Bot] Recovery attempted from URL: {url}")
                            time.sleep(2)
                            continue
                    result = "host_ended" if "meet.google.com" in url else "left"
                    print(f"[Bot] Meeting URL changed to {url} — exiting.")
                    break

                # ── Full page text (textContent catches portals) ─
                page_text = driver.execute_script(
                    "return document.body ? document.body.textContent : '';"
                ) or ""
                page_lower = page_text.lower()

                # ── Page title check ────────────────────────
                title = driver.execute_script("return document.title || '';").lower()

                # ── Collect captions (Real-time Streaming) ──
                _now = time.time()
                if _now - last_caption_scrape >= CAPTION_INTERVAL:
                    last_caption_scrape = _now
                    cap = scrape_captions(driver).strip()
                    if cap:
                        # Split into segments (sentences) for better storage
                        parts = cap.split(". ")
                        for p in parts:
                            p = p.strip()
                            if not p: continue
                            
                            p_clean = p.lower()
                            
                            # ❌ Filtering Pipeline
                            # Improved: Catch "okay bro", "yes sir", etc.
                            if any(phrase in p_clean for phrase in IGNORE_PHRASES):
                                continue
                            if len(p_clean) < 4:
                                continue
                            if p == last_caption:
                                continue
                                
                            last_caption = p
                            
                            # ✅ Always store full transcript
                            caption_lines.append(p)
                            
                            # 🔥 SMART FILTERING + SCORING (Hybrid Mode)
                            is_important = is_important_line(p)
                            score = score_line(p)
                            
                            if is_important:
                                chunk_buffer.append((p, score))
                                print(f"[Important] {p[:80]}")
                            elif len(chunk_buffer) % 5 == 0:
                                # keep some context periodically
                                chunk_buffer.append((p, score))
                                print(f"[Caption] {p[:80]}")
                            else:
                                # Still print normal captions to console
                                print(f"[Caption] {p[:80]}")
                                
                            # Farewell detection
                            p_lower = p.lower()
                            if any(phrase in p_lower for phrase in FAREWELL):
                                farewell_detected = True
                                print(f"[Bot] Farewell detected in caption — leaving now.")
                                time.sleep(3)
                                _click_leave(driver)
                                result = "host_ended"
                                break
                        if result == "host_ended": break

                # ── Keep tab on chat and capture pasted links/messages ─
                if _now - last_chat_open_try >= CHAT_OPEN_INTERVAL:
                    last_chat_open_try = _now
                    _open_chat_panel(driver)

                if _now - last_chat_scrape >= CHAT_INTERVAL:
                    last_chat_scrape = _now
                    for msg in scrape_chat_messages(driver):
                        if msg not in seen_chat_lines:
                            seen_chat_lines.add(msg)
                            stamped = f"[CHAT] {msg}"
                            chat_lines.append(stamped)
                            # Prevent memory leak in very long meetings
                            if len(chat_lines) > 2000:
                                chat_lines.pop(0)
                            print(f"[Chat] {msg[:120]}")

                # ── Participant-based end detection ──────────
                if _now - last_participant_check >= PARTICIPANT_CHECK_INTERVAL:
                    last_participant_check = _now
                    count = get_participant_count(driver)
                    if count != -1:
                        print(f"[Participants] Active count: {count}")
                        if count <= 1 and len(caption_lines) > 5:
                            print("[Bot] Only 1 participant left — meeting likely ended.")
                            time.sleep(5)
                            _click_leave(driver)
                            result = "host_ended"
                            break

                # ── Page-level end state detection ──────────
                PROBLEM_HINTS = [
                    "there was a problem", "something went wrong", "try again",
                    "rejoin", "reconnecting", "couldn't connect",
                ]
                if any(p in page_lower for p in PROBLEM_HINTS):
                    if click_rejoin_or_retry(driver) or click_join_button(driver):
                        transient_retries += 1
                        print("[Bot] Detected transient meet issue — attempted rejoin.")
                        if transient_retries <= MAX_TRANSIENT_RETRIES:
                            try:
                                driver.refresh()
                                print(f"[Bot] Refreshing Meet page ({transient_retries}/{MAX_TRANSIENT_RETRIES}).")
                            except Exception:
                                pass
                        time.sleep(2)
                        continue
                else:
                    transient_retries = 0

                if any(p in page_lower for p in HOST_END):
                    result = "host_ended"
                    print("[Bot] Host ended the meeting.")
                    break
                if any(p in page_lower for p in KICKED):
                    result = "kicked"
                    print("[Bot] Removed from meeting.")
                    break
                if any(p in page_lower for p in LEFT):
                    result = "left"
                    print("[Bot] Left the meeting.")
                    break
                # Title-based (Google Meet sets title to "Google Meet" on meeting end)
                if title and ("google meet" == title or "call ended" in title):
                    result = "host_ended"
                    print("[Bot] Title indicates meeting ended.")
                    break

                # ── Dismiss popups ──────────────────────────
                dismiss_popups(driver)

                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                print(f"[Bot] Driver error #{consecutive_errors}: {e}")
                if consecutive_errors >= 3:
                    print("[Bot] Browser unresponsive — treating as meeting ended.")
                    result = "host_ended"
                    break

    except Exception as e:
        print("[Bot] Critical error in join_meet:")
        traceback.print_exc()

    finally:
        if driver:
            try:
                driver.quit()
                print("[Bot] Chrome closed.")
            except Exception:
                pass

    # ── Post-meeting: AI analysis & Text Report ─────────────
    end_time   = get_ntp_time_ist()
    # Full transcript saved separately
    captions_text = "\n".join(caption_lines)

    # ── Importance Ranking Logic with Fallback ──
    MAX_AI_LINES = 800
    # Filter for segments with positive importance score
    important_segments = [txt for txt, score in chunk_buffer if score > 0]
    
    if important_segments:
        # We have meaningful content! Rank by score.
        sorted_by_score = sorted(chunk_buffer, key=lambda x: x[1], reverse=True)
        # Take top unique segment texts
        top_segment_texts = set(txt for txt, score in sorted_by_score[:MAX_AI_LINES] if score > 0)
        # Restore chronological order
        top_lines_ordered = [txt for txt, score in chunk_buffer if txt in top_segment_texts]
        filtered_captions = "\n".join(top_lines_ordered)
        print(f"[Bot] Selected {len(top_lines_ordered)} important lines for AI analysis.")
    else:
        # Fallback: Meeting was casual/low-importance. Use last N lines instead.
        print("[Bot] No 'important' lines found. Falling back to last 800 lines.")
        filtered_captions = "\n".join(caption_lines[-MAX_AI_LINES:])

    chat_text = "\n".join(chat_lines)
    
    transcript = (
        f"CAPTIONS\n{filtered_captions}\n\nCHAT\n{chat_text}".strip()
        if (filtered_captions or chat_text)
        else ""
    )
    date_str   = join_start_time.strftime("%Y-%m-%d")

    print(f"[Bot] Captions collected: {len(caption_lines)}")
    print(f"[Bot] Chat messages captured: {len(chat_lines)}")
    print("[AI] Analysing transcript with LLaMA...")
    ai_results = ai_processor.analyze_text(transcript, date_str)
    ai_results["transcript"] = transcript
    ai_results["captions"] = captions_text
    ai_results["chat_log"] = chat_text

    wa._update_meeting_analysis(
        date_str,
        summary    = ai_results.get("summary", ""),
        tasks      = ai_results.get("tasks", []),
        transcript = transcript
    )
    save_report(meet_link, join_start_time, end_time, ai_results)

    # ── Auto-send WhatsApp report via Twilio ─────────────────
    print("[WhatsApp] Sending meeting report to your WhatsApp...")
    try:
        wa.notify_ended_with_summary(
            meet_link  = meet_link,
            join_time  = join_start_time,
            end_time   = end_time,
            ai_results = ai_results,
        )
        print("[WhatsApp] ✅ Report sent successfully!")
    except Exception as _wa_err:
        print(f"[WhatsApp] ❌ Failed to send report: {_wa_err}")

    # ── Auto-run VTU Diary (only when meeting ended properly) ─
    if result in ("host_ended", "left"):
        print("[VTU] Running VTU Diary automation...")
        try:
            import subprocess
            subprocess.run(["python", "vtu_diary.py"], check=True, timeout=300)
            print("[VTU] ✅ Diary updated successfully!")
        except subprocess.TimeoutExpired:
            print("[VTU] ⚠️ VTU diary timed out after 5 minutes.")
        except subprocess.CalledProcessError as e:
            print(f"[VTU] ❌ Diary script exited with error: {e}")
        except Exception as e:
            print(f"[VTU] ❌ Failed to run diary: {e}")
    else:
        print(f"[VTU] Skipping diary — meeting ended with result: {result}")

    print(f"[Bot] Session complete. Result: {result}")
    return result


# ── Text Report Writer ───────────────────────────────────
def save_report(meet_link: str, join_time: datetime.datetime,
                end_time: datetime.datetime, ai_results: dict):
    """
    Save a formatted plain-text meeting report to reports/ folder.
    Filename: reports/YYYY-MM-DD_HH-MM.txt
    """
    os.makedirs("reports", exist_ok=True)
    date_str = join_time.strftime("%Y-%m-%d")
    time_str = join_time.strftime("%H-%M")
    path     = os.path.join("reports", f"{date_str}_{time_str}.txt")

    delta      = end_time - join_time
    total_mins = max(0, int(delta.total_seconds() // 60))
    hours, mins = divmod(total_mins, 60)
    dur_str    = f"{hours}h {mins}m" if hours else f"{mins} min"

    summary           = ai_results.get("summary", "No summary available.")
    tasks             = ai_results.get("tasks", [])
    learning_outcomes = ai_results.get("learning_outcomes", [])
    transcript    = ai_results.get("transcript", "")
    captions_text = ai_results.get("captions", "")
    chat_text     = ai_results.get("chat_log", "")

    lines = [
        "=" * 60,
        f"  MEETING REPORT",
        "=" * 60,
        f"  Date      : {date_str}",
        f"  Start     : {join_time.strftime('%H:%M')} IST",
        f"  End       : {end_time.strftime('%H:%M')} IST",
        f"  Duration  : {dur_str}",
        f"  Meet Link : {meet_link}",
        "=" * 60,
        "",
        "SUMMARY",
        "-" * 60,
        summary,
        "",
    ]

    if learning_outcomes:
        lines += ["LEARNING OUTCOMES", "-" * 60]
        for idx, outcome in enumerate(learning_outcomes, 1):
            # Clean up any residual markdown the AI might have accidentally added
            clean_outcome = outcome.lstrip('*-• ').strip()
            lines.append(f"  {idx}. {clean_outcome}")
        lines.append("")

    if tasks:
        lines += ["ACTION ITEMS", "-" * 60]
        for t in tasks:
            if isinstance(t, dict):
                flag  = "[URGENT] " if t.get("urgent") else ""
                label = f"  {flag}{t.get('task','')}"
                if t.get("assignee") and t["assignee"].lower() != "unassigned":
                    label += f" (Assignee: {t['assignee']})"
                if t.get("has_deadline"):
                    label += f" | Deadline: {t.get('deadline','')}"
                lines.append(label)
            else:
                lines.append(f"  {t}")
        lines.append("")
    else:
        lines += ["ACTION ITEMS", "-" * 60, "  None identified.", ""]

    if captions_text:
        lines += ["CAPTIONS", "-" * 60, captions_text, ""]

    if chat_text:
        lines += ["CHAT LOG", "-" * 60, chat_text, ""]

    if transcript and not captions_text and not chat_text:
        lines += ["TRANSCRIPT", "-" * 60, transcript, ""]

    lines.append("=" * 60)

    report_text = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[Report] Saved to {path}")
    # Also print to console so you see it immediately
    print()
    print(report_text)


def dismiss_popups(driver):
    """
    Aggressively dismiss all types of popups, alerts, and dialogs on Google Meet.
    Tries multiple strategies to handle different popup types.
    """
    strategies = [
        # Prefer positive/recovery actions first (but NOT Join/Ask buttons anymore)
        (By.XPATH, "//button[contains(., 'Try again')]"),
        (By.XPATH, "//*[@role='dialog']//button"),
        (By.XPATH, "//*[@role='alertdialog']//button"),

        # Then safe dismiss actions only
        (By.XPATH, "//button[contains(text(), 'OK')]"),
        (By.XPATH, "//button[contains(text(), 'Ok')]"),
        (By.XPATH, "//button[contains(text(), 'Okay')]"),
        (By.XPATH, "//button[contains(text(), 'Got it')]"),
        (By.XPATH, "//button[contains(text(), 'Close')]"),
        (By.XPATH, "//button[contains(text(), 'Dismiss')]"),
        (By.XPATH, "//button[contains(text(), 'Skip')]"),
        (By.XPATH, "//button[contains(text(), 'Cancel')]"),
        (By.XPATH, "//button[contains(text(), 'Not now')]"),
        (By.XPATH, "//button[contains(text(), 'No thanks')]"),
        (By.XPATH, "//button[contains(text(), 'Continue without')]"),
        (By.XPATH, "//button[@aria-label='Close']"),
        (By.XPATH, "//button[@aria-label='Dismiss']"),
        (By.XPATH, "//button[@aria-label='Cancel']"),
        (By.CSS_SELECTOR, ".modal button.close"),
    ]
    
    clicked_count = 0
    dangerous_words = [
        "leave", "hang up", "end call", "end meeting", "sign out", "log out", "remove"
    ]

    for strategy_by, strategy_selector in strategies:
        try:
            elements = driver.find_elements(strategy_by, strategy_selector)
            for elem in elements:
                try:
                    if elem.is_displayed():
                        visible_text = (elem.text or "").strip().lower()
                        aria_label = (elem.get_attribute("aria-label") or "").strip().lower()
                        combined = f"{visible_text} {aria_label}"
                        if any(w in combined for w in dangerous_words):
                            continue

                        # Scroll into view before clicking
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
                        time.sleep(0.1)
                        try:
                            elem.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", elem)
                        clicked_count += 1
                        print(f"[Bot] Dismissed popup ({strategy_selector})")
                except Exception:
                    pass
        except Exception:
            pass
    
    return clicked_count > 0
def _schedule_shutdown():
    """
    Schedule a PC shutdown at the configured shutdown_time_ist (default 14:30).
    Uses 'shutdown /s /t N' so Windows counts down exactly to that time.
    If the time has already passed today, shuts down after 60 seconds.
    """
    cfg = load_config()
    shutdown_str = cfg.get("shutdown_time_ist", "14:30")
    try:
        sh, sm = map(int, shutdown_str.split(":"))
    except Exception:
        sh, sm = 14, 30

    now = get_ntp_time_ist()
    target = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    secs = int((target - now).total_seconds())

    if secs <= 0:
        # Already past shutdown time — shut down in 60s
        secs = 60
        print(f"[Shutdown] Shutdown time {shutdown_str} already passed — shutting down in 60s.")
    else:
        h, m = divmod(secs // 60, 60)
        print(f"[Shutdown] PC will shut down at {shutdown_str} IST (in {h}h {m}m).")

    print("[Shutdown] Press Ctrl+C within 10 seconds to cancel.")
    try:
        time.sleep(10)
        os.system(f"shutdown /s /t {secs}")
        print(f"[Shutdown] Shutdown scheduled — Windows will power off in {secs} seconds.")
    except KeyboardInterrupt:
        print("[Shutdown] Shutdown cancelled by user.")


# ── Scheduler ─────────────────────────────────────────────
def run_scheduler():
    """Main wait loop — joins at the configured time every day."""
    target_hour, target_minute = get_join_time()
    joined_today  = False
    reminder_sent = False

    current_ist = get_ntp_time_ist()
    try:
        default_link = get_active_link()
    except ValueError as e:
        print(f"[Scheduler] ❌ {e}")
        return

    print(f"Scheduled join: {default_link}")
    print(f"Join time (IST): {target_hour:02d}:{target_minute:02d}")
    print(f"Current time:    {current_ist.strftime('%H:%M:%S')} IST")
    print(f"Waiting...\n")

    while True:
        now = get_ntp_time_ist()

        # Reset at midnight
        if now.hour == 0 and now.minute == 0 and now.second < 10:
            if joined_today or reminder_sent:
                print("[Scheduler] 🌙 Midnight reset.")
                joined_today  = False
                reminder_sent = False

        # Minutes PAST the scheduled join time (positive = we are past it)
        now_mins    = now.hour * 60 + now.minute
        target_mins = target_hour * 60 + target_minute
        mins_past   = now_mins - target_mins          # negative = not yet reached
        mins_to_join = -mins_past if mins_past < 0 else 0

        # 20-minute reminder
        if not joined_today and not reminder_sent and 19 <= -mins_past <= 20:
            try:
                link      = get_active_link()
                target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                wa.notify_reminder(link, 20, target_dt)
                reminder_sent = True
            except Exception as e:
                print(f"[Scheduler] Reminder error: {e}")

        # Join: fire if within the grace window (0 to JOIN_WINDOW_M minutes past schedule)
        if not joined_today and 0 <= mins_past <= JOIN_WINDOW_M:
            try:
                link = get_active_link()
            except ValueError as e:
                print(f"[Scheduler] ❌ Cannot join: {e}")
                time.sleep(60)
                continue

            print(f"[{now.strftime('%H:%M:%S')} IST] ⏰ Joining now...")
            result  = join_meet(link)
            result2 = None
            joined_today = True

            # Auto-rejoin once if kicked (not if host ended)
            if result == "kicked":
                print("[Scheduler] 🔄 Kicked — rejoining once in 15s...")
                wa.send_whatsapp("🔄 *Meet Bot*: Kicked. Rejoining in 15 seconds...")
                time.sleep(15)
                try:
                    link2 = get_active_link()
                except ValueError:
                    link2 = link
                result2 = join_meet(link2)
                print(f"[Scheduler] Rejoin result: {result2}")

            # Schedule shutdown only — VTU diary now runs inside join_meet()
            final_result = result2 if result2 is not None else result
            if final_result in ("host_ended", "left"):
                _schedule_shutdown()

        # ── Adaptive sleep & countdown display ────────────────
        if not joined_today:
            # mins_past < 0 means we haven't reached join time yet
            real_mins_to_join = -mins_past if mins_past < 0 else 0
            if real_mins_to_join > 60:
                sleep_secs = 60
            elif real_mins_to_join > JOIN_WINDOW_M:
                sleep_secs = 30
            else:
                sleep_secs = 5
            h_left = real_mins_to_join // 60
            m_left = real_mins_to_join % 60
            if mins_past < 0:
                print(f"[{now.strftime('%H:%M')} IST] Waiting {h_left}h {m_left}m until join  (next check in {sleep_secs}s)")
            else:
                print(f"[{now.strftime('%H:%M')} IST] Past join time by {mins_past}m — join window closed. Next join: tomorrow at {target_hour:02d}:{target_minute:02d}")
                sleep_secs = 60
        else:
            sleep_secs = 60

        time.sleep(sleep_secs)


# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import ctypes
    immediate = TEST_MODE or "--now" in sys.argv or "-n" in sys.argv

    print("=" * 54)
    print("  Google Meet Auto-Joiner v2")
    print("=" * 54)
    print()

    # Prevent Windows from sleeping while the bot is active in the background
    try:
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        print("[Bot] 🛡️ Sleep prevention activated.")
    except Exception as e:
        print(f"[Bot] ⚠️ Could not set sleep prevention: {e}")

    if immediate:
        print("[IMMEDIATE] Joining right now...")
        try:
            link = get_active_link()
        except ValueError as e:
            print(f"[IMMEDIATE] Cannot join: {e}")
            sys.exit(1)
        res = join_meet(link)
        print(f"[IMMEDIATE] Done. Result: {res}")
        
        if res in ("host_ended", "left"):
            print(f"[IMMEDIATE] Meeting ended — VTU diary already triggered inside join_meet().")
    else:
        run_scheduler()
