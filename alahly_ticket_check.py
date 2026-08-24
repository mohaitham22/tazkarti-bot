"""
Al Ahly Tazkarti Ticket Check (single run, for GitHub Actions)
------------------------------------------------------------------
Checks Tazkarti ONCE, compares against the last known state
(last_seen.json in this repo), and sends a Telegram alert if the
Al Ahly listing changed. Then exits.

Key difference from the first version: this one can tell the
difference between "no Al Ahly matches listed" and "the scrape
broke". The old version produced an empty string in both cases,
which hashed identically to the stored baseline -- so a broken
scraper reported "No change." forever while the job stayed green.

How it distinguishes them: it counts EVERY match card on the page,
not just the Al Ahly ones.
    - 0 cards total          -> page never rendered. Something is
                                wrong (blocked, geo-restricted,
                                markup changed). Alert + exit 1.
    - N cards, 0 Al Ahly     -> genuinely no Al Ahly fixtures. Quiet.

On failure it does NOT overwrite the stored hash, so a temporary
block can't destroy a good baseline and cause a bogus "change"
alert when it recovers.
"""

import os
import sys
import json
import hashlib
import datetime
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

TZK_URL = os.environ.get("TZK_URL", "https://www.tazkarti.com/#/matches")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = "last_seen.json"
DEBUG_DIR = "debug"

# Re-alert about a persistent failure every N runs so you get one
# nudge per hour at a 10-minute cadence, not one every 10 minutes.
FAILURE_REALERT_EVERY = 6

# A real browser UA. Headless Chromium's default UA contains
# "HeadlessChrome", which is the single easiest bot signal to filter on.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


class ScrapeError(RuntimeError):
    """The page did not render usable content."""


# --------------------------------------------------------------------
# state
# --------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


# --------------------------------------------------------------------
# scraping
# --------------------------------------------------------------------

# Arabic normalisation: Tazkarti may render "الأهلي" or "الاهلي" or
# "الأهلى" depending on the data source. Strip hamza forms and
# diacritics, and fold alef-maqsura to yaa, before comparing.
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


def dump_evidence(page, tag: str) -> None:
    """Save a screenshot + HTML so a headless failure is debuggable."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        page.screenshot(path=os.path.join(DEBUG_DIR, f"{tag}.png"), full_page=True)
        with open(os.path.join(DEBUG_DIR, f"{tag}.html"), "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"Saved debug evidence to {DEBUG_DIR}/{tag}.[png|html]")
    except Exception as e:  # never let debug capture mask the real error
        print("Could not save debug evidence:", e)


def fetch_al_ahly_matches(page) -> list:
    """Return the sorted list of Al Ahly fixtures, or raise ScrapeError."""
    page.goto(TZK_URL, wait_until="domcontentloaded", timeout=45000)

    try:
        page.wait_for_selector(".team-names", timeout=25000)
    except PlaywrightTimeout:
        dump_evidence(page, "no-selector")
        raise ScrapeError(
            ".team-names never appeared within 25s. The page did not render "
            "match cards -- likely blocked, geo-restricted, or the markup changed."
        )

    result = page.evaluate(PAGE_SCRIPT)
    total = result["total"]
    al_ahly = result["alAhly"]

    if total == 0:
        dump_evidence(page, "zero-cards")
        raise ScrapeError("Selector matched but zero match cards parsed.")

    print(f"Parsed {total} match cards, {len(al_ahly)} of them Al Ahly.")
    # Sorted so a mere reordering of the listing doesn't look like a change.
    return sorted(al_ahly)


# --------------------------------------------------------------------
# telegram
# --------------------------------------------------------------------

def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url, data={"chat_id": CHAT_ID, "text": message}, timeout=15
        )
        if resp.status_code == 200:
            print("Telegram alert sent OK.")
        else:
            print("Telegram alert FAILED:", resp.status_code, resp.text)
    except Exception as e:
        print("Telegram request errored:", e)


def describe_change(old: list, new: list) -> str:
    added = [m for m in new if m not in old]
    removed = [m for m in old if m not in new]
    lines = []
    if added:
        lines.append("NEW:\n" + "\n".join(f"  + {m}" for m in added))
    if removed:
        lines.append("GONE:\n" + "\n".join(f"  - {m}" for m in removed))
    if not lines:
        lines.append("Listing text changed (same fixtures).")
    return "\n\n".join(lines)


# --------------------------------------------------------------------
# main
# --------------------------------------------------------------------

def main() -> int:
    state = load_state()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ar-EG",
            timezone_id="Africa/Cairo",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        try:
            matches = fetch_al_ahly_matches(page)
        except ScrapeError as e:
            fails = state.get("consecutive_failures", 0) + 1
            state["consecutive_failures"] = fails
            state["last_error"] = str(e)
            save_state(state)          # note: hash / matches left untouched
            browser.close()

            print("SCRAPE FAILED:", e)
            if fails == 1 or fails % FAILURE_REALERT_EVERY == 0:
                send_telegram(
                    f"\u26A0\uFE0F Tazkarti monitor is not working "
                    f"(failure #{fails}).\n\n{e}\n\nNo ticket alerts will "
                    f"arrive until this is fixed.\n{TZK_URL}"
                )
            return 1
        finally:
            if browser.is_connected():
                browser.close()

    content = "\n".join(matches)
    current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    last_hash = state.get("hash")
    last_matches = state.get("matches", [])

    recovered = state.get("consecutive_failures", 0) > 0

    if last_hash is None:
        print(f"Baseline established ({len(matches)} Al Ahly fixtures).")
    elif current_hash != last_hash:
        send_telegram(
            "\U0001F534 Al Ahly listing changed on Tazkarti:\n\n"
            f"{describe_change(last_matches, matches)}\n\n{TZK_URL}"
        )
        print("Change detected -- alert sent.")
    else:
        print("No change.")

    if recovered:
        print("Scraper recovered after "
              f"{state['consecutive_failures']} failed run(s).")

    save_state({
        "hash": current_hash,
        "matches": matches,
        "consecutive_failures": 0,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())