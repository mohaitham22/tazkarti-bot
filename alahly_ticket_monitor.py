"""
Al Ahly Tazkarti Ticket Monitor (Playwright version)
-------------------------------------------------------
Watches a Tazkarti page and sends you a Telegram message the instant
something changes.

Tazkarti's site builds its match listings with JavaScript (note the
"#/" in its URLs -- that's a single-page app route, not a plain HTML
page), so this uses a real headless browser to read the page after it
finishes loading. A plain HTTP request would only ever see the empty
page shell and never detect real changes.

This script only READS a public page on a timer -- same as your browser
refreshing -- so it doesn't touch any private API or login. It does not
book or pay for anything.

Setup:
    pip install requests playwright python-dotenv
    (add --break-system-packages at the end if pip complains about an
    "externally managed environment")
    playwright install chromium

    Create a file named .env in this same folder (see .env.example)
    with your real TZK_URL / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.
    This script loads it automatically -- no more retyping env vars
    in every new terminal.

Environment variables:
    TZK_URL             - the Tazkarti page listing Al Ahly matches
                           e.g. https://www.tazkarti.com/#/matches
    TELEGRAM_BOT_TOKEN  - from @BotFather
    TELEGRAM_CHAT_ID    - from @userinfobot

Run:
    python alahly_ticket_monitor.py

Selector notes:
    Built from Tazkarti's real markup: match cards are ".team-names"
    elements containing ".team-name.first" / ".team-name.second". If
    Tazkarti changes their site's HTML later, re-inspect a match card
    in Chrome devtools and update the selectors inside
    fetch_al_ahly_matches() below.

    The listing is paginated: only the first page renders, and the rest
    arrives behind a "View More" button. load_all_pages() clicks it until
    the list is exhausted. Without that step this script sees roughly the
    first six fixtures and silently ignores the rest.

    The scraping logic here is kept byte-identical to
    alahly_ticket_check.py on purpose (rule 13).
"""

import os
import time
import json
import hashlib
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()  # reads .env in this folder, if present

TZK_URL = os.environ["TZK_URL"]
# An EMPTY value must fail exactly like a missing one -- an empty token
# produces a 404 from Telegram that is easy to mistake for a network blip.
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

POLL_SECONDS = 30   # be reasonable -- this is someone else's server
STATE_FILE = "last_seen.json"


class ScrapeError(RuntimeError):
    """The page did not render usable content."""


PAGE_SCRIPT = """
() => {
    const norm = (t) => (t || '')
        .replace(/[\\u0623\\u0625\\u0622\\u0671]/g, '\\u0627')  // أإآٱ -> ا
        .replace(/\\u0649/g, '\\u064A')                          // ى -> ي
        .replace(/[\\u064B-\\u0652]/g, '');                      // diacritics

    const cards = Array.from(document.querySelectorAll('.team-names'));

    const all = cards.map(el => {
        const first  = el.querySelector('.team-name.first')?.innerText.trim()  || '';
        const second = el.querySelector('.team-name.second')?.innerText.trim() || '';
        return (first + ' vs ' + second).trim();
    }).filter(m => m !== 'vs');

    const isAlAhly = (t) => /al\\s*ahly/i.test(t) || norm(t).includes('\\u0627\\u0644\\u0627\\u0647\\u0644\\u064A');

    return { total: all.length, alAhly: all.filter(isAlAhly) };
}
"""


# --------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------
# Tazkarti renders only the first page of fixtures and appends the rest
# behind a "View More" button. A scrape that never clicks it sees page 1
# and nothing else -- which is how a live "ZED FC vs Al Ahly FC" sat
# unnoticed on page 2 while the monitor reported 0 Al Ahly fixtures.
#
# Re-derive from devtools: the control is
#     button.button.button-blue.width-auto     text "View More"
# and it reports disabled once the whole list is loaded. Selecting it by
# class rather than by text keeps this working if the site is served in
# Arabic; :not(.filter-toggle) is required because the two Search buttons
# share button-blue and width-auto.
LOAD_MORE_SELECTOR = "button.button-blue.width-auto:not(.filter-toggle)"
LOAD_MORE_MAX_CLICKS = 20    # ~4-6 fixtures per page, so 20 covers a season
LOAD_MORE_WAIT_MS = 2000     # give Angular time to append the next page


def count_match_cards(page) -> int:
    return page.evaluate("() => document.querySelectorAll('.team-names').length")


def load_all_pages(page) -> int:
    """Click "View More" until the entire fixture list is in the DOM.

    Returns the number of clicks used. Raises ScrapeError if the button is
    still live afterwards: at that point we cannot prove we have seen the
    whole listing, and reporting a partial scrape as a complete one is
    exactly the bug this function exists to fix.
    """
    clicks = 0
    while clicks < LOAD_MORE_MAX_CLICKS:
        button = page.query_selector(LOAD_MORE_SELECTOR)
        if button is None or not button.is_enabled():
            return clicks

        before = count_match_cards(page)
        button.click()
        page.wait_for_timeout(LOAD_MORE_WAIT_MS)
        clicks += 1

        if count_match_cards(page) == before:
            # Button still present but nothing new arrived. Treat the list
            # as finished rather than clicking forever.
            return clicks

    button = page.query_selector(LOAD_MORE_SELECTOR)
    if button is not None and button.is_enabled():
        raise ScrapeError(
            f"'View More' was still active after {LOAD_MORE_MAX_CLICKS} clicks. "
            "Refusing to report a partial listing as if it were complete."
        )
    return clicks


def fetch_al_ahly_matches(page) -> list:
    """Return the sorted list of Al Ahly fixtures, or raise ScrapeError.

    Deliberately identical to alahly_ticket_check.py per rule 13. This
    script is the reference implementation, so any divergence here destroys
    its only purpose: telling "the code is wrong" apart from "the CI
    environment is different".
    """
    page.goto(TZK_URL, wait_until="domcontentloaded", timeout=45000)

    # wait_for_selector, never networkidle + a fixed sleep: on an SPA
    # networkidle can resolve before Angular paints (rule 7).
    try:
        page.wait_for_selector(".team-names", timeout=25000)
    except PlaywrightTimeout:
        raise ScrapeError(
            ".team-names never appeared within 25s. The page did not render "
            "match cards -- likely blocked, geo-restricted, or the markup changed."
        )

    # Load every page BEFORE parsing, or the scrape silently covers only
    # the first one.
    clicks = load_all_pages(page)

    result = page.evaluate(PAGE_SCRIPT)
    total = result["total"]
    al_ahly = result["alAhly"]

    if total == 0:
        raise ScrapeError("Selector matched but zero match cards parsed.")

    print(f"Parsed {total} match cards after {clicks} 'View More' click(s), "
          f"{len(al_ahly)} of them Al Ahly.")
    # Sorted so a mere reordering of the listing doesn't look like a change.
    return sorted(al_ahly)


def load_last_hash():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("hash")
    return None


def save_last_hash(h: str):
    with open(STATE_FILE, "w") as f:
        json.dump({"hash": h}, f)


def send_telegram(message: str) -> bool:
    """Returns True ONLY if Telegram accepted the message."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
        if resp.status_code == 200:
            print("Telegram alert sent OK.")
            return True
        else:
            # This is the important part -- Telegram tells you exactly
            # what's wrong (bad token, bad chat id, bot never started, etc).
            print("Telegram alert FAILED:", resp.status_code, resp.text)
            return False
    except Exception as e:
        print("Telegram request errored:", e)
        return False


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are empty or unset -- "
            "check your .env file."
        )

    print("Watching for Al Ahly ticket changes... (Ctrl+C to stop)")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        while True:
            try:
                matches = fetch_al_ahly_matches(page)
                content = "\n".join(matches)
                current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                last_hash = load_last_hash()

                delivered = True
                if last_hash is not None and current_hash != last_hash:
                    print("Change detected \u2014 sending Telegram alert...")
                    detail = content if content else "(listing changed)"
                    delivered = send_telegram(
                        "\U0001F534 Al Ahly listing changed on Tazkarti:\n"
                        f"{detail}\n\n{TZK_URL}"
                    )

                # Only advance the baseline once the alert is actually out.
                # Saving after a failed send makes the next poll report no
                # change, and the alert is lost for good.
                if delivered:
                    save_last_hash(current_hash)
                else:
                    print("Alert undelivered -- baseline kept so the next "
                          "poll retries.")

            except Exception as e:
                print("Check failed (will retry):", e)

            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()