"""
vtu_diary.py  —  VTU Internship Portal Auto-Fill
==================================================
Logs in, navigates to Internship Diary, and fills all
required fields using today's AI meeting report.

Usage:
    python vtu_diary.py          # login + auto-fill today's diary
    python vtu_diary.py --test   # dry-run: fills form but does NOT click submit

Credentials in .env:
    VTU_USERNAME="yourname@gmail.com"
    VTU_PASSWORD="yourPass@word#123"

Skills config in config.json:
    "vtu_skills": ["Python", "Android Development", "GenAI"]
    "vtu_hours":  6.5
"""
import os, sys, time, json, glob, re, traceback, datetime, random
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────
PORTAL_URL  = "https://vtu.internyet.in/sign-in"
DIARY_URL   = "https://vtu.internyet.in/dashboard/student/student-diary"
PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile_vtu")

CHROME_VER  = 145
TIMEOUT     = 15

VTU_USERNAME = os.getenv("VTU_USERNAME", "").strip().strip('"')
VTU_PASSWORD = os.getenv("VTU_PASSWORD", "").strip().strip('"')

def load_cfg():
    try:
        with open("config.json") as f:
            return json.load(f)
    except Exception:
        return {}

# ── Driver ─────────────────────────────────────────────────
def build_driver():
    opts = uc.ChromeOptions()
    
    # Ensure profile directory exists
    os.makedirs(PROFILE_DIR, exist_ok=True)
    print(f"[VTU] Using profile: {PROFILE_DIR}")
    
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-translate")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--log-level=3")
    
    # Run entirely headless/invisibly in the background
    opts.add_argument("--headless=new")
    
    # Use Chromium binary on Linux if detected
    if sys.platform.startswith("linux") and CHROMIUM_BIN:
        print(f"[VTU] Using Chromium binary: {CHROMIUM_BIN}")
        return uc.Chrome(options=opts, version_main=CHROME_VER, browser_executable_path=CHROMIUM_BIN)
    else:
        return uc.Chrome(options=opts, version_main=CHROME_VER)

# ── Popup dismisser ─────────────────────────────────────────
def dismiss_popups(driver):
    """Close any overlay/popup by trying common close patterns."""
    selectors = [
        "button[aria-label='Close']", "button[aria-label='Dismiss']",
        ".modal button.close", "[data-dismiss='modal']",
        "//button[contains(text(),'Close')]", "//button[contains(text(),'OK')]",
        "//button[contains(text(),'Got it')]", "//span[contains(text(),'×')]",
    ]
    for sel in selectors:
        try:
            by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
            btn = driver.find_element(by, sel)
            if btn.is_displayed():
                btn.click()
                print(f"[VTU] Dismissed popup via: {sel}")
                time.sleep(0.5)
        except Exception:
            pass

# ── Login ───────────────────────────────────────────────────
def login(driver) -> bool:
    print("[VTU] Opening sign-in page...")
    driver.get(PORTAL_URL)
    time.sleep(3)
    dismiss_popups(driver)

    # ── Already logged in? Skip form entirely ──────────────
    if "sign-in" not in driver.current_url and "login" not in driver.current_url:
        print(f"[VTU] ✅ Already logged in! URL: {driver.current_url}")
        return True

    if not VTU_USERNAME or not VTU_PASSWORD:
        print("[VTU] ❌  VTU_USERNAME or VTU_PASSWORD not set in .env")
        return False

    try:
        wait = WebDriverWait(driver, TIMEOUT)

        email_field = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[autocomplete='email'], input[placeholder*='email']")
        ))
        email_field.clear()
        email_field.send_keys(VTU_USERNAME)

        pwd_field = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[type='password'], input#password")
        ))
        pwd_field.clear()
        pwd_field.send_keys(VTU_PASSWORD)

        submit = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button[type='submit']")
        ))
        submit.click()
        print("[VTU] Sign-in clicked — waiting for dashboard...")

        for _ in range(20):
            time.sleep(1)
            if "sign-in" not in driver.current_url and "login" not in driver.current_url:
                break
        else:
            print("[VTU] ❌  Still on sign-in page — check credentials.")
            return False

        dismiss_popups(driver)
        print(f"[VTU] ✅ Logged in! URL: {driver.current_url}")
        return True

    except Exception as e:
        print(f"[VTU] ❌  Login error: {e}")
        traceback.print_exc()
        return False

# ── Load meeting report ─────────────────────────────────────
def load_todays_report() -> dict:
    """Read the most recent report from reports/ and parse it."""
    
    # Check for CLI date override
    target_date = datetime.date.today().strftime("%Y-%m-%d")
    if "--date" in sys.argv:
        try:
            target_date = sys.argv[sys.argv.index("--date") + 1]
            print(f"[VTU] Override date detected: {target_date}")
        except IndexError:
            pass

    files = sorted(glob.glob(f"reports/{target_date}_*.txt"), reverse=True)
    if not files:
        # Fallback: latest report of any date
        files = sorted(glob.glob("reports/*.txt"), reverse=True)
    if not files:
        print("[VTU] ⚠️  No meeting report found — using placeholders.")
        return {}

    print(f"[VTU] Using report: {files[0]}")
    content = open(files[0], encoding="utf-8").read()

    def extract(section, next_section):
        pattern = rf"{section}\n-+\n(.*?)(?={next_section}|\Z)"
        m = re.search(pattern, content, re.DOTALL)
        return m.group(1).strip() if m else ""

    summary   = extract("SUMMARY", "LEARNING OUTCOMES|ACTION ITEMS|TRANSCRIPT|=")
    learnings = extract("LEARNING OUTCOMES", "ACTION ITEMS|TRANSCRIPT|=")

    if not learnings:
        # Fallback if old report format (KEY DECISIONS)
        dec_old = extract("KEY DECISIONS", "ACTION ITEMS|TRANSCRIPT|=")
        tsk_old = extract("ACTION ITEMS", "TRANSCRIPT|=")
        parts = []
        if dec_old: parts.append("Key Decisions:\n" + dec_old)
        if tsk_old: parts.append("Action Items:\n" + tsk_old)
        learnings_fallback = "\n\n".join(parts)
        learnings = learnings_fallback or "Attended internship meeting and reviewed tasks."

    # Duration from header
    dur_match = re.search(r"Duration\s*:\s*(.+)", content)
    dur_str   = dur_match.group(1).strip() if dur_match else ""
    hours     = _parse_hours(dur_str)

    # Extract date from filename: reports/2026-03-24_13-00.txt
    fname     = os.path.basename(files[0])
    date_str  = fname[:10]   # first 10 chars = YYYY-MM-DD

    # Check for Google Cloud keywords
    extra_skills = []
    if re.search(r"\b(google|cloud|gcp)\b", content, re.IGNORECASE):
        extra_skills.append("Google Cloud")

    return {
        "date":         date_str,
        "summary":      summary or "Attended internship meeting and discussed project progress.",
        "learnings":    learnings,
        "hours":        hours,
        "extra_skills": extra_skills,
    }

def _parse_hours(dur_str: str) -> float:
    """Return a random float between 8.0 and 12.0 (in 0.5 increments)."""
    # E.g., 8.0, 8.5, 9.0, ..., 12.0
    val = random.choice([7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0])
    return val

# ── Date picker helper (calendar UI) ─────────────────────────
def pick_date(driver, wait, date_str: str):
    """
    Click a calendar-style date picker.
    Opens the calendar by clicking the trigger, navigates to the
    correct month if needed, then clicks the correct day number.
    date_str format: YYYY-MM-DD
    """
    dt          = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    target_day  = dt.day                    # e.g. 24
    target_mon  = dt.strftime("%b")         # e.g. "Mar"
    target_year = dt.year                   # e.g. 2026

    # ── 1. Open the calendar ────────────────────────────────
    opened = False
    # Try clicking the input field first
    for sel in ["input[placeholder*='Pick']", "input[placeholder*='Date']",
                "input[placeholder*='date']"]:
        try:
            inp = driver.find_element(By.CSS_SELECTOR, sel)
            inp.click()
            time.sleep(0.8)
            opened = True
            break
        except Exception:
            pass

    if not opened:
        # Fallback: click any element that says 'Pick a Date'
        try:
            driver.find_element(
                By.XPATH, "//*[contains(text(),'Pick a Date')]"
            ).click()
            time.sleep(0.8)
        except Exception as e:
            print(f"[VTU] ⚠️  Could not open date picker: {e}")
            return

    # ── 2. Navigate to correct month (max 12 clicks) ────────
    for _ in range(12):
        try:
            mon_text  = driver.find_element(
                By.XPATH, "//button[contains(@class,'month')] | //select[@class*='month']"
                          " | //div[contains(@class,'month-year')] | //span[contains(@class,'month')]"
            ).text
            year_text = driver.execute_script("return document.title;")  # fallback
        except Exception:
            mon_text = ""

        # Simpler: read all visible text in the calendar header area
        try:
            header = driver.find_element(
                By.XPATH,
                "//*[contains(@class,'calendar') or contains(@class,'Calendar') "
                "or contains(@class,'DayPicker') or contains(@class,'rdp')]"
            ).text
        except Exception:
            header = driver.execute_script(
                "return document.body.innerText.slice(0,500);"
            ) or ""

        # Check if target month+year visible
        if target_mon in header and str(target_year) in header:
            break

        # Click next month arrow
        try:
            nxt = driver.find_element(
                By.XPATH,
                "//button[@aria-label='Go to next month'] "
                "| //button[contains(@aria-label,'next')] "
                "| //button[.='\u203a'] | //button[.='>'] "
                "| //*[@class='rdp-nav_button rdp-nav_button_next']"
            )
            nxt.click()
            time.sleep(0.5)
        except Exception:
            break

    # ── 3. Click the target day number ──────────────────────
    day_str = str(target_day)
    day_xpaths = [
        # Exact text match, not disabled/greyed
        f"//button[normalize-space(.)='{day_str}' and not(@disabled)]",
        f"//td[normalize-space(.)='{day_str}' and not(@disabled)]",
        f"//div[normalize-space(.)='{day_str}' and not(@disabled) and not(contains(@class,'outside'))]",
        # Fallback: aria-label with date
        f"//*[contains(@aria-label,'{target_mon}') and contains(@aria-label,'{target_year}') and contains(@aria-label,'{day_str}')]",
    ]
    for xp in day_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn.is_displayed():
                btn.click()
                print(f"[VTU] ✅ Date clicked: {date_str} (day {day_str})")
                time.sleep(0.5)
                return
        except Exception:
            pass

    # Final fallback: JS click any visible element with exact day number
    result = driver.execute_script(f"""
        var candidates = document.querySelectorAll('button, td, [role="gridcell"]');
        for (var el of candidates) {{
            if (el.innerText.trim() === '{day_str}' && el.offsetParent !== null
                && !el.disabled && !el.getAttribute('aria-disabled')) {{
                el.click(); return el.outerHTML.slice(0,80);
            }}
        }}
        return null;
    """)
    if result:
        print(f"[VTU] ✅ Date clicked via JS fallback: {date_str}")
    else:
        print(f"[VTU] ⚠️  Could not click day {day_str} in calendar.")

# ── Skills multi-select helper ──────────────────────────────
def add_skills(driver, wait, skills: list):
    """
    Type each skill into the 'Add skills' multi-select dropdown and
    select it from the suggestion list.
    """
    try:
        # Click the skills input/dropdown
        skills_input = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR,
             "input[placeholder*='skill'], input[placeholder*='Skill'], "
             "[placeholder*='Add skills'] input, "
             ".skills-select input, [class*='skill'] input")
        ))
    except Exception:
        # Broader fallback: find by label
        try:
            container = driver.find_element(
                By.XPATH,
                "//*[contains(text(),'Skills Used')]/following::div[1]"
            )
            skills_input = container.find_element(By.TAG_NAME, "input")
        except Exception as e2:
            print(f"[VTU] ⚠️  Skills input not found: {e2}")
            return

    for skill in skills:
        try:
            skills_input.click()
            time.sleep(0.3)
            skills_input.clear()
            skills_input.send_keys(skill)
            time.sleep(1)  # wait for dropdown options

            # Click the matching option
            option_xpaths = [
                f"//div[contains(@class,'option') and contains(text(),'{skill}')]",
                f"//*[@role='option' and contains(text(),'{skill}')]",
                f"//li[contains(text(),'{skill}')]",
                f"//*[contains(@class,'menu-item') and contains(text(),'{skill}')]",
            ]
            clicked = False
            for xp in option_xpaths:
                try:
                    opt = driver.find_element(By.XPATH, xp)
                    if opt.is_displayed():
                        opt.click()
                        clicked = True
                        print(f"[VTU] ✅ Skill selected: {skill}")
                        time.sleep(0.4)
                        break
                except Exception:
                    pass

            if not clicked:
                # Try pressing Enter to confirm typed value
                skills_input.send_keys(Keys.RETURN)
                print(f"[VTU] ⚠️  Pressed Enter for skill: {skill}")
                time.sleep(0.3)

        except Exception as e:
            print(f"[VTU] ⚠️  Could not add skill '{skill}': {e}")

# ── Main fill function ──────────────────────────────────────
def fill_diary(driver):
    cfg       = load_cfg()
    report    = load_todays_report()
    # Use the date from the report filename; fall back to today
    diary_date = report.get("date") or datetime.date.today().strftime("%Y-%m-%d")
    skills    = cfg.get("vtu_skills", ["Android Studio", "Kotlin", "UI/UX"])
    
    # Add dynamic extra skills (like Google Cloud)
    extra = report.get("extra_skills", [])
    for s in extra:
        if s not in skills:
            skills.append(s)

    hours     = report.get("hours", random.choice([8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0]))
    summary   = report.get("summary", "Attended internship meeting.")
    learnings = report.get("learnings", "Reviewed project progress and key decisions.")
    print(f"[VTU] Filing diary for date: {diary_date}")
    print(f"[VTU] Summary: {summary[:80]}...")

    wait = WebDriverWait(driver, TIMEOUT)

    # ── Navigate to Internship Diary ────────────────────────
    print("[VTU] Navigating to Internship Diary...")
    driver.get(DIARY_URL)
    time.sleep(4)
    dismiss_popups(driver)

    # Verify we landed on diary page; if not, try sidebar link
    if "student-diary" not in driver.current_url:
        print(f"[VTU] Not on diary URL ({driver.current_url}), clicking sidebar...")
        # Scroll sidebar into view and click
        try:
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            link = None
            # Try href-based link first
            for href in ["student-diary", "internship-diary"]:
                try:
                    link = driver.find_element(
                        By.XPATH, f"//a[contains(@href,'{href}') and not(contains(@href,'entries'))]"
                    )
                    break
                except Exception:
                    pass
            # Fallback: text-based
            if not link:
                link = driver.find_element(
                    By.XPATH,
                    "//a[contains(text(),'Internship Diary') and not(contains(text(),'Entries'))]"
                    " | //span[contains(text(),'Internship Diary') and not(contains(text(),'Entries'))]/parent::a"
                )
            link.click()
            time.sleep(3)
        except Exception as e:
            print(f"[VTU] ⚠️  Sidebar navigation failed: {e}")

    dismiss_popups(driver)
    print(f"[VTU] On page: {driver.current_url}")

    # ── Step 1: Select Internship (Radix UI combobox) ────────
    print("[VTU] Selecting internship...")
    try:
        # Click the combobox trigger
        trigger = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR,
             "#internship_id, button[role='combobox'][data-slot='select-trigger'],"
             " button[role='combobox']")
        ))
        trigger.click()
        print("[VTU] Dropdown opened, looking for option...")
        time.sleep(1.5)   # give portal time to render

        # Try 4 methods to click the first/only option
        clicked = False

        # Method 1: CSS role=option
        try:
            opt = driver.find_element(By.CSS_SELECTOR, "div[role='option']")
            driver.execute_script("arguments[0].click();", opt)
            clicked = True
            print("[VTU] ✅ Internship selected (method 1 - CSS).")
        except Exception:
            pass

        # Method 2: XPath by partial text
        if not clicked:
            try:
                opt = driver.find_element(
                    By.XPATH, "//div[contains(text(),'Android') or contains(text(),'internship') or contains(text(),'Internship')]"
                )
                driver.execute_script("arguments[0].click();", opt)
                clicked = True
                print("[VTU] ✅ Internship selected (method 2 - text).")
            except Exception:
                pass

        # Method 3: XPath generic option/listitem
        if not clicked:
            try:
                opt = driver.find_element(
                    By.XPATH, "//*[@role='option' or @role='menuitem'][1]"
                )
                driver.execute_script("arguments[0].click();", opt)
                clicked = True
                print("[VTU] ✅ Internship selected (method 3 - role).")
            except Exception:
                pass

        # Method 4: JS - find first visible dropdown item and click it
        if not clicked:
            result = driver.execute_script("""
                var opts = document.querySelectorAll('[role="option"], [role="menuitem"], li');
                for (var o of opts) {
                    if (o.offsetParent !== null) { o.click(); return o.innerText; }
                }
                return null;
            """)
            if result:
                clicked = True
                print(f"[VTU] ✅ Internship selected via JS: {result[:50]}")

        if not clicked:
            print("[VTU] ⚠️  Could not click internship option — continuing anyway.")

        time.sleep(0.5)
    except Exception as e:
        print(f"[VTU] ⚠️  Internship select: {e}")

    # ── Step 1: Pick Date ────────────────────────────────────
    pick_date(driver, wait, diary_date)

    # ── Step 1: Continue ─────────────────────────────────────
    try:
        continue_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(),'Continue')]")
        ))
        continue_btn.click()
        print("[VTU] ✅ Continue clicked.")
        time.sleep(2)
        dismiss_popups(driver)
    except Exception as e:
        print(f"[VTU] ⚠️  Continue button: {e}")

    # ── Step 2: Work Summary ─────────────────────────────────
    print("[VTU] Filling Work Summary...")
    try:
        ws = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR,
             "textarea[placeholder*='work you did'], textarea[placeholder*='Briefly']")
        ))
        ws.clear()
        ws.send_keys(summary[:1999])
        print("[VTU] ✅ Work Summary filled.")
    except Exception as e:
        print(f"[VTU] ⚠️  Work Summary: {e}")

    # ── Step 2: Hours Worked ─────────────────────────────────
    print(f"[VTU] Setting hours to {hours}...")
    try:
        hrs = driver.find_element(
            By.CSS_SELECTOR, "input[placeholder*='6.5'], input[type='number']"
        )
        hrs.clear()
        hrs.send_keys(str(hours))
        print(f"[VTU] ✅ Hours set: {hours}")
    except Exception as e:
        print(f"[VTU] ⚠️  Hours field: {e}")

    # ── Step 2: Learnings / Outcomes ────────────────────────
    print("[VTU] Filling Learnings/Outcomes...")
    try:
        lo = driver.find_element(
            By.CSS_SELECTOR,
            "textarea[placeholder*='learn'], textarea[placeholder*='ship today']"
        )
        lo.clear()
        lo.send_keys(learnings[:1999])
        print("[VTU] ✅ Learnings filled.")
    except Exception as e:
        print(f"[VTU] ⚠️  Learnings: {e}")

    # ── Step 2: Skills Used ──────────────────────────────────
    print(f"[VTU] Adding skills: {skills}")
    add_skills(driver, wait, skills)

    # ── Submit ───────────────────────────────────────────────
    is_test = "--test" in sys.argv
    if is_test:
        print("[VTU] 🧪 TEST MODE: Skipping final 'Submit' click.")
    else:
        print("[VTU] Submitting diary entry...")
        try:
            submit = wait.until(EC.element_to_be_clickable(
                (By.XPATH,
                 "//button[contains(text(),'Submit') or contains(text(),'Save')]")
            ))
            submit.click()
            time.sleep(2)
            dismiss_popups(driver)
            print("[VTU] ✅ Diary submitted!")
        except Exception as e:
            print(f"[VTU] ⚠️  Submit button: {e}")

# ── Entry point ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 54)
    print("  VTU Internship Diary — Auto Fill")
    print("=" * 54)

    driver = None
    try:
        driver = build_driver()
        if login(driver):
            fill_diary(driver)
            print()
            print("[VTU] Done! Check the portal to confirm the entry.")
            input("Press ENTER to close Chrome... ")
    except Exception as e:
        print(f"[VTU] Critical error: {e}")
        traceback.print_exc()
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
