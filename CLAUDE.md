# Al Ahly Tazkarti Monitor — Claude Code Context

## TL;DR
A personal ticket-availability watcher. Polls Tazkarti's public match listing with headless
Playwright, detects when the Al Ahly fixture list changes, and pushes a Telegram message.
A separate local-only helper pre-fills the checkout form up to — but never past — the point
where a human must take over.

Stack: Python 3.12 + Playwright (Chromium) + Telegram Bot API + GitHub Actions (cron).
No server, no database, no web UI. State is a single JSON file committed back to the repo.

**Phase 0 and Phase 1 are DONE and the pagination bug is FIXED. The monitor now reads the
entire listing, currently tracks `ZED FC vs Al Ahly FC`, and has delivered a real alert for it
(run #44, 2026-08-25). There is no blocking bug. Phase 2 — changing the signal from "the
fixture list changed" to "tickets are buyable" — is the next work.**

Repo: `mohaitham22/tazkarti-bot` — **PUBLIC**. Every rule about secrets in this file follows
from that one fact.

---

## Phase Roadmap — Read This First

```
Phase 0  ✅ DONE         Local monitor: Playwright scrape + hash diff + Telegram alert.
                         Confirmed working — real alerts received on hash change.
Phase 1  ✅ DONE         GitHub Actions migration so the monitor runs without a terminal open.
                         All four acceptance criteria proven. Runs #10/#11/#12, 2026-08-24.
Phase 2  ⬜ NOT STARTED  Change the signal from "fixture list changed" to "tickets are buyable".
Phase 3  ⬜ NOT STARTED  Pre-fill helper: replace TODO selectors with Tazkarti's real ones.
```

**Phase 1 is proven and the scraper now reads the whole listing, so Phase 2 is unblocked for
real. The `.status` selector it needs is already recorded in Feature Specs below.**
**Do NOT start Phase 3 until Phase 2 gives a usable per-match URL to open.**
**Phase 3 is LOCAL ONLY and never runs in CI. See Coding Rules.**

---

## ✅ No Blocking Bug — Pagination Fixed 2026-08-25

Kept as a record, because it is the best example in this project of a green job proving nothing.

**What was wrong.** `#/matches` renders 6 match cards and hides the rest behind a `View More`
button. Neither script ever clicked it, so both read page 1 and stopped. `ZED FC vs Al Ahly FC`
— the exact fixture this project exists to watch — sat on page 2 while every run truthfully
reported `Parsed 6 match cards, 0 of them Al Ahly.` and stayed silent.

**It survived the entire Phase 1 test suite.** All four acceptance criteria passed. None of
them asked whether the scrape saw every match. A fifth criterion has been added below so the
same shape of gap cannot pass again.

**The fix (`8178263`).** `load_all_pages()` clicks `View More` until it disappears or reports
disabled, then parses. Bounded at `LOAD_MORE_MAX_CLICKS = 20`; if the button is still live when
that budget runs out it raises rather than returning, because a partial listing reported as a
complete one is the original bug wearing a different hat. It also stops early if a click adds
no cards, so a button that never disables cannot spin forever.

The control is selected by class, not by text, so it survives the site being served in Arabic:

```
button.button-blue.width-auto:not(.filter-toggle)
```

`:not(.filter-toggle)` is load-bearing — the two Search buttons also carry `button-blue` and
`width-auto`, and clicking one of those re-filters the listing instead of extending it.

**Result, run #44:** `Parsed 10 match cards after 1 'View More' click(s), 1 of them Al Ahly.` /
`Telegram alert sent OK.` The one-time NEW alert fired as predicted and the baseline moved from
the empty-string hash to `8fbc6677...1e89` with `matches: ["ZED FC vs Al Ahly FC"]`.

**Landed in both scripts (rule 13).** `PAGE_SCRIPT` and the whole pagination block are now
byte-identical between them, copied programmatically rather than by hand. That also pulled
`alahly_ticket_monitor.py` up to the CI script's behaviour — `wait_for_selector` instead of
`networkidle` plus a fixed sleep, Arabic normalisation, and sorted output. It had none of the
three, so it could not previously have served as a reference for any of them.

---

## Current State

### What exists

| File | Status | Notes |
|---|---|---|
| `alahly_ticket_check.py` | ✅ Verified in CI | Parses the FULL listing, detects change, alerts, fails loudly, preserves the baseline on failure, recovers. All five acceptance criteria proven against it. |
| `alahly_ticket_monitor.py` | ✅ Trustworthy reference | Local loop, `POLL_SECONDS = 30`. Scraping logic now byte-identical to the CI script. Verified locally: same 10 cards, same 1 Al Ahly fixture. |
| `alahly_ticket_prefill.py` | ⬜ Skeleton | Every selector a `TODO`. Never run for real. |
| `get_telegram_chat_id.py` | ✅ Working | One-shot helper, purpose served. |
| `.github/workflows/monitor.yml` | ✅ Working | `cron: */10`, `contents: write`, `checkout@v5` / `setup-python@v6`, Playwright cache, artifact upload on failure, concurrency group. Node 20 warning gone. |
| `last_seen.json` | ✅ Complete | `{hash: 8fbc6677...1e89, matches: ["ZED FC vs Al Ahly FC"]}`. First baseline in this project's history that reflects the whole listing. |
| `env.example` | ✅ Exists | Docstrings say `.env.example`; the repo file is `env.example`. Harmless. |

### Verified working — with run numbers, 2026-08-24

- **Scrape on GitHub runners.** Runs #5, #6, #12: `Parsed 6 match cards`. The geo-block and
  bot-challenge hypotheses are **disproven**. The `debug-11` screenshot shows the fully
  rendered English matches page with Book Ticket buttons; its HTML dump contains zero
  occurrences of `cloudflare`, `captcha`, `Access Denied`, or country-restriction text. CI and
  a simultaneous Cairo run returned the same six fixtures by name.
- **Telegram delivery from inside Actions.** Run #10: `Telegram alert sent OK.` /
  `Change detected -- alert delivered.`
- **Failure path.** Run #11: red job, exit 1, `debug-11` artifact (210 KB, PNG + HTML),
  Telegram warning delivered, baseline preserved.
- **Baseline preservation.** After run #11 the state kept `hash e3b0c442...b855` and
  `matches: []`, gaining only `consecutive_failures: 1` and `last_error`.
- **Recovery.** Run #12: `Scraper recovered after 1 failed run(s).`, counter back to 0.
- **Scheduled cron.** Runs #2, #3, #5, #6, #9 all `event: schedule`.

### Not yet verified

- Phase 2 availability signal. Selectors are known but unused (see Feature Specs). Only
  `.status.green` / `Available` has ever been observed — the sold-out and coming-soon variants
  are still unseen, so their exact markup is guesswork until one appears.
- Prefill helper, in any form.
- Whether an Al Ahly fixture being *added* to the listing fires correctly. Run #44 proved the
  added-branch works, but via the pagination fix rather than a genuine new fixture.

### Standing Blockers

- **Signal is fixture-list, not availability** — `.team-names` changes when a fixture is added
  or removed; tickets opening for an already-listed match does not touch it. Phase 2. The
  selector is now known: `.status` (see Feature Specs).
- **`.env` was committed to PUBLIC history.** Commit `b8ccce9` contains a real `.env` with
  `TZK_USERNAME`, `TZK_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Removing it in
  `acbc288` did not remove it from history — the blob still returns HTTP 200 with no auth.
  **Both credentials were rotated 2026-08-24**: the old bot token now returns 401, and the
  Tazkarti password was changed. History was deliberately NOT rewritten — rotation is the real
  fix, and GitHub can retain unreachable blobs anyway. Never treat anything in `.env` as
  having been private.
- **Every run commits `last_seen.json`** — `updated_at` changes even when nothing else does,
  so the state commit lands on every run rather than only on change. Side effect: ~144 bot
  commits/day at `*/10`. Upside: it keeps the repo active, which defuses the 60-day
  scheduled-workflow shutoff below. Fix, if it ever annoys: only write when `hash` or
  `consecutive_failures` changes.
- **Scheduled workflows are disabled after 60 days of repository inactivity.** Currently
  defused by the commit-every-run behaviour above. If that is ever "fixed", this comes back.
- **GitHub cron drift** — `*/10` is a request, not a promise. Observed gaps of 8–45 minutes.
- **Prefill selectors are fabricated** — `#username`, `#password`, `#login-button`,
  `#seat-category`, `#quantity`, `#add-to-cart` were invented. None verified.

## ⚠️ SESSION MEMORY PROTOCOL — READ THIS AT THE START OF EVERY SESSION

**This section is the handoff between sessions. Read it before writing a single line of code.**

### How to Start Every New Session
1. Read this entire CLAUDE.md top to bottom.
2. Read the Known Bug section — if it is still present, that is the work.
3. Find the last row in the Session Log — that is where we left off.
4. Check `last_seen.json`. `matches` should be non-empty. If `hash` is `e3b0c442...b855`
   — the SHA-256 of the empty string — the scrape is returning nothing; treat that as broken
   until the run log's card count proves otherwise.
5. Confirm out loud: "I've read the context. We are in Phase X. Last session did Y. Continuing with Z."
6. Only then start writing code.

**Never assume the scraper works. The job going green proves nothing — that is the entire
lesson of Phase 1.**

### How to End Every Session
1. Add a row to the Session Log (Date | Phase | Done | Blockers | Next).
2. Add a Session Note below with real detail — exact file paths, exact error text.
3. Update the phase roadmap markers and the Current State table.
4. If a new blocker appeared, add it to Standing Blockers with the exact symptom and the fix path.
5. If `last_seen.json` changed meaning, say so explicitly.

**If a session ends without updating this file, the next session starts blind.**

### Session Log

| Date | Phase | Done | Blockers | Next |
|---|---|---|---|---|
| 2026-08-24 | 0 → 1 | Local monitor confirmed working. Actions workflow written, secrets *believed* added, first manual run green. | Scrape returns empty on runner. Telegram untested in CI. | Commit rewritten check script, run manually, read the debug artifact. |
| 2026-08-24 | 1 → ✅ | Verified all three failure paths in CI (runs #10/#11/#12). Found + fixed a silent Telegram delivery failure. Rotated leaked credentials. Found the page-1 pagination bug. | Scraper reads 6 of 10 matches and is missing live `ZED FC vs Al Ahly FC`. | Decide the `View More` fix, then apply it to BOTH scripts in one commit. |
| 2026-08-25 | 1 → 2 | Fixed pagination in both scripts (`8178263`); scraper reads all 10 fixtures and now tracks `ZED FC vs Al Ahly FC`. Real alert delivered, run #44. Aligned the local monitor with the CI script. Fixed a truncated `TZK_URL` in `.env`. | None blocking. | Phase 2: read `.status` per match, alert on availability rather than on fixture-list changes. |

### Session Notes (Full Detail)

**Session 2026-08-24 — Phase 1**

- `TELEGRAM_BOT_TOKEN` secret initially rejected by GitHub with an alphanumeric-characters
  error. Cause was invisible whitespace or a pasted `KEY=value` pair in the Name field, not the
  name itself. Fix: type the name manually, paste only into the Value field.
- Workflow run #1: manual dispatch, 47s, green. Steps: checkout 1s, setup-python 0s,
  install deps 28s, run check 8s, save state 1s.
- `Run check` output: `No change.`
- `Save updated state` output: `Everything up-to-date` — correct, since the state file was
  byte-identical.
- **Root finding:** `last_seen.json` holds the SHA-256 of the empty string. Verified
  independently. The scraper parsed zero cards on the runner.
- Local `alahly_ticket_monitor.py` was previously confirmed working with real Telegram alerts
  from Cairo. Same selectors, same site, different result → environment difference, not logic.
- Rewrote `alahly_ticket_check.py`: total-card counting to separate "empty" from "broken",
  `wait_for_selector` instead of `networkidle` + fixed sleep, screenshot + HTML dump to
  `debug/` on failure, real User-Agent with `ar-EG` locale and `Africa/Cairo` timezone,
  Arabic normalisation (أ/إ/آ → ا, ى → ي, strip diacritics), `sorted()` before hashing,
  baseline preserved on failure, hourly re-alert instead of every-10-minute spam.
- Rewrote `monitor.yml`: pinned `checkout@v5` / `setup-python@v6`, cached
  `~/.cache/ms-playwright`, `upload-artifact` on failure, `concurrency` group,
  `git pull --rebase --autostash` before push.
- **Neither file committed yet.** That is the next action.

**Session 2026-08-24 (second) — Phase 1 closed, new blocker found**

Goal was to verify the three failure paths. All three now pass, but the session found two
things that mattered more than the tests.

*Starting check.* Runs #5 and #6 (both `schedule`) logged `Parsed 6 match cards, 0 of them Al
Ahly.` A simultaneous local Cairo scrape returned the same six fixtures by name. So the Phase 1
"scraper returns empty" bug was already gone, and the empty-string hash in `last_seen.json` was
a legitimate value, not the poisoned one.

*Test 1, first attempt (run #7).* Widened the Al Ahly predicate to also match `Pyramids` (a
team actually listed) so the NEW/added branch could fire at all — the live list had zero Al
Ahly fixtures, so nothing could ever appear as added. Doctored the baseline with a flipped hash
character plus a fixture that was not live, giving both branches in one run. Result:

```
Parsed 6 match cards, 1 of them Al Ahly.
Telegram alert FAILED: 404 {"ok":false,"error_code":404,"description":"Not Found"}
Change detected -- alert sent.
```

Detection worked. Delivery did not. The script printed "alert sent" anyway, returned 0, and the
job went **green** — the Phase 1 silent-failure pattern relocated from the scrape step to the
notify step.

*Root cause.* `GET /repos/mohaitham22/tazkarti-bot/actions/secrets` returned `total_count: 0`.
No Actions secrets, no environment secrets, no Dependabot secrets. The previous session's log
claimed both were added; they were not. An undefined secret expands to `""`, so the URL became
`api.telegram.org/bot/sendMessage` -> 404. The run log's env group showed
`TELEGRAM_BOT_TOKEN: ` with nothing after the colon, where a real secret would print `***`.

*Fix (`40faf1b`).* `send_telegram()` now returns whether Telegram accepted the message; a
change whose alert was NOT delivered no longer advances the baseline (saving it would make the
next run print `No change.` and lose the alert permanently) and exits non-zero; empty
credentials now fail like missing ones with an actionable message. Mirrored into
`alahly_ticket_monitor.py` per rule 13 — it had the same bug, calling `save_last_hash()`
unconditionally after a failed send. Verified by runs #8 and #9: both red, exit code 2, with
the FATAL text. The identical condition had produced a green job three runs earlier.

*Credential exposure.* While checking why the secrets were missing: `.env` was committed in
`b8ccce9`, the initial commit, and the repo is public. `acbc288` stopped tracking it but did
not remove it from history. `https://raw.githubusercontent.com/mohaitham22/tazkarti-bot/
b8ccce9/.env` returned HTTP 200 with no authentication, exposing `TZK_USERNAME`, `TZK_PASSWORD`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Both were rotated the same day: the old bot token now
returns 401 from `getMe`, and the Tazkarti password differs from the leaked one. History was
deliberately left un-rewritten — rotation is the actual fix. New secrets were then created via
the API, encrypted with the repo public key.

*Test 1, re-run (run #10, commit `ba4f5fa`).* `Parsed 6 match cards, 1 of them Al Ahly.` /
`Telegram alert sent OK.` / `Change detected -- alert delivered.` Scaffold reverted in
`384bb4d`; scraping logic is byte-identical to the pre-test version.

*Test 2 (run #11, commit `85aa510`).* Both `.team-names` occurrences pointed at
`.team-names-nonexistent`. All four assertions passed: red job (exit 1),
`Telegram alert sent OK.` for the warning, `debug-11` artifact at 210 KB, and `last_seen.json`
kept `hash e3b0c442...b855` with `matches: []`, gaining only `consecutive_failures: 1` and
`last_error`. Run #12 then logged `Scraper recovered after 1 failed run(s).`

*Test 3.* Needed no waiting — runs #2, #3, #5, #6, #9 were already `event: schedule`.

*Geo-block hypothesis: DISPROVEN.* The `debug-11` screenshot shows the fully rendered English
matches page from a US Azure runner — six cards, Book Ticket buttons, Available badges. Its
HTML dump contains zero occurrences of `cloudflare`, `captcha`, `Access Denied`, or
country-restriction text. Do not spend any more time on self-hosted runners, an Egyptian VPS,
or fingerprint evasion. Keep that filed only as a contingency if the scrape ever does start
failing from Azure IPs, and the cheapest form of it is running the local script on an
always-on box, not a self-hosted Actions runner.

*The real finding — pagination.* The `debug-11` screenshot showed a `View More` button below
the six matches. Clicking it locally: 6 -> 10 matches, then the button reports disabled. Four
matches have never been scraped by either script, and one of them is
**`ZED FC vs Al Ahly FC`** — a live Al Ahly fixture. The monitor has been quietly reporting
`0 of them Al Ahly` while the exact thing it exists to watch sat on page 2. Not implemented:
the fix needs a decision on click bounds and whether to fold in the `.status` read. See Known
Bug.

*Phase 2 selectors recorded.* Read out of the `debug-11` HTML rather than guessed, as this
file demands. `.status` is the availability badge; observed only as
`<div class="status green"> Available </div>`. See Feature Specs.

**Session 2026-08-25 — pagination fixed, Phase 1 closed for real**

*The fix (`8178263`).* `load_all_pages()` in both scripts clicks `View More` until it is gone
or reports disabled, then parses. Three deliberate choices:

- **Selected by class, not text.** `button.button-blue.width-auto:not(.filter-toggle)`. The
  browser context sets `locale="ar-EG"`, so a text match on "View More" would break the day
  Tazkarti serves Arabic. `:not(.filter-toggle)` is load-bearing: the page has three
  `button-blue` elements and two of them are Search buttons carrying `width-auto` as well.
  Clicking one of those would re-filter the listing rather than extend it. Verified the
  selector resolves to exactly one element on the live page.
- **Bounded at 20 clicks, and the budget running out is an ERROR, not a silent return.** If the
  button is still enabled after 20 clicks we cannot prove we saw the whole list, and a partial
  listing reported as complete is the original bug in a new costume.
- **Stops early if a click adds no cards**, so a button that never disables cannot spin.

*Verified before pushing.* Locally, against the live site: `Parsed 10 match cards after 1
'View More' click(s), 1 of them Al Ahly.` -> `['ZED FC vs Al Ahly FC']`. The guard was tested
by forcing `LOAD_MORE_MAX_CLICKS = 0` in-process, which correctly raised instead of returning
a 6-fixture list. Then in CI, run #44: same line, `Telegram alert sent OK.`,
`Change detected -- alert delivered.` The stored hash `8fbc6677...1e89` matches the value
computed locally before the push.

*Rule 13, enforced rather than promised.* `PAGE_SCRIPT` and the entire pagination block were
copied programmatically from `alahly_ticket_check.py` into `alahly_ticket_monitor.py`, then
both were re-extracted and SHA-compared to confirm byte-identity. Doing it by hand is how they
drifted in the first place.

*What that alignment exposed.* The local monitor was NOT a reference implementation in any
meaningful sense. It used `networkidle` plus a fixed 2s sleep (rule 7 says never), had no
Arabic normalisation (rule 6), and hashed in DOM order without sorting (rule 5). All three are
now fixed by sharing the CI script's code.

*`.env` had a truncated `TZK_URL`.* It read `"https://www.tazkarti.com"` — the homepage, with
no `#/matches` route — so `alahly_ticket_monitor.py`, which is the only script that calls
`load_dotenv()`, was loading a page that has no `.team-names` at all. `env.example` and
`monitor.yml` both carry the correct value; only `.env` was wrong, and the copy committed in
`b8ccce9` has the same truncated value, so it has been wrong since the initial commit.
**This casts real doubt on the Phase 0 claim that the local monitor was "confirmed working
with real Telegram alerts."** With that URL it would scrape nothing every time, hash the empty
string, and never alert. Fixed locally; `.env` is gitignored so there is nothing to commit.
Worth remembering that the CI script survived only because `monitor.yml` sets `TZK_URL`
explicitly and the script's own default is correct.

*Not done, deliberately.* Phase 2 was not folded into this change. The scrape still returns a
list of fixture strings, so adding a per-match `status` stays additive, exactly as the v2 notes
ask.

---

## What We Are Building

A personal notification tool for one fan watching one team. Specifically:

1. **Watches** Tazkarti's public match listing on a timer, using a real headless browser
   because the site is an Angular SPA (`#/matches` is a client-side route — a plain HTTP GET
   returns only the empty shell).
2. **Detects** changes to the Al Ahly fixture set by hashing a normalised, sorted snapshot.
3. **Notifies** via Telegram, with a diff showing what was added or removed.
4. **Pre-fills** the checkout form locally, on demand, and then stops and hands control back
   to the human.

Reads a public page on a timer, the same thing a browser refresh does. Touches no private API.
Does not book, pay, or hold anything.

---

## What NOT to Build

```
❌ Auto-purchase / auto-click "Pay" or "Confirm"     — never, in any phase
❌ CAPTCHA solving or bypass                          — never
❌ Running the prefill helper in CI                   — never (needs a human at the browser)
❌ TZK_USERNAME / TZK_PASSWORD as Actions secrets     — never (public repo, and pointless)
❌ Multiple accounts, proxy rotation, IP cycling      — never
❌ Polling faster than ~5 min                         — someone else's server
❌ Buying for resale                                  — not what this is for
❌ Reselling or publishing the alert feed             — personal tool, keep it personal
❌ A web dashboard / database / user accounts         — a JSON file is the right size
❌ Multi-team support                                 — Al Ahly only until it works for one team
```

The prefill script's docstring already states the payment and CAPTCHA boundaries explicitly.
That boundary is a design decision, not an unfinished TODO. Keep it in the docstring. If a
future session feels tempted to "just finish the automation," that temptation is the thing this
line exists to stop.

---

## Architecture

### Two Runtimes, Deliberately Separate

| | Local (`alahly_ticket_monitor.py`) | CI (`alahly_ticket_check.py`) |
|---|---|---|
| Loop | `while True` + `sleep(30)` | Single run, exits |
| Repeat driver | The script itself | GitHub Actions cron |
| State | `last_seen.json` on disk | `last_seen.json` committed to the repo |
| Secrets | `.env` via `python-dotenv` | Repo Actions secrets |
| Requires terminal open | Yes | No |
| Status | ✅ Known-good reference | ⚠️ Under repair |

**Why both exist:** the local version is the ground truth. When the CI version misbehaves, run
the local one to determine whether the problem is the code or the environment. Do not delete it.

**Keep the scraping logic identical between them.** If a selector or normalisation rule changes
in one, change it in the other in the same commit. A divergence here destroys the whole point of
having a reference implementation.

### Flow

```
GitHub Actions cron (*/10)
  └─> checkout repo (brings last_seen.json)
      └─> headless Chromium -> tazkarti.com/#/matches
          └─> wait for .team-names to render
              ├─ timeout / 0 cards  -> save screenshot+HTML -> Telegram warning -> exit 1
              └─ N cards parsed
                  └─> filter Al Ahly -> sort -> join -> sha256
                      ├─ hash == baseline      -> "No change." -> exit 0
                      ├─ no baseline yet       -> establish it, stay quiet
                      └─ hash != baseline      -> Telegram diff -> exit 0
                          └─> commit last_seen.json back to main
```

The commit-back is how state survives between runs — Actions runners are ephemeral. Pushes made
with `GITHUB_TOKEN` do not re-trigger workflows, so there is no infinite loop.

---

## Project Structure

```
tazkarti-bot/
├── .github/
│   └── workflows/
│       └── monitor.yml              ✅ cron */10 + workflow_dispatch
├── .vscode/                         ✅ editor config
├── alahly_ticket_check.py           ⚠️ CI single-run — rewrite pending
├── alahly_ticket_monitor.py         ✅ local loop — reference implementation
├── alahly_ticket_prefill.py         ⬜ local helper — all selectors TODO
├── get_telegram_chat_id.py          ✅ one-shot setup helper
├── last_seen.json                   ⚠️ committed state — currently empty-string hash
├── env.example                      ✅ template
├── .gitignore                       ✅ must contain .env
├── debug/                           ⬜ created at runtime on failure, NOT committed
└── CLAUDE.md                        ✅ this file
```

---

## State File Schema (`last_seen.json`)

**Current (v1):**
```json
{"hash": "<sha256 hex>"}
```

**Target (v2, in the rewritten script):**
```json
{
  "hash": "<sha256 of sorted, newline-joined fixture list>",
  "matches": ["Al Ahly vs Zamalek", "Pyramids vs Al Ahly"],
  "consecutive_failures": 0,
  "last_error": null,
  "updated_at": "2026-08-24T15:13:00+00:00"
}
```

Rules:
- `matches` exists so alerts can say `+ Al Ahly vs Zamalek` instead of dumping the whole list.
- `hash` is computed over the **sorted** list. Unsorted hashing makes a mere reordering of the
  page look like a change and fires a false alert.
- On scrape failure, `hash` and `matches` are **left untouched** and only
  `consecutive_failures` / `last_error` are updated. Overwriting a good baseline with a failure
  result causes a bogus "change detected" alert the moment the scraper recovers.
- Written with `indent=2` and a trailing newline so git diffs are readable.

---

## Tech Stack (Final — Not Options)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Matches `setup-python` pin |
| Browser automation | Playwright, Chromium | Tazkarti is an Angular SPA; `requests` sees only the shell |
| Notifications | Telegram Bot API via `requests` | Free, instant, no email deliverability problems |
| Scheduler (CI) | GitHub Actions cron | Free, no server to maintain |
| Scheduler (local) | `time.sleep()` loop | Simple, and it is the reference implementation |
| State | JSON committed to the repo | Runners are ephemeral; a DB is overkill for one hash |
| Local secrets | `python-dotenv` + `.env` | Never committed |
| CI secrets | GitHub Actions repository secrets | Telegram credentials only |

Explicitly rejected: Selenium (heavier, no benefit), a database (one hash), Redis, a web UI,
Docker (Actions provides the environment), and email notifications (Telegram is faster and has
no spam-folder failure mode).

---

## Environment Variables

```bash
# ── Monitor (local .env AND GitHub Actions secrets) ──────────────
TZK_URL=https://www.tazkarti.com/#/matches
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_CHAT_ID=<from get_telegram_chat_id.py>

# ── Prefill helper (LOCAL .env ONLY — NEVER in GitHub secrets) ───
TZK_USERNAME=<your Tazkarti account email>
TZK_PASSWORD=<your Tazkarti account password>
TZK_MATCH_URL=<specific match page, filled in after an alert>
TZK_SEAT_CATEGORY=First Class    # optional
TZK_QUANTITY=1                   # optional
```

**Repository Actions secrets (Settings → Secrets and variables → Actions → Secrets tab):**
only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Nothing else. Ever.

Secret names must be alphanumeric or underscore and start with a letter. If GitHub rejects a
valid-looking name, the cause is invisible whitespace or a pasted `KEY=value` pair — type the
name by hand and paste only into the Value field.

---

## Coding Rules

1. **A failed scrape must never be silent.** Empty output and broken output must take different
   code paths. This is the single rule this project exists to remember.
2. **Never overwrite a good baseline with a failure result.** On error, preserve `hash` and
   `matches`.
3. **Fail loudly in CI.** Scrape errors exit non-zero so the job goes red. A green job must
   mean the scraper actually ran.
4. **Save evidence on failure.** Screenshot plus full HTML to `debug/`, uploaded as an
   artifact. You cannot debug a headless browser you cannot see.
5. **Sort before hashing.** Always.
6. **Normalise Arabic before comparing.** `الأهلي`, `الاهلي`, and `الأهلى` are the same team.
   Fold hamza forms to `ا`, `ى` to `ي`, and strip diacritics.
7. **`wait_for_selector`, never `networkidle` + `sleep`.** On an SPA, `networkidle` can resolve
   before Angular paints, and a fixed 2-second wait is a coin flip.
8. **Keep selectors in one place**, with a comment pointing at how to re-derive them from
   devtools. Tazkarti will change its markup eventually.
9. **Never commit `.env`.** Check `.gitignore` before every commit that touches config.
10. **Never put Tazkarti account credentials in GitHub secrets.** Public repo, and the prefill
    helper needs a human at the browser regardless — there is nothing to gain.
11. **Never automate past the checkout boundary.** No auto-pay, no CAPTCHA solving. The
    boundary is deliberate and documented in the prefill docstring; leave that docstring intact.
12. **Be polite to the server.** 10 minutes in CI, 30 seconds locally, single client, no
    parallel requests, no proxy rotation.
13. **Changes to scraping logic land in both scripts in the same commit.**
14. **`[skip ci]` on state commits** so the commit-back never causes surprises.

---

## Feature Specs (Binding)

### Change detection
Compare the SHA-256 of the sorted, newline-joined Al Ahly fixture list against the stored
baseline. Alert on any difference. Do not alert when no baseline exists — establish it silently,
so a fresh clone does not fire a spurious notification on its first run.

### Failure detection
Zero total match cards on the page means failure, not emptiness. Alert on the first failure,
then once per hour (every 6th run at a 10-minute cadence) while it persists. Do not alert every
run — an unfixable notification every 10 minutes trains you to ignore the bot entirely.

### Alert content
Telegram plain text. Show the delta (`+ added`, `- removed`), not the full list. Include the
Tazkarti URL so it is one tap to act. Keep it short enough to read on a lock screen.

### Phase 2 — availability signal (not yet built)
`.team-names` is the wrong element for "tickets are buyable" — it changes only when a fixture
enters or leaves the listing.

**Real selectors, read out of the `debug-11` artifact HTML on 2026-08-24. Not guessed.**

```
.match                       match card root (inside an .ng-star-inserted wrapper)
  .top.clearfix
    .teams
      .team-names            <- what the scrape currently targets
        .team-name.first
        .team-name.second
  .bottom
    .one > .first            metadata label ("Tournament", "Match No.", "Group :")
    .one > .second           metadata value
    .status                  AVAILABILITY BADGE  <- the Phase 2 signal
```

Observed markup: `<div class="status green"> Available </div>`. The colour is a second class
on the same element, so `.status` carries the text and `.status.green` encodes the state.

**Only `green` / `Available` has been observed.** Sold-out and coming-soon variants have never
been seen, so do NOT hardcode a state list — read both the text and the class list, and alert
on the transition rather than on a matched constant.

Also in the markup: the load-more control, `button.button.button-blue.width-auto` with the
text `View More`, which reports `disabled` once the list is exhausted. That button is the
Known Bug at the top of this file.

The booking modal is `#book-ticket-modal`, containing `.book-second-step` and
`.book-ticket-modal-footer`. That is Phase 3 territory and is still unverified.

---

## How to Run (Local Dev)

```bash
# ── FIRST TIME SETUP ─────────────────────────────────────────────
pip install requests playwright python-dotenv
# add --break-system-packages if pip complains about an externally managed environment
playwright install chromium

cp env.example .env
# fill in TZK_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Get your chat ID: message your bot in Telegram FIRST ("hi"), then:
python get_telegram_chat_id.py

# ── DAILY DEV ────────────────────────────────────────────────────
# Run the known-good local monitor (Ctrl+C to stop):
python alahly_ticket_monitor.py

# Run the CI script exactly as Actions runs it:
python alahly_ticket_check.py

# ── DEBUGGING THE SCRAPER ────────────────────────────────────────
# Watch it work. This is the fastest way to see what the runner cannot show you.
# Temporarily set headless=False in the launch() call, then run.

# Reset the baseline (forces the next run to re-establish it):
rm last_seen.json

# Force an alert, to test the Telegram path end-to-end:
# edit last_seen.json and change one character of the hash, then run.
```

---

## How to Deploy (GitHub Actions)

**Already done:**
- `.github/workflows/monitor.yml` committed with `cron: "*/10 * * * *"` + `workflow_dispatch`
- `permissions: contents: write` so the job can commit `last_seen.json` back
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` added as repository secrets

**To verify a run:**
1. Actions tab → **Al Ahly Tazkarti Monitor** → **Run workflow**.
2. Click into the run → **check** in the left sidebar.
3. Expand **Run check**. The summary page only shows that the job finished — it does not show
   output. Note that collapsed line-number gaps (`1` then `13`) hide the grouped step output;
   click the triangle to expand.
4. If it failed, download the `debug-N` artifact from the run summary and open the PNG. That
   screenshot distinguishes a bot challenge from a geo-block from changed markup in one glance.
5. Check **Save updated state**. `Everything up-to-date` means the state file did not change —
   correct when nothing moved, suspicious when you expected a change.

**Acceptance criteria for Phase 1 being genuinely done — all four:**
- [x] A run parses more than zero total match cards — run #12, `Parsed 6 match cards`
- [x] A deliberately broken baseline produces a real Telegram message — run #10,
      `Telegram alert sent OK.` / `Change detected -- alert delivered.`
- [x] A deliberately broken selector produces a red job plus a debug artifact — run #11,
      exit 1 plus `debug-11` (210 KB, PNG + HTML), baseline preserved
- [x] A scheduled (not manual) run appears in the Actions tab — runs #2, #3, #5, #6, #9

- [x] The scrape sees every match on the page, not just the first — run #44,
      `Parsed 10 match cards after 1 'View More' click(s)`, matching a local click-through

**The fifth criterion exists because the first four all passed while the scraper was reading 6
of 10 fixtures and missing the only Al Ahly match on the site. When adding a phase, ask what a
passing suite would still fail to notice, and write that down as a criterion.**

---

## v2+ Future Enhancements (Do NOT Build Now)

| Enhancement | Design consideration for today |
|---|---|
| Ticket-availability signal instead of fixture-list | Phase 2. Keep the scrape function returning a structured list, not a string, so adding a `status` field per match is additive. |
| Self-hosted runner in Egypt | The fallback if the geo-block hypothesis is confirmed. A Raspberry Pi or a cheap always-on box running the *local* script is simpler than a self-hosted Actions runner — prefer it. |
| Multiple teams | Filter predicate is already isolated in the page script. Make it a list of patterns, not a hardcoded one. |
| Per-match alert routing | Telegram supports multiple chat IDs. `CHAT_ID` would become a comma-separated list. |
| Alert deduplication | If cron drift causes double runs, the hash comparison already makes repeats harmless. Revisit only if it proves otherwise. |
| Playwright stealth / fingerprint evasion | Only if a debug screenshot actually shows a bot challenge. Do not add speculatively — and if the site is deliberately blocking automation, the honest answer is to stop, not to escalate. |
