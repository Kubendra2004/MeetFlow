"""
meet_joiner.py  —  Google Meet Auto-Joiner v2
=============================================
Joins a Google Meet at a scheduled time, mutes mic/camera,
records captions, writes AI summary/report locally, and shuts down
the PC when the host ends the meeting.

Edit config.json to change the meeting link or join time.
"""
import time
import traceback
import os
import json
import sys
import ntplib
import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

import ai_processor

# ── Constants ────────────────────────────────────────────
CONFIG_FILE = "config.json"
PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile")
IST_OFFSET  = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
CHROME_VER  = 145   # ← update this if you upgrade Chrome
DB_FILE     = "meetings_db.json"
CHROME_LAUNCH_RETRIES = 3
MEET_PAGELOAD_TIMEOUT = 45

if sys.platform.startswith("linux"):
    CHROMIUM_PATHS = [
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        "/opt/chromium/chromium",
    ]
    CHROMIUM_BIN = next((p for p in CHROMIUM_PATHS if os.path.exists(p)), None)
else:
    CHROMIUM_BIN = None

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


def _load_db() -> dict:
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[DB] Failed to read {DB_FILE}: {e}")
    return {}


def _save_db(db: dict):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[DB] Failed to write {DB_FILE}: {e}")


def _log_meeting_start(date_str: str, record: dict):
    db = _load_db()
    db.setdefault(date_str, [])
    db[date_str].append(record)
    _save_db(db)


def _update_meeting_end(date_str: str, joined_at: str, ended_at: str, duration_minutes: int):
    db = _load_db()
    items = db.get(date_str, [])
    if not isinstance(items, list):
        items = [items]

    for rec in reversed(items):
        if (rec or {}).get("joined_at") == joined_at:
            rec["ended_at"] = ended_at
            rec["duration_minutes"] = duration_minutes
            break
    db[date_str] = items
    _save_db(db)


def _update_meeting_analysis_local(
    date_str: str,
    joined_at: str,
    summary: str,
    tasks: list,
    transcript: str,
    learning_outcomes: list,
):
    db = _load_db()
    items = db.get(date_str, [])
    if not isinstance(items, list):
        items = [items]

    for rec in reversed(items):
        if (rec or {}).get("joined_at") == joined_at:
            rec["summary"] = summary
            rec["tasks"] = tasks
            rec["transcript"] = transcript
            rec["learning_outcomes"] = learning_outcomes
            break
    db[date_str] = items
    _save_db(db)


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


def get_effective_link_preview() -> str:
    """
    Return the currently effective link WITHOUT consuming dynamic override.
    Used for logging/reminders only.
    """
    cfg = load_config()
    override = cfg.get("dynamic_link_override")
    if override:
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
            r = c.request(server, version=3, timeout=3)
            utc = datetime.datetime.fromtimestamp(r.tx_time, tz=datetime.timezone.utc)
            return utc.astimezone(IST_OFFSET)
        except Exception:
            continue
    print("[WARNING] NTP unreachable — falling back to system clock.")
    return datetime.datetime.now(IST_OFFSET)


def _wait_for_document_ready(driver, timeout_s: int = 20) -> bool:
    """Wait until DOM is interactive/complete. Returns False on timeout."""
    try:
        WebDriverWait(driver, timeout_s).until(
            lambda d: (d.execute_script("return document.readyState") or "") in ("interactive", "complete")
        )
        return True
    except Exception:
        return False


def _launch_chrome(options: uc.ChromeOptions):
    """Launch Chrome with small retries to survive transient driver startup failures."""
    last_error = None
    for attempt in range(1, CHROME_LAUNCH_RETRIES + 1):
        try:
            if sys.platform.startswith("linux") and CHROMIUM_BIN:
                print(f"[Join] Using Chromium binary: {CHROMIUM_BIN}")
                driver = uc.Chrome(
                    options=options,
                    version_main=CHROME_VER,
                    browser_executable_path=CHROMIUM_BIN,
                )
            else:
                driver = uc.Chrome(options=options, version_main=CHROME_VER)

            driver.set_page_load_timeout(MEET_PAGELOAD_TIMEOUT)
            return driver
        except Exception as e:
            last_error = e
            print(f"[Join] Chrome launch failed (attempt {attempt}/{CHROME_LAUNCH_RETRIES}): {e}")
            time.sleep(2)

    raise RuntimeError(f"Chrome launch failed after retries: {last_error}")


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
    
    # Keep browser visible as requested; headless remains disabled for Meet reliability.
    options.add_argument("--start-maximized")
    
    return options


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


def _ensure_device_off(driver, keyword: str) -> tuple[bool, bool]:
    """
    Ensure a pre-join media device is OFF.
    Returns (found_visible_button, is_off_after_action).
    """
    if keyword == "microphone":
        aliases = ["microphone", "mic"]
    else:
        aliases = ["camera", "video"]

    try:
        candidates = []
        for alias in aliases:
            xp = (
                "//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                f"'{alias}') and (self::button or @role='button' or self::div)]"
            )
            candidates.extend(driver.find_elements(By.XPATH, xp))

        # Deduplicate by underlying element id if possible.
        seen = set()
        btns = []
        for el in candidates:
            try:
                key = el.id
            except Exception:
                key = str(id(el))
            if key in seen:
                continue
            seen.add(key)
            btns.append(el)

        found_visible = False
        for btn in btns:
            if not btn.is_displayed():
                continue
            found_visible = True

            label = ((btn.get_attribute("aria-label") or "") + " " + (btn.text or "")).strip().lower()
            aria_pressed = (btn.get_attribute("aria-pressed") or "").strip().lower()
            is_relevant = any(a in label for a in aliases)
            if not is_relevant:
                continue

            # Most Meet media toggles expose aria-pressed=true (on) / false (off).
            if aria_pressed == "false":
                return True, True
            if aria_pressed == "true":
                for _ in range(2):
                    try:
                        btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.35)
                    new_pressed = (btn.get_attribute("aria-pressed") or "").strip().lower()
                    if new_pressed == "false":
                        return True, True
                return True, False

            # Off-state label variants observed on Meet UIs.
            off_markers = [
                "turn on",
                "is off",
                "off",
            ]
            on_markers = [
                "turn off",
                "is on",
                "on",
            ]

            if any(m in label for m in off_markers) and not any(m in label for m in on_markers if m != "on"):
                return True, True

            if "turn off" in label or "is on" in label or f"{aliases[0]} on" in label or f"{aliases[-1]} on" in label:
                # Click to turn device off, then verify by re-reading aria-label.
                for _ in range(2):
                    try:
                        btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.35)
                    new_label = ((btn.get_attribute("aria-label") or "") + " " + (btn.text or "")).strip().lower()
                    if any(a in new_label for a in aliases) and ("turn on" in new_label or "is off" in new_label):
                        return True, True

                # Found control but failed to verify OFF state.
                return True, False

        return found_visible, False
    except Exception:
        pass
    return False, False


def _prejoin_media_ready(driver) -> bool:
    """Return True only when both mic and camera toggles are visible and OFF."""
    mic_found, mic_off = _ensure_device_off(driver, "microphone")
    cam_found, cam_off = _ensure_device_off(driver, "camera")
    return mic_found and cam_found and mic_off and cam_off


def _prejoin_media_state(driver) -> dict:
    """Return detailed pre-join media state for logging and fallback decisions."""
    mic_found, mic_off = _ensure_device_off(driver, "microphone")
    cam_found, cam_off = _ensure_device_off(driver, "camera")
    return {
        "mic_found": mic_found,
        "mic_off": mic_off,
        "cam_found": cam_found,
        "cam_off": cam_off,
        "ready": mic_found and cam_found and mic_off and cam_off,
    }


def _has_join_controls(driver) -> bool:
    """Detect visible join-related controls without clicking."""
    xpaths = [
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'ask to join')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'join now')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'join the call')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'ready to join')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'rejoin')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join the call')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'rejoin')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join the call')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
    ]
    for xp in xpaths:
        try:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed():
                    return True
        except Exception:
            continue
    return False


def _has_preview_ui(driver) -> bool:
    """Detect preview/lobby-only UI markers (means not yet inside call)."""
    xpaths = [
        "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'other ways to join')]",
        "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
        "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
    ]
    for xp in xpaths:
        try:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed():
                    return True
        except Exception:
            continue
    return False


def enable_captions(driver) -> bool:
    """
    Try to turn on Google Meet live captions (CC button).
    Returns True if captions were activated.
    """
    time.sleep(2)   # let toolbar render after joining
    try:
        # Try aria-label variations Google uses for the CC button
        cc_labels = [
            "Turn on captions", "Captions", "closed captions",
            "Turn on closed captions", "CC",
        ]
        for label in cc_labels:
            btns = driver.find_elements(
                By.XPATH,
                f"//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                f"'abcdefghijklmnopqrstuvwxyz'), '{label.lower()}')]"
            )
            for btn in btns:
                if btn.is_displayed():
                    btn.click()
                    print("[Bot] Captions enabled ✅")
                    return True
    except Exception as e:
        print(f"[Bot] Caption toggle error: {e}")
    print("[Bot] ⚠️  Could not find captions button — transcript will be empty.")
    return False


def scrape_captions(driver) -> str:
    """
    Extract current caption text visible on screen.
    Tries multiple selectors that Google Meet uses across versions.
    Filters out Google Meet UI strings (settings menus, font controls, etc.)
    """
    # Known Google Meet UI strings that pollute caption scraping
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

        # Filter each line: reject if it's a UI noise string or too short
        clean_lines = []
        for line in raw.splitlines():
            line = line.strip()
            if len(line) < 5:
                continue
            if line.lower() in UI_NOISE:
                continue
            # Reject lines made entirely of UI keywords
            words = set(line.lower().split())
            if words and words.issubset(UI_NOISE):
                continue
            clean_lines.append(line)

        return " ".join(clean_lines)

    except Exception:
        return ""



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
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'join the call')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'join the call now')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'ready to join')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'rejoin')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'join call')]",
        "//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'try again')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join the call')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
        "//div[@role='button']//span[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'rejoin')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ask to join')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join the call')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ready to join')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'rejoin')]",
        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'try again')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join now')]",
        "//div[@role='button' and contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join the call')]",
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

    # Fallback: text-based JS click for Meet UI variants where text is nested differently.
    try:
        clicked = driver.execute_script("""
            const patterns = ['join the call now', 'join the call', 'join now', 'ask to join', 'ready to join', 'rejoin'];
            const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
            for (const el of candidates) {
                const txt = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase().trim();
                if (!txt) continue;
                if (patterns.some(p => txt.includes(p))) {
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return true;
                }
            }
            return false;
        """)
        if clicked:
            return True
    except Exception:
        pass

    return False


def _is_in_meeting_ui(driver) -> bool:
    """
    Detect if user is already inside meeting (toolbar visible).
    """
    # If preview/lobby controls are visible, we are NOT in the active call yet.
    if _has_join_controls(driver) or _has_preview_ui(driver):
        return False

    checks = [
        "//button[contains(@aria-label,'Leave')]",
        "//button[contains(@aria-label,'Hang up')]",
        "//div[@role='button' and contains(@aria-label,'Leave')]",
        "//button[contains(@aria-label,'People')]",
        "//button[contains(@aria-label,'Chat')]",
    ]
    for xp in checks:
        try:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed():
                    return True
        except Exception:
            continue
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


def _force_media_off_in_call(driver):
    """Best-effort in-call mute to guarantee mic/camera are not left ON after joining."""
    targets = [
        "microphone",
        "camera",
    ]

    for target in targets:
        aliases = [target]
        if target == "microphone":
            aliases.append("mic")
        if target == "camera":
            aliases.append("video")

        try:
            els = []
            for alias in aliases:
                xp = (
                    "//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                    f"'{alias}') and (self::button or @role='button' or self::div)]"
                )
                els.extend(driver.find_elements(By.XPATH, xp))

            for el in els:
                if not el.is_displayed():
                    continue
                label = ((el.get_attribute("aria-label") or "") + " " + (el.text or "")).lower()
                if not any(a in label for a in aliases):
                    continue

                # If label says "Turn off ...", device is currently ON; click once to turn it OFF.
                if "turn off" in label or "is on" in label:
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                    print(f"[Join] Forced {target} OFF after join.")
                    time.sleep(0.2)
                    break
        except Exception:
            continue


def join_with_popup_retries(driver, timeout_s: int = 120) -> bool:
    """
    Retry join flow while dismissing popups so transient dialogs
    do not block meeting entry.
    """
    end_at = time.time() + max(30, timeout_s)
    start_at = time.time()
    waiting_logged = False
    media_wait_logged = False
    media_fallback_logged = False
    did_one_full_reload = False
    last_media_status_log = 0.0
    media_strict_wait_s = 22

    while time.time() < end_at:
        # Stop retrying if we are already admitted.
        if _is_in_meeting_ui(driver):
            return True

        dismiss_popups(driver)

        # Ask-to-join flow can hide Join controls while host admits.
        if _is_waiting_for_admission(driver):
            if not waiting_logged:
                print("[Join] Ask-to-join sent. Waiting for host approval...")
                waiting_logged = True
            time.sleep(2.0)
            continue

        has_join_controls = _has_join_controls(driver)

        # Strict pre-join gate: enforce media-off only when join controls are present.
        # This avoids deadlocks on intermediate Meet loading/preview transitions.
        if has_join_controls:
            media = _prejoin_media_state(driver)
            if not media["ready"]:
                elapsed = time.time() - start_at
                now = time.time()
                if not media_wait_logged:
                    print("[Join] Join controls found. Waiting for mic/camera to be visible and OFF...")
                    media_wait_logged = True
                if now - last_media_status_log >= 4:
                    print(
                        "[Join] Media state: "
                        f"mic(found={media['mic_found']},off={media['mic_off']}), "
                        f"cam(found={media['cam_found']},off={media['cam_off']})"
                    )
                    last_media_status_log = now

                # After a grace window, don't hard-deadlock if Meet UI variant hides states.
                if elapsed < media_strict_wait_s:
                    time.sleep(0.9)
                    continue

                if not media_fallback_logged:
                    print("[Join] Media state not fully verifiable after wait; applying best-effort mute fallback.")
                    media_fallback_logged = True
                mute_device(driver, "microphone")
                mute_device(driver, "camera")
                time.sleep(0.4)
                media = _prejoin_media_state(driver)
                if not media["ready"]:
                    print("[Join] Proceeding with join (best-effort media mute applied).")

        # Join controls sometimes never render due to transient Meet state.
        # Perform one full page reload automatically if controls are missing.
        if not has_join_controls:
            elapsed = time.time() - start_at
            if not did_one_full_reload and elapsed > 15 and not _is_waiting_for_admission(driver):
                print("[Join] Join controls missing — doing one full Meet page reload...")
                try:
                    driver.refresh()
                    _wait_for_document_ready(driver, timeout_s=20)
                    time.sleep(1.5)
                    dismiss_popups(driver)
                    did_one_full_reload = True
                    media_wait_logged = False
                    last_media_status_log = 0.0
                    continue
                except Exception as e:
                    print(f"[Join] Reload attempt failed: {e}")

        if click_join_button(driver):
            # Give Meet a short window to transition from preview to in-call UI.
            deadline = time.time() + 12
            while time.time() < deadline:
                if _is_in_meeting_ui(driver):
                    return True
                if _is_waiting_for_admission(driver):
                    break
                time.sleep(0.4)

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


# ── Core join function ────────────────────────────────────
def join_meet(meet_link: str) -> str:
    """
    Opens Chrome, mutes mic/camera, joins the meeting, scrapes live
    captions, runs LLaMA analysis, and saves local report/database.
    No audio file is created — captions are read directly from the DOM.

    Returns one of: 'host_ended' | 'kicked' | 'left' | 'error'
    """
    now             = get_ntp_time_ist()
    join_start_time = now
    driver          = None
    result          = "error"
    caption_lines: list[str] = []      # accumulated caption lines
    chat_lines: list[str] = []         # accumulated chat lines
    seen_chat_lines: set[str] = set()
    last_caption    = ""              # dedup: skip repeated lines
    joined_at_iso   = ""

    print(f"\n{'='*54}")
    print(f"  [{now.strftime('%Y-%m-%d %H:%M:%S')} IST] Joining: {meet_link}")
    print(f"{'='*54}")

    try:
        options = build_chrome_options()
        driver = _launch_chrome(options)

        driver.get(meet_link)
        _wait_for_document_ready(driver, timeout_s=20)
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
            return "error"

        join_start_time = get_ntp_time_ist()
        joined_at_iso = join_start_time.isoformat()
        print("[Join] Joined the meeting!")
        _force_media_off_in_call(driver)
        _log_meeting_start(join_start_time.strftime("%Y-%m-%d"), {
            "meet_link": meet_link,
            "joined_at": joined_at_iso,
            "ended_at": None,
            "duration_minutes": None,
            "summary": "Auto-joined by bot",
            "tasks": [],
            "key_decisions": [],
            "learning_outcomes": [],
            "transcript": "",
        })
        
        # Dismiss any popups that appear after joining
        time.sleep(1)
        dismiss_popups(driver)
        time.sleep(1)

        # ── Enable live captions ───────────────────────────
        enable_captions(driver)
        time.sleep(2)

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
        last_caption_scrape = time.time()   # scrape captions every 15 minutes
        CAPTION_INTERVAL    = 900           # 15 minutes in seconds
        last_chat_scrape    = 0.0
        CHAT_INTERVAL       = 6             # seconds
        last_chat_open_try  = 0.0
        CHAT_OPEN_INTERVAL  = 25            # seconds

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

                # ── Collect captions (once per minute) ──────
                _now = time.time()
                if _now - last_caption_scrape >= CAPTION_INTERVAL:
                    last_caption_scrape = _now
                    cap = scrape_captions(driver).strip()
                    if cap and cap != last_caption:
                        caption_lines.append(cap)
                        last_caption = cap
                        cap_lower = cap.lower()
                        if any(phrase in cap_lower for phrase in FAREWELL):
                            farewell_detected = True
                            print(f"[Bot] Farewell detected in caption — leaving now.")
                            time.sleep(3)
                            _click_leave(driver)
                            result = "host_ended"
                            break

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
                            print(f"[Chat] {msg[:120]}")

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
    captions_text = "\n".join(caption_lines)
    chat_text = "\n".join(chat_lines)
    transcript = (
        f"CAPTIONS\n{captions_text}\n\nCHAT\n{chat_text}".strip()
        if (captions_text or chat_text)
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

    _update_meeting_analysis_local(
        date_str,
        joined_at_iso,
        summary=ai_results.get("summary", ""),
        tasks=ai_results.get("tasks", []),
        transcript=transcript,
        learning_outcomes=ai_results.get("learning_outcomes", []),
    )

    total_mins = max(0, int((end_time - join_start_time).total_seconds() // 60))
    _update_meeting_end(date_str, joined_at_iso, end_time.isoformat(), total_mins)

    save_report(meet_link, join_start_time, end_time, ai_results)

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
        default_link = get_effective_link_preview()
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

        # 20-minute local reminder (console only)
        if not joined_today and not reminder_sent and 19 <= -mins_past <= 20:
            try:
                link      = get_effective_link_preview()
                target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                print(f"[Scheduler] ⏰ Reminder: meeting in 20 minutes at {target_dt.strftime('%H:%M')} IST -> {link}")
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
                time.sleep(15)
                link2 = link
                result2 = join_meet(link2)
                print(f"[Scheduler] Rejoin result: {result2}")

            # Execute VTU diary & Schedule shutdown only if meeting genuinely ended
            final_result = result2 if result2 is not None else result
            if final_result in ("host_ended", "left"):
                print(f"[Scheduler] Meeting ended ({final_result}). Running VTU Diary Automation...")
                try:
                    import subprocess
                    subprocess.run(["python", "vtu_diary.py"], check=True)
                except Exception as e:
                    print(f"[Scheduler] ❌ Failed to run VTU diary: {e}")
                
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
            print(f"[IMMEDIATE] Meeting ended. Running VTU Diary Automation...")
            try:
                import subprocess
                subprocess.run(["python", "vtu_diary.py"], check=True)
            except Exception as e:
                print(f"[IMMEDIATE] ❌ Failed to run VTU diary: {e}")
    else:
        run_scheduler()
