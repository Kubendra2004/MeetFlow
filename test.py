import undetected_chromedriver as uc
import time

options = uc.ChromeOptions()
options.add_argument("--start-maximized")
options.add_argument("--window-position=0,0")

print("Starting Chrome...")
driver = uc.Chrome(options=options)
driver.get("https://www.google.com")

print("Chrome window should be visible and at (0,0).")
input("Check Chrome window and press Enter to close...")
driver.quit()
