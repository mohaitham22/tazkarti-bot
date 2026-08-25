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
import sys
import time
import json
import socket
import hashlib
import logging
import logging.handlers
import datetime
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

_HERE = os.path.dirname(os.path.abspath(__file__))

# An explicit path, not a bare load_dotenv(). Task Scheduler starts the
# process with an arbitrary working directory, and dotenv's search falls
# back to the cwd in some invocations -- an .env it fails to find then
# surfaces much later as a confusing "missing TELEGRAM_BOT_TOKEN".
load_dotenv(os.path.join(_HERE, ".env"))


# --------------------------------------------------------------------
# where the always-on local runner keeps its own files
# --------------------------------------------------------------------
# Deliberately NOT in the repo, for three separate reasons:
#
#   1. Separate baseline. The 30s local loop and the 10-minute CI job
#      watch the same fixtures. Pointed at one state file they overwrite
#      each other's hash, and each one's write then makes the other's
#      next run see a change that never happened -- two runners
#      cross-firing false alerts at each other forever.
#   2. The repo is inside OneDrive. A 30-second loop rewriting a file
#      there is ~2,880 uploads a day, and a sync lock landing on the one
#      write that mattered is a real way to lose a baseline.
#   3. CI commits its last_seen.json on every run. A local writer would
#      be fighting `git pull --rebase` for the same file.
LOCAL_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or _HERE, "tazkarti-monitor"
)
os.makedirs(LOCAL_DATA_DIR, exist_ok=True)

# Read by the SHARED SCRAPE BLOCK below, which runs at import time, so
# these have to be set BEFORE it. setdefault, so an explicit environment
# value still wins -- that is how the verification runs point the script
# at a throwaway state file.
os.environ.setdefault(
    "TZK_STATE_FILE", os.path.join(LOCAL_DATA_DIR, "last_seen_local.json")
)
os.environ.setdefault("TZK_DEBUG_DIR", os.path.join(LOCAL_DATA_DIR, "debug"))

LOG_FILE = os.path.join(LOCAL_DATA_DIR, "monitor.log")

TZK_URL = os.environ.get("TZK_URL", "https://www.tazkarti.com/#/matches")
# An EMPTY value must fail exactly like a missing one -- an empty token
# produces a 404 from Telegram that is easy to mistake for a network blip.
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

HOSTNAME = socket.gethostname()

POLL_SECONDS = 30   # be reasonable -- this is someone else's server

# Failure handling, in polls. At 30s a poll: hold off alerting for the
# first 3 minutes of trouble, because a single timeout is not news, then
# re-state it hourly for as long as it stays broken. An unfixable
# notification every 30 seconds trains you to swipe the bot away, which
# is the one outcome that actually costs you a ticket.
FAILURE_ALERT_AFTER = 6       # 6 x 30s = 3 minutes before the first alert
FAILURE_REALERT_EVERY = 120   # then ~1 hour between repeats
FAILURE_RETRY_EVERY = 10      # but retry ~5 min after an alert we could not send

# A browser that has run for two hours is a browser that has had two
# hours to leak. Recycling on a schedule is cheaper than diagnosing why
# the poll went slow on day four.
BROWSER_RECYCLE_POLLS = 240   # ~2 hours

# A once-a-day "still here". The failure alert cannot fire if the machine
# is asleep or the process is gone -- in those cases silence IS the
# symptom, and a heartbeat is what turns silence into something you can
# notice. Set TZK_HEARTBEAT_HOURS=0 to switch it off.
HEARTBEAT_HOURS = float(os.environ.get("TZK_HEARTBEAT_HOURS", "24"))
NOTIFY_ON_START = os.environ.get("TZK_NOTIFY_START", "1").strip() not in ("0", "", "no")

# Same browser identity as CI, so that a difference in results is a real
# difference and not an artefact of the two scripts looking different to
# the server.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------
# logging
# --------------------------------------------------------------------

class _LineTee:
    """Mirror a text stream into the rotating log, a whole line at a time.

    print() writes the text and its newline as two separate calls, so
    buffering until a newline is what stops one log line becoming two.
    """

    def __init__(self, stream, logger):
        self._stream = stream
        self._logger = logger
        self._buf = ""

    def write(self, text):
        if self._stream is not None:
            try:
                self._stream.write(text)
            except Exception:
                # A console that cannot encode what it is handed must not
                # be able to kill the monitor. Arabic team names through a
                # cp1252 console raise UnicodeEncodeError inside the
                # print() itself -- down in the shared block, where there
                # is no try/except to catch it.
                try:
                    self._stream.write(text.encode("ascii", "replace").decode("ascii"))
                except Exception:
                    pass
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._logger.info(line)

    def flush(self):
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False


def install_logging() -> None:
    """Tee stdout and stderr into a rotating file.

    Under Task Scheduler there is no console at all, so without this every
    print() in this script and in the shared block goes nowhere, and a
    failure at 3am leaves nothing to read at 9am.
    """
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger = logging.getLogger("tazkarti.local")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    sys.stdout = _LineTee(sys.stdout, logger)
    sys.stderr = _LineTee(sys.stderr, logger)


# ====================================================================
# BEGIN SHARED SCRAPE BLOCK (rule 13)
# Byte-identical in alahly_ticket_check.py and alahly_ticket_monitor.py.
# Never edit one copy by hand -- edit the copy in alahly_ticket_check.py
# and then run
#     python sync_shared_block.py
# which copies it across and verifies the two are identical. Hand-copying
# is how these two files drifted apart in the first place.
# ====================================================================

# Both of these default to a path NEXT TO THIS SCRIPT rather than to the
# process's working directory. Task Scheduler does not set a working
# directory, so a bare relative path there writes the baseline into
# C:\Windows\System32 instead of the repo -- and a baseline the next run
# cannot find reads as "no baseline yet", which re-establishes silently
# and loses the alert. CI is unaffected: it runs from the repo root, so
# the resolved path is the same file it always was.
#
# TZK_STATE_FILE exists so the always-on local runner can keep its OWN
# baseline. The 30s local loop and the 10-minute CI job watch the same
# site; pointed at one file they overwrite each other's hash, and each
# one's write makes the other's next run see a change that never
# happened. Separate files, no cross-fire.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("TZK_STATE_FILE") or os.path.join(_SCRIPT_DIR, "last_seen.json")
DEBUG_DIR = os.environ.get("TZK_DEBUG_DIR") or os.path.join(_SCRIPT_DIR, "debug")


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
    """Read the baseline, and be LOUD if one exists but cannot be read.

    The old version swallowed every error and returned {}, which the
    callers cannot tell apart from "no baseline yet" -- so a corrupt file
    silently re-established the baseline and threw away the alert that
    was about to fire. That is rule 1 in a different costume, and the
    local runner makes it likelier: it rewrites this file every 30
    seconds, so an unclean shutdown has ~2,880 chances a day to catch a
    half-written one. utf-8-sig because a state file that has been
    through a Windows editor or PowerShell carries a BOM, which plain
    utf-8 rejects.
    """
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        # Not fatal -- refusing to run helps nobody. But say so, keep the
        # unreadable file for post-mortem, and let the caller re-baseline
        # knowing it happened rather than assuming a fresh install.
        print(f"WARNING: {STATE_FILE} exists but could not be read ({e}). "
              f"Re-establishing the baseline; ONE change may go unalerted.")
        try:
            os.replace(STATE_FILE, STATE_FILE + ".corrupt")
            print(f"Kept the unreadable file as {STATE_FILE}.corrupt")
        except OSError:
            pass
        return {}


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    # STATE_FILE may now live outside the repo (the local runner keeps its
    # baseline under LOCALAPPDATA), so the directory is not guaranteed to
    # exist on a first run.
    parent = os.path.dirname(STATE_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Write-then-rename, so the baseline is never observed half-written.
    # os.replace is atomic within a volume on Windows as well as POSIX.
    # Without this, losing power partway through one of the local
    # runner's writes leaves a truncated file that the next start cannot
    # parse -- see load_state().
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)


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
# browser lifecycle
# --------------------------------------------------------------------

def new_browser(p):
    """A fresh Chromium plus the one context/page the poll loop reuses."""
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=USER_AGENT,
        locale="ar-EG",
        timezone_id="Africa/Cairo",
        viewport={"width": 1366, "height": 900},
    )
    return browser, context, context.new_page()


START_PING_MIN_GAP_SECONDS = 600


def should_send_start_ping() -> bool:
    """True at most once every 10 minutes.

    The Task Scheduler watchdog relaunches this script within a minute of
    it dying, so an unhandled crash occurring *after* start-up would
    otherwise put a Telegram message on your phone every single minute,
    forever. The reboot signal is worth having. A crash-loop broadcasting
    it at 60 messages an hour is how you end up muting the bot on the one
    day it matters.
    """
    stamp = os.path.join(LOCAL_DATA_DIR, "last-start-ping")
    now = time.time()
    try:
        if now - os.path.getmtime(stamp) < START_PING_MIN_GAP_SECONDS:
            print(f"Skipping the start-up ping -- one went out less than "
                  f"{START_PING_MIN_GAP_SECONDS // 60} minutes ago. "
                  f"Frequent restarts mean something is crashing; read the "
                  f"log above rather than trusting the silence.")
            return False
    except OSError:
        pass                      # no stamp yet, or unreadable -- ping.
    try:
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(str(now))
    except OSError:
        pass
    return True


def close_quietly(*things) -> None:
    """Tear down without raising. Whatever is being closed may already be
    dead -- that is usually the reason we are closing it."""
    for thing in things:
        if thing is None:
            continue
        try:
            thing.close()
        except Exception:
            pass


def maybe_alert_failure(poll, consecutive_failures, alert_due_at,
                        failure_alerted, detail):
    """Telegram once the loop has been failing for more than a few minutes.

    Silent for the first FAILURE_ALERT_AFTER failures, because one timeout
    is not news. After that, hourly -- an unfixable notification every 30
    seconds is how you teach yourself to ignore the bot.

    Returns the updated (alert_due_at, failure_alerted).
    """
    if consecutive_failures == FAILURE_ALERT_AFTER:
        alert_due_at = poll
    if alert_due_at is None or poll < alert_due_at:
        return alert_due_at, failure_alerted

    minutes = consecutive_failures * POLL_SECONDS // 60
    sent = send_telegram(
        f"⚠️ Local Tazkarti watcher has been failing for ~{minutes} min "
        f"({consecutive_failures} polls in a row) on {HOSTNAME}.\n\n"
        f"{detail}\n\n"
        f"The 10-minute GitHub Actions check is separate and unaffected."
    )
    if sent:
        return poll + FAILURE_REALERT_EVERY, True
    # Could not send -- usually the same outage that broke the poll in the
    # first place. Retry sooner than the hourly cadence, but do not hammer
    # Telegram every 30 seconds while the network is down.
    print("Could not deliver the failure alert; will retry shortly.")
    return poll + FAILURE_RETRY_EVERY, failure_alerted


# --------------------------------------------------------------------
# main
# --------------------------------------------------------------------

def main() -> int:
    install_logging()

    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are empty or unset -- "
            "check your .env file."
        )

    print("=" * 70)
    print(f"Local monitor starting on {HOSTNAME}. Polling every {POLL_SECONDS}s.")
    print(f"  url    : {TZK_URL}")
    print(f"  state  : {os.environ['TZK_STATE_FILE']}")
    print(f"  debug  : {os.environ['TZK_DEBUG_DIR']}")
    print(f"  log    : {LOG_FILE}")
    print("=" * 70)

    if NOTIFY_ON_START and should_send_start_ping():
        # Worth a message: this also fires after a reboot, so its arrival
        # is how you know the machine came back and the watcher with it.
        send_telegram(
            f"✅ Local Tazkarti watcher started on {HOSTNAME} "
            f"(every {POLL_SECONDS}s)."
        )

    poll = 0
    consecutive_failures = 0
    alert_due_at = None      # poll index at which the next failure alert is due
    failure_alerted = False
    last_heartbeat = time.time()

    with sync_playwright() as pw:
        browser = context = page = None
        polls_on_browser = 0
        try:
            while True:
                # (Re)launch whenever there is no live page. Every failure
                # path below drops the browser, so this doubles as the
                # recovery path.
                if page is None:
                    try:
                        browser, context, page = new_browser(pw)
                        polls_on_browser = 0
                        print("Launched a fresh Chromium.")
                    except Exception as e:
                        consecutive_failures += 1
                        print(f"Could not launch Chromium "
                              f"({consecutive_failures} in a row): {e!r}")
                        alert_due_at, failure_alerted = maybe_alert_failure(
                            poll, consecutive_failures, alert_due_at,
                            failure_alerted, f"Chromium would not launch: {e}",
                        )
                        time.sleep(POLL_SECONDS)
                        continue

                poll += 1
                polls_on_browser += 1

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
                        # The source marker goes LAST. Two runners now alert on
                        # the same fixtures so you need to know which one spoke,
                        # but not at the cost of pushing the actionable line out
                        # of a lock-screen preview.
                        delivered = send_telegram(
                            f"{describe_change(last_matches, matches)}\n\n"
                            f"{TZK_URL}\n\n"
                            f"-- local {POLL_SECONDS}s watcher on {HOSTNAME}"
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

                    if failure_alerted:
                        minutes = consecutive_failures * POLL_SECONDS // 60
                        send_telegram(
                            f"✅ Local watcher recovered after "
                            f"{consecutive_failures} failed poll(s) "
                            f"(~{minutes} min) on {HOSTNAME}."
                        )
                    elif consecutive_failures:
                        print(f"Recovered after {consecutive_failures} failed poll(s).")
                    consecutive_failures = 0
                    alert_due_at = None
                    failure_alerted = False

                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    consecutive_failures += 1
                    minutes = consecutive_failures * POLL_SECONDS // 60
                    print(f"Poll failed ({consecutive_failures} in a row, "
                          f"~{minutes} min): {e!r}")

                    # Throw the browser away on EVERY failure.
                    #
                    # The old loop caught the exception, printed it, slept,
                    # then called fetch_al_ahly_matches(page) again with the
                    # SAME page object. If what broke was the browser itself
                    # -- the Chromium process died, the context was closed,
                    # the driver pipe went -- that page is dead for good and
                    # every later poll raises the identical error, forever.
                    # The loop keeps running, keeps printing, and never
                    # scrapes again: a silent wedge, which is precisely what
                    # rule 1 exists to make impossible.
                    #
                    # Relaunching unconditionally costs a ~1s restart after a
                    # transient network blip. In exchange the wedge cannot
                    # happen at all, and there is no need to guess which
                    # exception types mean "the browser is gone" -- a guess
                    # that would eventually be wrong on some Playwright
                    # version, silently, in the direction of staying wedged.
                    close_quietly(context, browser)
                    browser = context = page = None

                    alert_due_at, failure_alerted = maybe_alert_failure(
                        poll, consecutive_failures, alert_due_at,
                        failure_alerted, repr(e),
                    )
                else:
                    if polls_on_browser >= BROWSER_RECYCLE_POLLS:
                        print(f"Recycling Chromium after {polls_on_browser} polls.")
                        close_quietly(context, browser)
                        browser = context = page = None

                if HEARTBEAT_HOURS > 0 and (
                    time.time() - last_heartbeat >= HEARTBEAT_HOURS * 3600
                ):
                    last_heartbeat = time.time()
                    tracked = len(load_state().get("matches", []))
                    send_telegram(
                        f"💚 Local watcher alive on {HOSTNAME}: {poll} polls, "
                        f"{tracked} Al Ahly fixture(s) tracked."
                    )

                time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            print("Stopped by keyboard interrupt.")
        finally:
            close_quietly(context, browser)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
