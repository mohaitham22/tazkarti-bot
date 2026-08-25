"""
Al Ahly Tazkarti Ticket Monitor (Playwright version)
-------------------------------------------------------
Watches a Tazkarti page in a loop and sends you a Telegram message the
instant an Al Ahly fixture's ticket availability changes.

Tazkarti's site builds its match listings with JavaScript (note the
"#/" in its URLs -- that's a single-page app route, not a plain HTML
page), so this uses a real headless browser to read the page after it
finishes loading. A plain HTTP request would only ever see the empty
page shell and never detect real changes.

This script only READS a public page on a timer -- same as your browser
refreshing -- so it doesn't touch any private API or login. It does not
book or pay for anything.

Why this file exists alongside alahly_ticket_check.py: it is the
reference implementation. When the CI version misbehaves, run this one
to find out whether the problem is the code or the environment. That is
only worth anything if the scraping logic is genuinely the same in both,
so everything between the SHARED SCRAPE BLOCK markers below is
byte-identical to alahly_ticket_check.py and is copied across
mechanically by sync_shared_block.py. Never edit it here.

Setup:
    pip install requests playwright python-dotenv
    (add --break-system-packages at the end if pip complains about an
    "externally managed environment")
    playwright install chromium

    Create a file named .env in this same folder (see env.example)
    with your real TZK_URL / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.
    This script loads it automatically -- no more retyping env vars
    in every new terminal.

Environment variables:
    TZK_URL             - the Tazkarti page listing Al Ahly matches
                           e.g. https://www.tazkarti.com/#/matches
                           (the full route, NOT just the homepage -- a
                           truncated value renders no match cards at all)
    TELEGRAM_BOT_TOKEN  - from @BotFather
    TELEGRAM_CHAT_ID    - from get_telegram_chat_id.py

Run:
    python alahly_ticket_monitor.py
"""

import os
import re
import time
import json
import hashlib
import datetime
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

# Same browser identity as CI, so that a difference in results is a real
# difference and not an artefact of the two scripts looking different to
# the server.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


# ====================================================================
# BEGIN SHARED SCRAPE BLOCK (rule 13)
# Byte-identical in alahly_ticket_check.py and alahly_ticket_monitor.py.
# Never edit one copy by hand -- edit the copy in alahly_ticket_check.py
# and then run
#     python sync_shared_block.py
# which copies it across and verifies the two are identical. Hand-copying
# is how these two files drifted apart in the first place.
# ====================================================================

STATE_FILE = "last_seen.json"
DEBUG_DIR = "debug"


class ScrapeError(RuntimeError):
    """The page did not render usable content."""


# --------------------------------------------------------------------
# status vocabulary
# --------------------------------------------------------------------
# Read out of Tazkarti's own compiled Angular bundle (8.*.js) on
# 2026-08-25, not guessed. The match card template is:
#
#   <div class="status" [class.green]="matchStatus==1"
#                       [class.red]="matchStatus==2||==3||==4">
#     {{ matchStatus==1 ? 'Available'   : matchStatus==2 ? 'NotAvailable'
#      : matchStatus==3 ? 'FullBooking' : 'MatchComingSoon' | translate }}
#   </div>
#
# and those i18n keys resolve through assets/i18n/{en,ar,fr}.json to:
#
#   raw  key              en               ar                fr
#   1    Available        Available        (matah)           Disponible
#   2    NotAvailable     Match Ended      (intahat...)      Match termine
#   3    FullBooking      Booking Closed   (tam ghalq...)    Reservation fermee
#   4    MatchComingSoon  Coming Soon      (qariban)         Bientot disponible
#
# These labels are for WORDING ALERTS ONLY. Change detection runs on the
# raw integer -- see match_payload().
STATUS_AVAILABLE = 1
STATUS_LABELS = {
    1: "AVAILABLE",
    2: "MATCH_ENDED",
    3: "BOOKING_CLOSED",
    4: "COMING_SOON",
}


def status_label(raw) -> str:
    """Human token for a raw matchStatus. Never used for change detection."""
    return STATUS_LABELS.get(raw, f"UNKNOWN_STATUS_{raw}")


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
# Arabic normalisation (rule 6)
# --------------------------------------------------------------------
# The hamza forms of alef and the two yaa forms are interchangeable in
# Tazkarti's data depending on the source, so fold them and strip
# diacritics before comparing team names.
_ARABIC_FOLD = {
    0x0623: "ا", 0x0625: "ا", 0x0622: "ا", 0x0671: "ا",
    0x0649: "ي",
}
_AL_AHLY_AR = "الاهلي"   # "al-ahly", normalised


def normalise_arabic(text: str) -> str:
    folded = (text or "").translate(_ARABIC_FOLD)
    return "".join(c for c in folded if not "ً" <= c <= "ْ")


def is_al_ahly(text: str) -> bool:
    return bool(re.search(r"al\s*ahly", text or "", re.I)) or \
        _AL_AHLY_AR in normalise_arabic(text)


# --------------------------------------------------------------------
# which fixtures are ours
# --------------------------------------------------------------------
# Al Ahly FC is teamId 77 in Tazkarti's feed. Matching on the id is exact
# and survives both a rename and the site being served in another
# language. Re-derive by fetching /data/matches-list-json.json and
# reading teamId1 / teamId2 off a fixture you know is Al Ahly's.
AL_AHLY_TEAM_ID = 77

# Clubs whose NAME matches an "al ahly" test but which are not Al Ahly
# FC. This is not a nicety: NBE Club is "نادى البنك الاهلى المصرى" --
# the National Bank of Egypt -- and "الاهلى" is simply the Arabic word
# for "national". Without this, every NBE fixture is tracked as an Al
# Ahly one. Found when the name test started reading Arabic names and
# quietly returned two fixtures where there was one.
DECOY_TEAM_IDS = {
    171: "NBE Club -- National Bank of Egypt, not Al Ahly FC",
}


def is_al_ahly_row(row: dict) -> bool:
    """Is this feed row an Al Ahly fixture?

    Team id first, because it is exact. The name test is kept as a
    fallback so that a reissued team id leaves the monitor noisy rather
    than silent -- silence is the failure this project keeps having, and
    a spurious extra fixture is both visible and trivially fixed by
    adding its id to DECOY_TEAM_IDS.

    The fallback runs per side, skipping only the decoy team itself
    rather than rejecting the whole fixture, so an Al Ahly match against
    NBE is still caught even if Al Ahly's own id changed.
    """
    if AL_AHLY_TEAM_ID in (row.get("teamId1"), row.get("teamId2")):
        return True

    for id_key, name_keys in (
        ("teamId1", ("teamName1", "teamNameAr1")),
        ("teamId2", ("teamName2", "teamNameAr2")),
    ):
        if row.get(id_key) in DECOY_TEAM_IDS:
            continue
        if any(is_al_ahly(str(row.get(k) or "")) for k in name_keys):
            return True
    return False


# --------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------

def match_payload(m: dict) -> str:
    """The exact bytes change detection runs on.

    Identity plus the RAW matchStatus, and nothing else. Everything else
    on a card is either derived from this integer (the badge colour and
    its translated label) or outright noise: the same page carries two
    hidden virtual-queue templates whose "Last update time" clock ticks
    every minute, which would fire an alert on every single run if it
    ever reached the hash.
    """
    return f"{m.get('match_id')}\t{m.get('fixture')}\t{m.get('status')}"


def compute_hash(matches: list) -> str:
    """SHA-256 over the sorted payloads (rule 5 -- always sort)."""
    body = "\n".join(match_payload(m) for m in sorted(matches, key=match_payload))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------
# scraping
# --------------------------------------------------------------------
# Selectors live here, together, with a note on how to re-derive them
# (rule 8). To re-derive: open https://www.tazkarti.com/#/matches, click
# "View More" until it disables, then inspect one card:
#
#   .match                        card root
#     .top .teams .team-names
#       .team-name.first  /  .team-name.second
#     .blocks button.button.button-green.width-auto     "Book Ticket"
#     .bottom .status                                   availability badge
#
# The badge is captured for cross-checking and alert wording only, NOT
# for change detection -- see match_payload(). The Book Ticket button is
# deliberately ignored: its colour class is static (green even when
# booking is closed) and its disabled property also depends on login
# state and a transient per-card startBooking flag.
#
# Two of the .match elements on the page are hidden virtual-queue
# templates rather than fixtures: blank team names, no .status, and text
# like "People waiting" / "Last update time : 05 : 13 PM". Cards with no
# team name are skipped, which drops them.
PAGE_SCRIPT = """
() => {
    const clean = (t) => (t || '').replace(/\\s+/g, ' ').trim();

    const cards = [];
    for (const card of Array.from(document.querySelectorAll('.match'))) {
        const names = card.querySelector('.team-names');
        if (!names) continue;

        const firstEl  = names.querySelector('.team-name.first');
        const secondEl = names.querySelector('.team-name.second');
        const first  = clean(firstEl  ? firstEl.innerText  : '');
        const second = clean(secondEl ? secondEl.innerText : '');
        // No team name at all -> hidden queue template, not a fixture.
        if (!first && !second) continue;

        const badge = card.querySelector('.status');
        cards.push({
            fixture: (first + ' vs ' + second).trim(),
            badge_text: badge ? clean(badge.innerText) : null,
            badge_class: badge
                ? (Array.from(badge.classList).filter(c => c !== 'status').join(' ') || null)
                : null
        });
    }
    return { total: cards.length, cards: cards };
}
"""

# The page fetches its own listing data from this public static file and
# renders the cards from it. It is the only place the raw matchStatus
# integer appears. Reading the response the page already requested adds
# no load of our own (rule 12).
MATCHES_JSON_FRAGMENT = "matches-list-json"


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
    """Return the sorted Al Ahly fixtures, each with its raw status.

    Every element is {match_id, fixture, status, status_label,
    status_badge, status_class}, where `status` is Tazkarti's raw
    matchStatus integer. Raises ScrapeError rather than returning
    anything it cannot vouch for.
    """
    captured = []

    def on_response(response):
        if MATCHES_JSON_FRAGMENT not in response.url:
            return
        try:
            body = response.json()
        except Exception:
            return          # not JSON, or the body is already gone
        if isinstance(body, list) and body:
            captured.append(body)

    # Registered before goto() -- the page fetches its listing data during
    # navigation. Removed again in the finally so the local monitor's loop
    # doesn't accumulate one handler per poll.
    page.on("response", on_response)
    try:
        # about:blank first, so the next goto() is guaranteed to be a real
        # load. TZK_URL is a hash route, and navigating to a URL that
        # differs from the current one only after the "#" is a
        # same-document navigation: the browser fires no page load,
        # Angular never re-bootstraps, and the listing feed is never
        # re-fetched. The local monitor reuses one page across polls, so
        # without this its second and every later poll re-reads the DOM
        # left over from the first one -- reporting "No change." forever
        # no matter what happens on the site. Costs CI one navigation to
        # a blank page and nothing else.
        page.goto("about:blank")
        page.goto(TZK_URL, wait_until="domcontentloaded", timeout=45000)

        # wait_for_selector, never networkidle + a fixed sleep: on an SPA
        # networkidle can resolve before Angular paints (rule 7).
        try:
            page.wait_for_selector(".team-names", timeout=25000)
        except PlaywrightTimeout:
            dump_evidence(page, "no-selector")
            raise ScrapeError(
                ".team-names never appeared within 25s. The page did not render "
                "match cards -- likely blocked, geo-restricted, or the markup changed."
            )

        # Separate wait, separate error. ".team-names but no .status" means
        # the page rendered and the availability signal specifically is
        # gone, which is a different problem from the page not rendering.
        try:
            page.wait_for_selector(".status", timeout=15000)
        except PlaywrightTimeout:
            dump_evidence(page, "no-status")
            raise ScrapeError(
                "Match cards rendered but no .status badge appeared within 15s. "
                "The availability markup changed -- re-derive the selector before "
                "trusting any result."
            )

        # Load every page BEFORE parsing, or the scrape silently covers
        # only the first one.
        try:
            clicks = load_all_pages(page)
        except ScrapeError:
            dump_evidence(page, "load-more")
            raise

        dom = page.evaluate(PAGE_SCRIPT)

        dom_total = dom["total"]
        if dom_total == 0:
            dump_evidence(page, "zero-cards")
            raise ScrapeError("Selector matched but zero match cards parsed.")

        if not captured:
            dump_evidence(page, "no-json")
            raise ScrapeError(
                f"The page never fetched '{MATCHES_JSON_FRAGMENT}'. The raw "
                "matchStatus lives only in that payload, so availability cannot "
                "be established -- refusing to fall back to the badge text."
            )

        rows = [r for r in captured[-1]
                if r.get("showInPortal", True) and not r.get("isDeleted", False)]

        # An independent check on the pagination fix: the feed knows the
        # true number of fixtures, so if the DOM shows fewer then
        # "View More" left the listing partial. This is the kind of
        # criterion the original Phase 1 test suite lacked.
        if len(rows) != dom_total:
            dump_evidence(page, "dom-json-mismatch")
            raise ScrapeError(
                f"The page rendered {dom_total} fixture card(s) but its data feed "
                f"lists {len(rows)}. Either 'View More' left the listing partial "
                "or the feed and the page disagree. Refusing to report either "
                "as complete."
            )
    finally:
        page.remove_listener("response", on_response)

    badges = {c["fixture"]: c for c in dom["cards"]}

    matches = []
    for row in rows:
        if not is_al_ahly_row(row):
            continue
        english = f"{row.get('teamName1', '')} vs {row.get('teamName2', '')}".strip()
        arabic = f"{row.get('teamNameAr1', '')} vs {row.get('teamNameAr2', '')}".strip()

        # The card renders whichever language the app is set to, so try
        # both keys. Diagnostics only -- a miss here is never fatal.
        badge = badges.get(english) or badges.get(arabic) or {}
        raw = row.get("matchStatus")
        matches.append({
            "match_id": row.get("matchId"),
            "fixture": english,
            "status": raw,
            "status_label": status_label(raw),
            "status_badge": badge.get("badge_text"),
            "status_class": badge.get("badge_class"),
        })

    matches.sort(key=match_payload)

    print(f"Parsed {dom_total} match cards after {clicks} 'View More' click(s), "
          f"{len(matches)} of them Al Ahly.")
    for m in matches:
        print(f"  {m['fixture']} -- {m['status_label']} "
              f"(matchStatus={m['status']}, badge={m['status_badge']!r})")
    return matches


# --------------------------------------------------------------------
# alert wording
# --------------------------------------------------------------------

def describe_change(old: list, new: list) -> str:
    """Say what actually changed, in words that mean different things.

    "Tickets are now on sale" and "a fixture was added" are not the same
    event and must not read the same on a lock screen. The most
    actionable section is emitted first so it survives truncation in a
    notification preview.
    """
    old_by_id = {m.get("match_id"): m for m in old if isinstance(m, dict)}
    new_by_id = {m.get("match_id"): m for m in new if isinstance(m, dict)}

    on_sale, added, closed, other, removed = [], [], [], [], []

    for mid, m in new_by_id.items():
        fixture = m.get("fixture")
        now = m.get("status")
        now_label = m.get("status_label") or status_label(now)
        previous = old_by_id.get(mid)

        if previous is None:
            if now == STATUS_AVAILABLE:
                on_sale.append(f"  {fixture}  (new fixture, already on sale)")
            else:
                added.append(f"  {fixture}  ({now_label})")
            continue

        was = previous.get("status")
        if was == now:
            continue
        was_label = previous.get("status_label") or status_label(was)

        if now == STATUS_AVAILABLE:
            on_sale.append(f"  {fixture}  ({was_label} -> AVAILABLE)")
        elif was == STATUS_AVAILABLE:
            closed.append(f"  {fixture}  (AVAILABLE -> {now_label})")
        else:
            other.append(f"  {fixture}  ({was_label} -> {now_label})")

    for mid, m in old_by_id.items():
        if mid not in new_by_id:
            removed.append(f"  {m.get('fixture')}")

    sections = []
    if on_sale:
        sections.append("\U0001F3AB TICKETS ON SALE:\n" + "\n".join(on_sale))
    if added:
        sections.append("\U0001F195 FIXTURE ADDED:\n" + "\n".join(added))
    if closed:
        sections.append("\U0001F512 NO LONGER ON SALE:\n" + "\n".join(closed))
    if other:
        sections.append("ℹ️ STATUS CHANGED:\n" + "\n".join(other))
    if removed:
        sections.append("❌ REMOVED FROM LISTING:\n" + "\n".join(removed))
    if not sections:
        # The hash moved but no transition explains it -- a fixture was
        # renamed, or a match id was reissued. Say that, rather than
        # inventing a reason.
        sections.append(
            "Tracked details changed with no status transition "
            "(fixture renamed, or match id reissued)."
        )
    return "\n\n".join(sections)


# ====================================================================
# END SHARED SCRAPE BLOCK (rule 13)
# ====================================================================


# --------------------------------------------------------------------
# telegram
# --------------------------------------------------------------------

def send_telegram(message: str) -> bool:
    """Returns True ONLY if Telegram accepted the message."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
        if resp.status_code == 200:
            print("Telegram alert sent OK.")
            return True
        # This is the important part -- Telegram tells you exactly
        # what's wrong (bad token, bad chat id, bot never started, etc).
        print("Telegram alert FAILED:", resp.status_code, resp.text)
        return False
    except Exception as e:
        print("Telegram request errored:", e)
        return False


# --------------------------------------------------------------------
# main
# --------------------------------------------------------------------

def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are empty or unset -- "
            "check your .env file."
        )

    print("Watching for Al Ahly ticket availability changes... (Ctrl+C to stop)")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ar-EG",
            timezone_id="Africa/Cairo",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()

        while True:
            try:
                matches = fetch_al_ahly_matches(page)

                state = load_state()
                current_hash = compute_hash(matches)
                last_hash = state.get("hash")
                stored = state.get("matches", [])
                # Phase 1 stored plain fixture strings; Phase 2 stores objects.
                legacy_state = any(isinstance(m, str) for m in stored)
                last_matches = [m for m in stored if isinstance(m, dict)]

                delivered = True
                if last_hash is None:
                    print(f"Baseline established ({len(matches)} Al Ahly fixtures).")
                elif legacy_state:
                    # The old hash covered fixture names only, so it is not
                    # comparable with one that covers matchStatus. Establish
                    # the new baseline quietly rather than alerting on what
                    # is only a format change.
                    print("Baseline migrated from the fixture-list signal to the "
                          "availability signal -- not comparable with the old "
                          "hash, so re-establishing quietly.")
                elif current_hash != last_hash:
                    print("Change detected -- sending Telegram alert...")
                    delivered = send_telegram(
                        f"{describe_change(last_matches, matches)}\n\n{TZK_URL}"
                    )
                else:
                    print("No change.")

                # Only advance the baseline once the alert is actually out.
                # Saving after a failed send makes the next poll report no
                # change, and the alert is lost for good.
                if delivered:
                    save_state({
                        "hash": current_hash,
                        "matches": matches,
                        "consecutive_failures": 0,
                    })
                else:
                    print("Alert undelivered -- baseline kept so the next "
                          "poll retries.")

            except Exception as e:
                print("Check failed (will retry):", e)

            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
