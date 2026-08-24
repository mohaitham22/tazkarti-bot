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
"""

import os
import time
import json
import hashlib
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()  # reads .env in this folder, if present

TZK_URL = os.environ["TZK_URL"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

POLL_SECONDS = 30   # be reasonable -- this is someone else's server
STATE_FILE = "last_seen.json"


def fetch_al_ahly_matches(page) -> str:
    """
    Load the page, wait for JS to render, and return a snapshot of just
    the Al Ahly match listings, as "TeamA vs TeamB" lines.

    Built from the real markup: each match card is a ".team-names"
    element containing ".team-name.first" and ".team-name.second" divs
    with the two team names. We keep only cards where one side is Al
    Ahly (checks both "Al Ahly" and the Arabic "\u0627\u0644\u0623\u0647\u0644\u064a"),
    so the hash only changes when an Al Ahly fixture is added, removed,
    or its text changes -- not on every unrelated match on the page.
    """
    page.goto(TZK_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)  # give any lazy-loaded content a beat

    matches = page.evaluate("""
        () => {
            const cards = Array.from(document.querySelectorAll('.team-names'));
            const isAlAhly = (t) => /al\\s*ahly/i.test(t) || t.includes('\u0627\u0644\u0623\u0647\u0644\u064a');
            return cards
                .map(el => {
                    const first = el.querySelector('.team-name.first')?.innerText.trim() || '';
                    const second = el.querySelector('.team-name.second')?.innerText.trim() || '';
                    return first + ' vs ' + second;
                })
                .filter(m => isAlAhly(m));
        }
    """)
    return "\n".join(matches)


def load_last_hash():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("hash")
    return None


def save_last_hash(h: str):
    with open(STATE_FILE, "w") as f:
        json.dump({"hash": h}, f)


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
        if resp.status_code == 200:
            print("Telegram alert sent OK.")
        else:
            # This is the important part -- Telegram tells you exactly
            # what's wrong (bad token, bad chat id, bot never started, etc).
            print("Telegram alert FAILED:", resp.status_code, resp.text)
    except Exception as e:
        print("Telegram request errored:", e)


def main():
    print("Watching for Al Ahly ticket changes... (Ctrl+C to stop)")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        while True:
            try:
                content = fetch_al_ahly_matches(page)
                current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                last_hash = load_last_hash()

                if last_hash is not None and current_hash != last_hash:
                    print("Change detected \u2014 sending Telegram alert...")
                    detail = content if content else "(listing changed)"
                    send_telegram(
                        "\U0001F534 Al Ahly listing changed on Tazkarti:\n"
                        f"{detail}\n\n{TZK_URL}"
                    )

                save_last_hash(current_hash)

            except Exception as e:
                print("Check failed (will retry):", e)

            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()