"""
Al Ahly Tazkarti Ticket Check (single run, for GitHub Actions)
------------------------------------------------------------------
Checks Tazkarti ONCE, compares against the last known state (stored
in last_seen.json in this same repo), and sends a Telegram alert if
something changed. Then exits.

It doesn't loop or sleep -- the repeating happens via the GitHub
Actions schedule in .github/workflows/monitor.yml, which reruns this
script every ~10 minutes on GitHub's own servers. Your PC doesn't
need to be on for this to work.
"""

import os
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

TZK_URL = os.environ.get("TZK_URL", "https://www.tazkarti.com/#/matches")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "last_seen.json"


def fetch_al_ahly_matches(page) -> str:
    """Same approach as the local version: read rendered .team-names
    cards, keep only the ones mentioning Al Ahly."""
    page.goto(TZK_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    matches = page.evaluate("""
        () => {
            const cards = Array.from(document.querySelectorAll('.team-names'));
            const isAlAhly = (t) => /al\\s*ahly/i.test(t) || t.includes('الأهلي');
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
    resp = requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
    if resp.status_code == 200:
        print("Telegram alert sent OK.")
    else:
        print("Telegram alert FAILED:", resp.status_code, resp.text)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        content = fetch_al_ahly_matches(page)
        browser.close()

    current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    last_hash = load_last_hash()

    if last_hash is not None and current_hash != last_hash:
        detail = content if content else "(listing changed)"
        send_telegram(
            "\U0001F534 Al Ahly listing changed on Tazkarti:\n"
            f"{detail}\n\n{TZK_URL}"
        )
        print("Change detected -- alert sent.")
    else:
        print("No change.")

    save_last_hash(current_hash)


if __name__ == "__main__":
    main()
