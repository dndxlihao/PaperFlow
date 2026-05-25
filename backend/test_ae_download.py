"""
Test: Extract article full text from ScienceDirect.

Strategy: 
1. Launch Chrome with remote debugging enabled (user's profile)
2. User can manually pass Cloudflare if needed
3. Then script scrapes article text

Usage:
  Step 1: Close Chrome completely
  Step 2: Run this script - it will open Chrome with debugging
  Step 3: If Cloudflare appears, solve it manually in the browser
  Step 4: Script will wait and then scrape text
"""
import os
import time
import subprocess
import sys

# --- Step 1: Launch Chrome with remote debugging ---
chrome_app = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
chrome_user_data = os.path.expanduser("~/Library/Application Support/Google/Chrome")
debug_port = 9222

doi_url = "https://doi.org/10.1016/j.apenergy.2026.127785"

print("Launching Chrome with remote debugging on port 9222...")
print("If Cloudflare challenge appears, please solve it manually.")
print()

# Launch Chrome in background
chrome_proc = subprocess.Popen([
    chrome_app,
    f"--remote-debugging-port={debug_port}",
    f"--user-data-dir={chrome_user_data}",
    "--profile-directory=Default",
    doi_url,
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

print("Chrome launched. Waiting 15 seconds for page to load...")
print("If Cloudflare challenge appears, solve it in the browser window.")
time.sleep(15)

# --- Step 2: Connect to Chrome via Selenium ---
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")

try:
    driver = webdriver.Chrome(options=opts)
except Exception as e:
    print(f"Cannot connect to Chrome: {e}")
    chrome_proc.terminate()
    exit(1)

print(f"Connected! Current URL: {driver.current_url[:100]}")
print(f"Title: {driver.title[:80]}")

# If still on Cloudflare, wait for user to solve it
if "just a moment" in driver.title.lower() or "cloudflare" in driver.page_source.lower()[:5000]:
    print("\n⚠️  Cloudflare challenge detected. Please solve it in the browser.")
    print("Waiting up to 120 seconds...")
    for i in range(60):
        time.sleep(2)
        if "just a moment" not in driver.title.lower():
            print("Cloudflare passed!")
            time.sleep(3)
            break
    else:
        print("Timeout waiting for Cloudflare.")
        driver.quit()
        chrome_proc.terminate()
        exit(1)

print(f"\nPage loaded: {driver.current_url[:100]}")
print(f"Title: {driver.title[:80]}")

# --- Step 3: Extract article text ---
abstract = ""
try:
    abstract_el = driver.find_element(By.CSS_SELECTOR, "div.abstract.author div")
    abstract = abstract_el.text.strip()
except:
    try:
        abstract_el = driver.find_element(By.ID, "abstracts")
        abstract = abstract_el.text.strip()
    except:
        pass

if abstract:
    print(f"\n=== ABSTRACT ({len(abstract)} chars) ===")
    print(abstract[:500])
else:
    print("No abstract found via CSS selectors")

# Full text
full_text = ""
for sel in ["div#body", "div.Body", "article", "div[id='body']"]:
    try:
        body_el = driver.find_element(By.CSS_SELECTOR, sel)
        full_text = body_el.text.strip()
        if len(full_text) > 500:
            print(f"\nFound body via '{sel}': {len(full_text)} chars")
            break
    except:
        continue

if not full_text or len(full_text) < 500:
    try:
        sections = driver.find_elements(By.CSS_SELECTOR, "section")
        texts = [s.text.strip() for s in sections if s.text.strip()]
        full_text = "\n\n".join(texts)
        print(f"\nFound via sections: {len(full_text)} chars from {len(texts)} sections")
    except:
        pass

if full_text and len(full_text) > 200:
    print(f"\n=== FULL TEXT ({len(full_text)} chars) ===")
    print(full_text[:1000])
    print("\n... [truncated] ...")
    
    out_path = os.path.join("/Users/lihao/Desktop/wechat/docs", "test_ae_text.txt")
    with open(out_path, "w") as f:
        f.write(f"ABSTRACT:\n{abstract}\n\nFULL TEXT:\n{full_text}")
    print(f"\nSaved to: {out_path}")
    print("SUCCESS!")
else:
    print(f"\nFull text too short or not found ({len(full_text)} chars)")
    src = driver.page_source
    print(f"Page source length: {len(src)}")

# Don't quit Chrome - leave it open for user
print("\nDone. Chrome left open.")
