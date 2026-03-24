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
import json
import ntplib
import sys
import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import whatsapp_notifier as wa
import ai_processor

# ── Constants ────────────────────────────────────────────
CONFIG_FILE = "config.json"

if sys.platform.startswith("linux"):
    PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile_linux")
else:
    PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile")
IST_OFFSET  = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
CHROME_VER  = 145   # ← update this if you upgrade Chrome

# Testing mode: set True to join immediately without waiting.
# Or run:  python meet_joiner.py --now
TEST_MODE     = False
JOIN_WINDOW_M = 10   # join if within this many minutes past the scheduled time
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
            r = c.request(server, version=3, timeout=3)
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

    # Allow mic/camera without popup prompts
    options.add_argument("--use-fake-ui-for-media-stream")
    # Use the persistent profile (keeps you signed in)
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")

    # ── Resource efficiency ──
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-default-apps")
    options.add_argument("--js-flags=--max-old-space-size=512")
    # NOTE: --disable-background-networking and --disable-sync removed
    # They break Google session auth and WebRTC (Meet won't load correctly)

    # Grant mic and camera permissions at browser level
    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.media_stream_mic": 1,
        "profile.default_content_setting_values.media_stream_camera": 1,
    })
    
    # Run invisibly off-screen to avoid interrupting the user.
    # We do NOT use --headless=new because it breaks Google Meet WebRTC/media permissions.
    options.add_argument("--window-position=-32000,-32000")
    
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


def click_join_button(driver) -> bool:
    """
    Try all known XPaths for Ask-to-join / Join-now buttons.
    Returns True if found and clicked, False otherwise.
    Waits up to 15 seconds total.
    """
    xpaths = [
        "//span[contains(text(), 'Ask to join')]",
        "//span[contains(text(), 'Join now')]",
        "//div[@role='button']//span[text()='Ask to join']",
        "//div[@role='button']//span[text()='Join now']",
        "//button[.//span[contains(text(),'Ask to join')]]",
        "//button[.//span[contains(text(),'Join now')]]",
    ]
    for xpath in xpaths:
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            btn.click()
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
    captions, runs LLaMA analysis, sends WhatsApp report.
    No audio file is created — captions are read directly from the DOM.

    Returns one of: 'host_ended' | 'kicked' | 'left' | 'error'
    """
    now             = get_ntp_time_ist()
    join_start_time = now
    driver          = None
    result          = "error"
    transcript_lines: list[str] = []   # accumulated caption lines
    last_caption    = ""              # dedup: skip repeated lines

    print(f"\n{'='*54}")
    print(f"  [{now.strftime('%Y-%m-%d %H:%M:%S')} IST] Joining: {meet_link}")
    print(f"{'='*54}")

    try:
        options = build_chrome_options()
        driver  = uc.Chrome(options=options, version_main=CHROME_VER)
        driver.get(meet_link)
        print("[Join] Page loaded. Waiting for preview screen...")
        time.sleep(4)

        # ── Mute mic & camera ──────────────────────────────
        mute_device(driver, "microphone")
        time.sleep(0.5)
        mute_device(driver, "camera")
        time.sleep(0.5)

        # ── Click Join button ──────────────────────────────
        joined = click_join_button(driver)
        if not joined:
            print("[Join] Could not find Join button — are you signed in?")
            wa.notify_failed(meet_link, "Join button not found. Check Chrome sign-in.")
            return "error"

        join_start_time = get_ntp_time_ist()
        print("[Join] Joined the meeting!")
        wa.notify_joined(meet_link, join_start_time)

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

        popup_xpaths = [
            "//span[contains(text(),'OK')]", "//span[contains(text(),'Ok')]",
            "//span[contains(text(),'Got it')]", "//button[contains(text(),'OK')]",
            "//button[contains(text(),'Got it')]",
        ]

        print(f"[Bot] Monitoring meeting (max {cfg_max} min)...")
        consecutive_errors = 0
        farewell_detected   = False
        last_caption_scrape = time.time()   # scrape captions every 15 minutes
        CAPTION_INTERVAL    = 900           # 15 minutes in seconds

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
                # Google redirects away from the meeting code when host ends
                if meet_code not in url:
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
                        transcript_lines.append(cap)
                        last_caption = cap
                        cap_lower = cap.lower()
                        if any(phrase in cap_lower for phrase in FAREWELL):
                            farewell_detected = True
                            print(f"[Bot] Farewell detected in caption — leaving now.")
                            time.sleep(3)
                            _click_leave(driver)
                            result = "host_ended"
                            break

                # ── Page-level end state detection ──────────
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
                for px in popup_xpaths:
                    try:
                        btn = driver.find_element(By.XPATH, px)
                        if btn.is_displayed():
                            btn.click()
                    except Exception:
                        pass

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
    transcript = "\n".join(transcript_lines)
    date_str   = join_start_time.strftime("%Y-%m-%d")

    print(f"[Bot] Captions collected: {len(transcript_lines)} lines ({len(transcript)} chars)")
    print("[AI] Analysing transcript with LLaMA...")
    ai_results = ai_processor.analyze_text(transcript, date_str)

    wa._update_meeting_analysis(
        date_str,
        summary    = ai_results.get("summary", ""),
        tasks      = ai_results.get("tasks", []),
        transcript = transcript
    )
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

    if transcript:
        lines += ["TRANSCRIPT", "-" * 60, transcript, ""]

    lines.append("=" * 60)

    report_text = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[Report] Saved to {path}")
    # Also print to console so you see it immediately
    print()
    print(report_text)


# ── Scheduled shutdown ────────────────────────────────────
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

        # 10-minute reminder
        if not joined_today and not reminder_sent and 9 <= -mins_past <= 10:
            try:
                link      = get_active_link()
                target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                wa.notify_reminder(link, 10, target_dt)
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
    immediate = TEST_MODE or "--now" in sys.argv or "-n" in sys.argv

    print("=" * 54)
    print("  Google Meet Auto-Joiner v2")
    print("=" * 54)
    print()

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
