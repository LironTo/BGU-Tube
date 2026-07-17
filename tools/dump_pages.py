# Dumps the rendered HTML of Moodle pages exactly as UI.py's Playwright session
# sees them, into page_dumps/ (git-ignored - the dumps contain personal data).
#
# Usage:
#   python tools/dump_pages.py                  -> login page + profile page
#   python tools/dump_pages.py 12345 67890      -> also videoslist of these course ids
#   python tools/dump_pages.py <full-url>       -> also that exact URL
import asyncio
import os
import re
import sys

from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from Media.LoginInfo import USERNAME, PASSWORD

MOODLE_LOGIN_URL = "https://moodle.bgu.ac.il/moodle/login/index.php"
PROFILE_URL = "https://moodle.bgu.ac.il/moodle/user/profile.php"
DUMP_DIR = os.path.join(BASE_DIR, "page_dumps")


async def dump(page, name):
    os.makedirs(DUMP_DIR, exist_ok=True)
    path = os.path.join(DUMP_DIR, f"{name}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(await page.content())
    print(f"[INFO] Saved {page.url} -> {path}")


async def main():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    await page.goto(MOODLE_LOGIN_URL)
    await dump(page, "login")

    await page.fill('#username', USERNAME)
    await page.fill('#password', PASSWORD)
    await page.click('#loginbtn')
    await page.wait_for_timeout(3000)
    print(f"[INFO] After login: {page.url}")

    await page.goto(PROFILE_URL)
    await page.wait_for_timeout(2000)
    await dump(page, "profile")

    for arg in sys.argv[1:]:
        if arg.isdigit():
            url = f"https://moodle.bgu.ac.il/moodle/blocks/video/videoslist.php?courseid={arg}"
            name = f"videoslist_{arg}"
        else:
            url = arg
            name = re.sub(r'[\\/*?:"<>|=&.]+', "_", arg.split("//")[-1])[:80]
        await page.goto(url)
        await page.wait_for_timeout(2000)
        await dump(page, name)

    await browser.close()
    await playwright.stop()


asyncio.run(main())
