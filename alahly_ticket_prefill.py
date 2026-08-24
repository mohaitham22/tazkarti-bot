"""
Al Ahly Tazkarti Pre-fill Helper
----------------------------------
Run this AFTER alahly_ticket_monitor.py alerts you. It logs into your
Tazkarti account, opens the match page, and selects your usual seat
category + quantity for you -- then STOPS.

What this does NOT do, on purpose:
    - It will not click the final "Pay" / "Confirm" button.
    - It will not try to solve or bypass any CAPTCHA.
    Both of those need to be you: most ticket platforms' terms of
    service prohibit automated purchasing, and a CAPTCHA on a checkout
    page exists specifically to require a human at that step. This
    script gets you to "one click away" and hands control back to you.

Setup:
    pip install playwright python-dotenv
    (add --break-system-packages at the end if pip complains about an
    "externally managed environment")
    playwright install chromium

    Uses the same .env file as alahly_ticket_monitor.py -- add
    TZK_USERNAME / TZK_PASSWORD / TZK_MATCH_URL to it (see .env.example).

    Environment variables:
        TZK_USERNAME     - your Tazkarti account username/email
        TZK_PASSWORD     - your Tazkarti account password
        TZK_MATCH_URL    - the specific match's ticket page (update this
                            once you know the actual match, from the
                            monitor's alert)
        TZK_SEAT_CATEGORY (optional) - default "First Class"
        TZK_QUANTITY      (optional) - default "1"

Before running for real:
    Log into Tazkarti yourself once in a normal browser, open dev tools
    (F12), and find the real element IDs/selectors for the login form,
    seat-category dropdown, quantity field, and add-to-cart button.
    Replace every "TODO" selector below with the real one.
"""

import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()  # reads .env in this folder, if present

TZK_USERNAME = os.environ["TZK_USERNAME"]
TZK_PASSWORD = os.environ["TZK_PASSWORD"]
MATCH_URL = os.environ["TZK_MATCH_URL"]
SEAT_CATEGORY = os.environ.get("TZK_SEAT_CATEGORY", "First Class")
QUANTITY = os.environ.get("TZK_QUANTITY", "1")


def main():
    with sync_playwright() as p:
        # headless=False so the browser window is visible -- you take
        # over in this exact window once it's done pre-filling.
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # --- Log in --- TODO: replace with Tazkarti's real selectors
        page.goto("https://tazkarti.com/login")
        page.fill("#username", TZK_USERNAME)      # TODO
        page.fill("#password", TZK_PASSWORD)      # TODO
        page.click("#login-button")               # TODO
        page.wait_for_load_state("networkidle")

        # --- Open the match and pick seats --- TODO: replace selectors
        page.goto(MATCH_URL)
        page.select_option("#seat-category", label=SEAT_CATEGORY)  # TODO
        page.fill("#quantity", QUANTITY)                            # TODO
        page.click("#add-to-cart")                                  # TODO

        page.wait_for_load_state("networkidle")
        print("Cart is ready in the browser window.")
        print("Switch over, review it, and complete payment yourself.")
        input("Press Enter here once you're done (keeps this open until then)...")

        browser.close()


if __name__ == "__main__":
    main()