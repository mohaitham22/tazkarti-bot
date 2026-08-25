"""
Al Ahly Tazkarti Login Pre-fill Helper
--------------------------------------
Opens Tazkarti in a VISIBLE browser that remembers your login between
runs, and types your Tazkarti ID and password into the login form.

That is the whole job. It stops there, on purpose.

    YOU click "Sign in".  YOU solve the CAPTCHA.  Every time.

WHAT THIS DOES NOT DO, AND WHY -- all three are deliberate design
decisions, not unfinished work. There is nothing here to "finish":

  1. It does not submit the login form.
     Tazkarti's login is gated by an INVISIBLE reCAPTCHA v2. This is not
     a guess: in the site's own bundle the login API call is
         _http.post(url + "Login", {Username, Password, recaptchaResponse})
     -- the CAPTCHA token is a REQUIRED field -- and the "Sign in"
     button is type="button" whose click handler is recaptchaRef.execute(),
     with the actual login firing only from reCAPTCHA's own callback.
     There is no code path to a session without a Google-issued token.
     Automating past this would mean solving or bypassing a CAPTCHA,
     which this project does not do (see rule 11 in CLAUDE.md).

  2. It does not pick seats, set a quantity, or add anything to a cart.
     That code used to exist here as fabricated placeholder selectors
     that had never matched a real element. It has been REMOVED rather
     than left as TODOs. Do not re-add it: Tazkarti allocates virtual
     queue position by ARRIVAL TIME, so a pre-filled cart does not move
     you up the queue -- being alerted 40 minutes earlier does. That is
     what the monitor is for. Seat/quantity automation is low-value here
     and is parked in CLAUDE.md's v2 table.

  3. It does not click "Pay" or "Confirm", ever.
     Most ticket platforms' terms prohibit automated purchasing, and the
     checkout CAPTCHA exists precisely to require a human. This script
     gets you to the keyboard-saving step and hands control back.

Because it keeps a persistent browser profile, the common case is that
you are ALREADY logged in -- then it skips the credential step entirely
and just opens the match page for you.

Setup:
    pip install playwright python-dotenv
    (add --break-system-packages at the end if pip complains about an
    "externally managed environment")
    playwright install chromium

    Uses the same .env file as alahly_ticket_monitor.py (see env.example).

Environment variables:
    TZK_USERNAME     - your TAZKARTI ID: a 14-16 digit number, NOT an
                        email. The login field is labelled "Tazkarti ID"
                        and its placeholder is 12345678901234.
                        Only read when you are actually logged out.
    TZK_PASSWORD     - your Tazkarti account password. Same -- only read
                        when logged out.
    TZK_MATCH_URL    - where to go once logged in. Defaults to the match
                        listing, and that default is permanent: Tazkarti
                        has NO per-match URL. Booking happens in a modal
                        on the listing itself, match cards contain no
                        links, and the route table has no matches/:id.
                        Confirmed live 2026-08-25 -- do not go hunting
                        for a deep link. Override it only if you want to
                        land somewhere else entirely.
    TZK_PROFILE_DIR  - (optional) where the browser profile lives.
                        Default: %LOCALAPPDATA%\\tazkarti-monitor\\browser-profile

Run:
    python alahly_ticket_prefill.py


===========================================================================
RUNBOOK
===========================================================================

HOW THE PROFILE DIRECTORY GETS CREATED
    Automatically, on first run. Chromium creates it if it is missing --
    you do not create it by hand, and you should not copy one in from
    another machine.

    It defaults to
        %LOCALAPPDATA%\\tazkarti-monitor\\browser-profile
    which is the same private working directory the always-on local
    monitor uses. It is deliberately NOT inside the repo: this repo
    lives in OneDrive, and a live Chromium profile is a large, constantly
    rewritten pile of files. Letting OneDrive sync it would mean
    thousands of uploads and, eventually, a sync lock landing mid-write
    on the file holding your session. Keep it out of OneDrive.

    Your login lives in that profile as localStorage key "ETMS-Token"
    (plus ETMS-RefreshToken / ETMS-ExpireToken / profileData). It is
    localStorage, not sessionStorage, which is exactly why closing the
    browser does not log you out.

    The first run will be logged out and will fill your credentials.
    Click "Sign in", solve the CAPTCHA, and let the script close the
    browser when you press Enter. From then on you should stay logged in.

    The profile is as sensitive as your password -- it holds a live
    session. Do not commit it, copy it, or put it in a shared folder.

HOW TO TELL THE SESSION HAS EXPIRED
    The script tells you, in the banner it prints on startup. It reports
    one of exactly three states:

        LOGGED IN        -- token found and the site accepted it. Prints
                            the name you are signed in as, opens
                            TZK_MATCH_URL, and stops.
        SESSION EXPIRED  -- the profile had a token, and the site threw
                            it away or asked for credentials anyway.
        LOGGED OUT       -- no token in the profile at all. Normal on
                            the first run, and after you sign out.

    How SESSION EXPIRED is detected, since it is not obvious: the site's
    header requests the cart-icon count on every page, and that request
    is authenticated. If the server has revoked the token, that call
    401s and Tazkarti's own interceptor runs clearCache(), which deletes
    ETMS-Token from localStorage. So the script reads the token, waits
    for the page to settle, and reads it again -- a token that vanished
    in between is a session the server just rejected.

    THE LIMIT OF THAT CHECK, because it is better to know it than to
    trust it blindly: every client-side signal here -- the token, the
    header, the "Welcome <name>" -- comes from the same localStorage. If
    the site never makes an authenticated call while we are looking, a
    dead token can still read as LOGGED IN. The tell is the ordinary
    one, in the browser window that is already open in front of you: the
    header says "Sign in" / "Register" instead of your name. If you see
    that, treat it as SESSION EXPIRED regardless of what the banner said.

WHAT TO DO WHEN IT HAS EXPIRED
    Nothing special -- this is the case the script exists for. On both
    SESSION EXPIRED and LOGGED OUT it opens the login page and fills in
    your Tazkarti ID and password. You click "Sign in", solve the
    CAPTCHA, then press Enter in the terminal so it closes the browser
    cleanly and the refreshed session is written back to the profile.

    Only if that fails repeatedly: delete the profile directory and let
    the next run recreate it from scratch. That is a reset, not routine
    maintenance -- it also throws away cookies and any CAPTCHA
    reputation the profile has built up, so do not do it casually.

    Always let the script close the browser (press Enter). Killing the
    terminal window can lose the session you just created, because
    Chromium may not have flushed localStorage to disk yet.
"""

import os

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()  # reads .env in this folder, if present

# Where to land once we know you are logged in. The listing IS the
# destination -- Tazkarti has no per-match URL. Confirmed live: the route
# table has no matches/:id, match cards contain zero anchors, and Book
# Ticket is a button that opens a modal on this same page (and bounces
# you to #/login if you are not signed in).
DEFAULT_MATCH_URL = "https://www.tazkarti.com/#/matches"
LOGIN_URL = "https://www.tazkarti.com/#/login"

MATCH_URL = os.environ.get("TZK_MATCH_URL") or DEFAULT_MATCH_URL

# NOTE: credentials are read lazily, inside the logged-out branch only.
# Reading them at import time would crash the common case -- already
# logged in, no credentials needed -- for no reason at all.


def default_profile_dir():
    """The browser profile lives beside the local monitor's state, NOT in
    the repo. The repo is in OneDrive; see the RUNBOOK above for why that
    matters. Override with TZK_PROFILE_DIR."""
    override = os.environ.get("TZK_PROFILE_DIR")
    if override:
        return os.path.abspath(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "tazkarti-monitor", "browser-profile")


# --- Selectors -------------------------------------------------------
# Read from the live DOM at https://www.tazkarti.com/#/login and each
# confirmed to resolve to exactly ONE element. NOT guessed.
#
# To re-derive them: open that URL, F12, and inspect the two inputs. The
# form carries NO id attributes -- it is Angular-rendered with name
# attributes only -- so select on [name], never on #id. An earlier
# version of this file used #username / #password, which could never
# have matched anything.
#
# Selecting on name/class also means these survive the site being served
# in Arabic, which a text match on "Sign in" would not.
FAN_ID_INPUT = 'input[name="txtFanId"]'       # label "Tazkarti ID *", maxlength 16
PASSWORD_INPUT = 'input[name="txtPassword"]'  # maxlength 20

# Recorded, and INTENTIONALLY NEVER CLICKED. This is not an oversight and
# not an unfinished line -- clicking it is the human's job, every time,
# because login only completes through the invisible reCAPTCHA callback
# (see point 1 at the top of this file). It is written down because it
# was expensive to find and because knowing it is how you confirm you are
# looking at the real login form. If you are about to add a .click() here,
# re-read the top of this file first.
SIGN_IN_BUTTON = 'form button.button-green'   # text "Sign in", type="button"

# The site's own login test, lifted from its bundle:
#     isLoggedIn = !!localStorage.getItem("ETMS-Token")
TOKEN_KEY = "ETMS-Token"


def banner(lines, indent="  "):
    """Print lines inside an asterisk box that always lines up. Built rather
    than hand-drawn so editing the text later cannot leave it ragged."""
    width = max(len(s) for s in lines) + 6
    print(indent + "*" * width)
    for line in lines:
        print(indent + "*  " + line.ljust(width - 6) + "  *")
    print(indent + "*" * width)


def goto_route(page, url):
    """Navigate to a Tazkarti hash route, forcing a real page load.

    Tazkarti's routes are '#/...' fragments, so page.goto() from one hash
    route to another is a SAME-DOCUMENT navigation: Angular never
    re-bootstraps and you silently keep reading the previous page. The
    local monitor had exactly this bug and every poll after the first
    re-read stale DOM. Bouncing through about:blank forces a genuine load.
    """
    page.goto("about:blank")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)


def has_token(page):
    """True if the profile holds a Tazkarti session token."""
    try:
        return bool(page.evaluate(
            "key => window.localStorage.getItem(key)", TOKEN_KEY))
    except Exception:
        # Not on the tazkarti.com origin, so localStorage is unreadable.
        return False


def profile_name(page):
    """The signed-in fan's name, from the profileData the site caches.
    Cosmetic -- it just lets the banner say who you are signed in as."""
    try:
        return page.evaluate(
            """() => {
                try {
                    const p = JSON.parse(
                        window.localStorage.getItem('profileData') || 'null');
                    if (!p) return null;
                    const en = [p.firstNameEn, p.lastNameEn].filter(Boolean).join(' ');
                    const ar = [p.firstNameAr, p.lastNameAr].filter(Boolean).join(' ');
                    return (en || ar || null);
                } catch (e) { return null; }
            }""")
    except Exception:
        return None


def login_form_present(page, timeout=8000):
    """True if the login form is on screen -- i.e. the site wants credentials."""
    try:
        page.wait_for_selector(FAN_ID_INPUT, timeout=timeout)
        return True
    except PlaywrightTimeout:
        return False


def fill_credentials(page):
    """Type the Tazkarti ID and password in. Does NOT submit. Returns True
    if both fields round-tripped the values we typed."""
    fan_id = os.environ.get("TZK_USERNAME")
    password = os.environ.get("TZK_PASSWORD")

    missing = [n for n, v in (("TZK_USERNAME", fan_id),
                              ("TZK_PASSWORD", password)) if not v]
    if missing:
        print("")
        print("  Cannot pre-fill: %s missing from .env" % ", ".join(missing))
        print("  TZK_USERNAME is your 14-16 digit Tazkarti ID, not an email.")
        print("  Add them to .env (see env.example), or just log in by hand")
        print("  in the browser window that is open right now -- the session")
        print("  is saved to the profile either way.")
        return False

    page.fill(FAN_ID_INPUT, fan_id)
    page.fill(PASSWORD_INPUT, password)

    # Round-trip check. Angular reactive forms can quietly ignore a value
    # that never raised an input event, and a blank field you did not
    # notice is worse than no help at all.
    id_ok = page.input_value(FAN_ID_INPUT) == fan_id
    pw_ok = page.input_value(PASSWORD_INPUT) == password

    # Lengths only -- never print the credentials themselves.
    print("  Tazkarti ID filled: %s (%d chars)" % (id_ok, len(fan_id)))
    print("  Password filled:    %s (%d chars)" % (pw_ok, len(password)))
    return id_ok and pw_ok


def main():
    profile_dir = default_profile_dir()
    os.makedirs(profile_dir, exist_ok=True)

    print("")
    print("=" * 70)
    print("Al Ahly Tazkarti login pre-fill")
    print("=" * 70)
    print("Profile: %s" % profile_dir)

    with sync_playwright() as p:
        # A PERSISTENT context, so the login survives between runs -- the
        # session token is a localStorage entry inside this directory.
        # headless=False because you have to be able to click Sign in and
        # solve the CAPTCHA yourself.
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            no_viewport=True,
            locale="en-US",
            timezone_id="Africa/Cairo",
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()

            # Go where you actually want to be, then work out from there
            # whether the session held. One navigation covers both cases.
            goto_route(page, MATCH_URL)
            token_before = has_token(page)

            # Let Angular bootstrap and route. This wait is also doing real
            # work: the site header calls the cart-icon endpoint on every
            # page, which is an AUTHENTICATED request. If the server has
            # revoked our token, that call 401s and the site's own
            # interceptor runs clearCache(), deleting ETMS-Token. So
            # re-reading the token afterwards catches a dead session that
            # merely reading it up front would have reported as healthy.
            page.wait_for_timeout(3500)
            token = has_token(page)

            bounced_to_login = ("#/login" in page.url
                                or login_form_present(page, timeout=3000))

            if token and not bounced_to_login:
                state = "LOGGED IN"
            elif token_before and (bounced_to_login or not token):
                # We arrived holding a token and the site rejected it.
                state = "SESSION EXPIRED"
            else:
                state = "LOGGED OUT"

            print("Status:  %s" % state)
            print("-" * 70)

            if state == "LOGGED IN":
                who = profile_name(page)
                print("")
                if who:
                    print("  Already signed in as %s -- nothing to type." % who)
                else:
                    print("  Already signed in -- nothing to type.")
                print("  Opened: %s" % MATCH_URL)
                if MATCH_URL == DEFAULT_MATCH_URL:
                    print("")
                    print("  (That is the match LISTING, not a specific match.")
                    print("   Set TZK_MATCH_URL in .env to go straight to a match.)")
                print("")
                print("  The browser is yours. Take it from here.")
            else:
                if state == "SESSION EXPIRED":
                    print("")
                    print("  Your saved session is stale -- the site asked for")
                    print("  credentials again. This is normal; just sign in.")

                goto_route(page, LOGIN_URL)
                if not login_form_present(page, timeout=30000):
                    print("")
                    print("  Could not find the login form at %s" % LOGIN_URL)
                    print("  The page may still be loading, or Tazkarti changed")
                    print("  its markup. Log in by hand in the open window --")
                    print("  the session still gets saved to the profile.")
                else:
                    print("")
                    filled = fill_credentials(page)
                    print("")
                    if filled:
                        banner([
                            'YOUR TURN: click "Sign in" in the browser window.',
                            "Solve the CAPTCHA if it asks. This script will",
                            "NOT submit the form for you -- that is deliberate.",
                        ])

            print("")
            print("  Leave this terminal open. Press Enter here when you are")
            print("  done, so the browser closes cleanly and your session is")
            print("  saved to the profile for next time.")
            print("")
            input("Press Enter to close the browser... ")

        except KeyboardInterrupt:
            print("\nInterrupted -- closing the browser cleanly.")
        finally:
            # Always close through Playwright. Chromium flushes
            # localStorage on shutdown, and that flush is what persists
            # the session you just signed into.
            context.close()

    print("Browser closed. Session (if any) is saved in the profile.")


if __name__ == "__main__":
    main()
