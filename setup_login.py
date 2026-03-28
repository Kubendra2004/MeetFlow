"""
setup_login.py
Opens Chrome with the bot's profile so you can sign into Google.
Run this ONCE before using the bot for the first time.

Usage:
    python setup_login.py
"""
import os
import sys
import time
import undetected_chromedriver as uc

if sys.platform.startswith("linux"):
    PROFILE_DIR = os.path.abspath(os.path.join(os.getcwd(), "chrome_profile_linux"))
    # Chromium binary paths on Linux (in order of preference)
    CHROMIUM_PATHS = [
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        "/opt/chromium/chromium",
    ]
    CHROMIUM_BIN = next((p for p in CHROMIUM_PATHS if os.path.exists(p)), None)
else:
    PROFILE_DIR = os.path.abspath(os.path.join(os.getcwd(), "chrome_profile"))
    CHROMIUM_BIN = None

CHROME_VER  = 145

print("=" * 54)
print("  Google Meet Bot — One-Time Login Setup")
print("=" * 54)
print()
print("Chrome will open now.")
print()
print("Please do the following:")
print("  1. Sign into your Google account (top-right corner)")
print("  2. Go to: https://meet.google.com")
print("  3. Confirm you can see your meetings")
print("  4. Come back here and press ENTER to save and close.")
print()

# Ensure profile directory exists
os.makedirs(PROFILE_DIR, exist_ok=True)
print(f"[Setup] Using profile: {PROFILE_DIR}")

options = uc.ChromeOptions()
options.add_argument(f"--user-data-dir={PROFILE_DIR}")
options.add_argument("--use-fake-ui-for-media-stream")

# Use Chromium binary on Linux if detected
if sys.platform.startswith("linux") and CHROMIUM_BIN:
    print(f"[Setup] Using Chromium binary: {CHROMIUM_BIN}")
    driver = uc.Chrome(options=options, version_main=CHROME_VER, browser_executable_path=CHROMIUM_BIN)
else:
    driver = uc.Chrome(options=options, version_main=CHROME_VER)
driver.get("https://accounts.google.com")

input("Press ENTER here when you are signed in and ready to close Chrome... ")

driver.quit()
print()
print("✅ Login saved! You can now run the bot normally.")
print("   Double-click run_meet_joiner.bat or run:")
print("   python meet_joiner.py --now")
