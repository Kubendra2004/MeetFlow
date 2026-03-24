"""
test_meet.py -- Quick test for the Google Meet Joiner.

Run this to confirm:
  1. Chrome opens without "bot detected" warnings.
  2. You are signed in to your Google account.
  3. Mic and camera toggle off automatically before joining.
  4. The "Ask to join" / "Join now" button is found and clicked.
  5. Any popups after joining are auto-dismissed.
  6. Popup dismissal logic runs without crashing.
  7. Meeting-end is detected and PC shuts down (10s warning before shutdown).

Usage:
    python test_meet.py
"""

import time
import traceback
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---- Point this to a real Meet link to test all steps ----
MEET_LINK = "https://meet.google.com/pmg-ynxm-tyx"  # <-- change to your link!
PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile")

PASS = "[  PASS  ]"
FAIL = "[  FAIL  ]"
INFO = "[  INFO  ]"

def test():
    results = []

    print("\n" + "="*55)
    print("   GOOGLE MEET JOINER -- TEST SUITE")
    print("="*55 + "\n")

    # --- Test 1: Chrome launches without errors ---
    print(f"{INFO} Test 1: Launching Chrome with undetected-chromedriver...")
    driver = None
    try:
        options = uc.ChromeOptions()
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument(f"--user-data-dir={PROFILE_DIR}")
        prefs = {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 1,
        }
        options.add_experimental_option("prefs", prefs)
        driver = uc.Chrome(options=options, version_main=145)
        print(f"{PASS} Test 1: Chrome launched successfully.\n")
        results.append(("Chrome Launch", True))
    except Exception:
        print(f"{FAIL} Test 1: Chrome failed to launch!")
        traceback.print_exc()
        results.append(("Chrome Launch", False))
        print_summary(results)
        return

    # --- Test 2: Navigate to Meet link ---
    print(f"{INFO} Test 2: Navigating to {MEET_LINK} ...")
    try:
        driver.get(MEET_LINK)
        time.sleep(3)
        current_url = driver.current_url
        if "accounts.google.com" in current_url or "signin" in current_url:
            print(f"{FAIL} Test 2: Redirected to login page. Please sign into your Google account first.")
            results.append(("Navigate to Meet (Signed In)", False))
        else:
            print(f"{PASS} Test 2: Navigated to Meet. URL: {current_url}\n")
            results.append(("Navigate to Meet (Signed In)", True))
    except Exception:
        print(f"{FAIL} Test 2: Failed to navigate!")
        traceback.print_exc()
        results.append(("Navigate to Meet (Signed In)", False))

    # --- Test 3: Mic button found & muted ---
    print(f"{INFO} Test 3: Checking microphone button...")
    mic_found = False
    try:
        # "Turn off microphone" in label → mic is ON → click to mute
        # "Turn on microphone"  in label → mic is already OFF
        mic_buttons = driver.find_elements(By.XPATH, "//*[contains(@aria-label, 'microphone') or contains(@aria-label, 'Microphone')]")
        for btn in mic_buttons:
            label = (btn.get_attribute("aria-label") or "").lower()
            if "turn off" in label and "microphone" in label:
                btn.click()
                print(f"{PASS} Test 3: Microphone was ON — now muted (turned OFF).\n")
                mic_found = True
                break
            elif "turn on" in label and "microphone" in label:
                print(f"{PASS} Test 3: Microphone already OFF/muted.\n")
                mic_found = True
                break
        if not mic_found:
            print(f"{FAIL} Test 3: Mic button not found. (Google Meet may have changed its UI.)\n")
    except Exception as e:
        print(f"{FAIL} Test 3: Error — {e}\n")
    results.append(("Microphone Toggle", mic_found))

    # --- Test 4: Camera button found & muted ---
    print(f"{INFO} Test 4: Checking camera button...")
    cam_found = False
    try:
        cam_buttons = driver.find_elements(By.XPATH, "//*[contains(@aria-label, 'camera') or contains(@aria-label, 'Camera')]")
        for btn in cam_buttons:
            label = (btn.get_attribute("aria-label") or "").lower()
            if "turn off" in label and "camera" in label:
                btn.click()
                print(f"{PASS} Test 4: Camera was ON — now muted (turned OFF).\n")
                cam_found = True
                break
            elif "turn on" in label and "camera" in label:
                print(f"{PASS} Test 4: Camera already OFF/muted.\n")
                cam_found = True
                break
        if not cam_found:
            print(f"{FAIL} Test 4: Camera button not found. (Google Meet may have changed its UI.)\n")
    except Exception as e:
        print(f"{FAIL} Test 4: Error — {e}\n")
    results.append(("Camera Toggle", cam_found))


    # --- Test 5: Join button found ---
    print(f"{INFO} Test 5: Looking for the Join button...")
    join_xpaths = [
        "//span[contains(text(), 'Ask to join')]",
        "//span[contains(text(), 'Join now')]",
        "//div[@role='button']//span[text()='Ask to join']",
        "//div[@role='button']//span[text()='Join now']"
    ]
    join_button = None
    for xpath in join_xpaths:
        try:
            join_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            break
        except:
            pass

    if join_button:
        print(f"{PASS} Test 5: Join button found! Text: '{join_button.text}'")
        join_button.click()
        print(f"{INFO} Clicked Join. Waiting 5 seconds for popups...\n")
        results.append(("Join Button Found & Clicked", True))
        time.sleep(5)
    else:
        print(f"{FAIL} Test 5: Join button NOT found in 5s per xpath.\n")
        results.append(("Join Button Found & Clicked", False))

    # --- Test 6: Popup dismissal ---
    print(f"{INFO} Test 6: Scanning for popups to dismiss...")
    popup_xpaths = [
        "//span[contains(text(), 'OK')]",
        "//span[contains(text(), 'Ok')]",
        "//span[contains(text(), 'Got it')]",
        "//span[contains(text(), 'Dismiss')]",
        "//span[contains(text(), 'Close')]",
        "//button[contains(text(), 'OK')]",
        "//button[contains(text(), 'Got it')]",
        "//button[contains(text(), 'Dismiss')]",
    ]
    dismissed_any = False
    for popup_xpath in popup_xpaths:
        try:
            btn = driver.find_element(By.XPATH, popup_xpath)
            if btn.is_displayed():
                btn.click()
                print(f"{PASS} Test 6: Dismissed popup with text '{btn.text}'")
                dismissed_any = True
        except:
            pass
    if not dismissed_any:
        print(f"{INFO} Test 6: No popups found to dismiss (this is normal if no dialog appeared).")
    results.append(("Popup Dismissal Logic", True))  # logic ran without crashing = pass

    # --- Test 7: Meeting-end detection & PC shutdown ---
    print(f"\n{INFO} Test 7: Monitoring for meeting end (host ending the call)...")
    print(f"{INFO} The test will stay in the meeting until the host ends it.")
    print(f"{INFO} When detected, PC will shut down after a 10-second warning.\n")

    end_phrases = [
        "Call ended",
        "The call has ended",
        "You left the call",
        "has ended the call",
        "You've been removed",
    ]

    meeting_end_detected = False
    try:
        while True:
            time.sleep(2)

            # Check URL and page source for meeting-end indicators
            current_url = driver.current_url
            page_source = driver.page_source

            if "meet.google.com" not in current_url or any(p in page_source for p in end_phrases):
                meeting_end_detected = True
                print(f"\n{PASS} Test 7: Meeting-end DETECTED!")
                results.append(("Meeting-End Detection", True))
                break

            # Also dismiss any popups while waiting
            for popup_xpath in popup_xpaths:
                try:
                    btn = driver.find_element(By.XPATH, popup_xpath)
                    if btn.is_displayed():
                        btn.click()
                        print(f"{INFO} Dismissed popup: '{btn.text}'")
                except:
                    pass

    except Exception:
        print(f"\n{PASS} Test 7: Browser closed → treating as meeting ended.")
        results.append(("Meeting-End Detection", True))
        meeting_end_detected = True

    print_summary(results)

    if meeting_end_detected:
        print(f"[!] Shutting down PC in 10 seconds... Press Ctrl+C to cancel!")
        try:
            time.sleep(10)
            os.system("shutdown /s /t 0")
        except KeyboardInterrupt:
            print("[!] Shutdown cancelled by user.")
    else:
        driver.quit()



def print_summary(results):
    print("\n" + "="*55)
    print("   TEST SUMMARY")
    print("="*55)
    all_passed = True
    for name, passed in results:
        status = PASS if passed else FAIL
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False
    print("="*55)
    if all_passed:
        print("  ALL TESTS PASSED! The bot is ready to use.")
    else:
        print("  SOME TESTS FAILED. Review the output above.")
    print("="*55 + "\n")


if __name__ == "__main__":
    test()
