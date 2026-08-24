# Al Ahly Tazkarti Monitor — Claude Code Context

## TL;DR
A personal ticket-availability watcher. Polls Tazkarti's public match listing with headless
Playwright, detects when the Al Ahly fixture list changes, and pushes a Telegram message.
A separate local-only helper pre-fills the checkout form up to — but never past — the point
where a human must take over.

Stack: Python 3.12 + Playwright (Chromium) + Telegram Bot API + GitHub Actions (cron).
No server, no database, no web UI. State is a single JSON file committed back to the repo.

**Phase 0 done (local monitor confirmed working). Phase 1 in progress — Actions migration runs
green but the scraper returns EMPTY on GitHub's runners. See Known Bug below before doing
anything else.**

Repo: `mohaitham22/tazkarti-bot` — **PUBLIC**. Every rule about secrets in this file follows
from that one fact.

---

## Phase Roadmap — Read This First

```
Phase 0  ✅ DONE         Local monitor: Playwright scrape + hash diff + Telegram alert.
                         Confirmed working — real alerts received on hash change.
Phase 1  ⚠️ IN PROGRESS  GitHub Actions migration so the monitor runs without a terminal open.
                         Workflow runs green. Scrape returns empty on the runner. BLOCKED.
Phase 2  ⬜ NOT STARTED  Change the signal from "fixture list changed" to "tickets are buyable".
Phase 3  ⬜ NOT STARTED  Pre-fill helper: replace TODO selectors with Tazkarti's real ones.
```

**Do NOT start Phase 2 until Phase 1 is proven — a scraper that returns nothing cannot be
taught to detect a better signal.**
**Do NOT start Phase 3 until Phase 2 gives a usable per-match URL to open.**
**Phase 3 is LOCAL ONLY and never runs in CI. See Coding Rules.**

---

## ⚠️ Known Bug — Fix This Before Any New Feature

`last_seen.json` currently contains:

```json
{"hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
```

That is the SHA-256 of the **empty string**. `fetch_al_ahly_matches()` returned `""` — the
GitHub runner parsed zero match cards.

**Why this is worse than a normal bug:** the original code cannot distinguish "no Al Ahly
fixtures listed" from "the scrape broke." Both produce `""`. And because the stored baseline
*is* the empty hash, a permanently broken scraper prints `No change.` on every run, exits 0,
and the Actions job stays green forever. Silent failure with a green checkmark.

**Leading hypothesis:** the local monitor works from a Cairo residential IP; GitHub runners are
US Azure datacenter IPs. Tazkarti is an Egyptian ticketing site and plausibly geo-restricts,
bot-challenges, or serves a different shell to datacenter ranges. Headless Chromium's default
User-Agent also contains the literal string `HeadlessChrome`, which is the single easiest bot
signal to filter on.

**Competing hypothesis:** there genuinely were no Al Ahly fixtures listed at that moment. Both
hypotheses produce byte-identical output, which is exactly the design flaw.

**How to tell them apart:** count *every* match card on the page, not only the Al Ahly ones.

| Total cards | Al Ahly cards | Meaning | Action |
|---|---|---|---|
| 0 | 0 | Page never rendered | Alert + exit 1 + save evidence |
| N > 0 | 0 | No Al Ahly fixtures right now | Normal. Stay quiet. |
| N > 0 | M > 0 | Working | Diff against baseline |

A rewritten `alahly_ticket_check.py` implementing this — plus screenshot/HTML evidence capture,
Arabic normalisation, sorted hashing, and refusal to overwrite the baseline on failure — has been
drafted but **is not yet committed**. Committing and running it is the next action.

---

## Current State

### What exists

| File | Status | Notes |
|---|---|---|
| `alahly_ticket_monitor.py` | ✅ Working | Local looping version. `POLL_SECONDS = 30`. Confirmed sending real Telegram alerts. This is the reference implementation — it is known-good. |
| `alahly_ticket_check.py` | ⚠️ Runs, wrong result | Single-run CI version. Green in Actions but scrapes empty. Rewrite drafted, not committed. |
| `alahly_ticket_prefill.py` | ⬜ Skeleton | Every selector is a `TODO` placeholder. Never run for real. Login/seat/quantity/add-to-cart selectors all fabricated. |
| `get_telegram_chat_id.py` | ✅ Working | One-shot helper. Reads `getUpdates`, prints chat IDs. Already served its purpose. |
| `.github/workflows/monitor.yml` | ⚠️ Runs, needs pins | `cron: */10`, `contents: write`, state commit-back all correct. Emits a Node 20 deprecation warning. |
| `last_seen.json` | ⚠️ Poisoned | Contains the empty-string hash. See Known Bug. |
| `env.example` | ✅ Exists | Note: docstrings in the scripts refer to `.env.example` (leading dot). The repo file is `env.example`. Harmless inconsistency, but pick one. |

### Verified working
- Telegram bot token + chat ID are valid — proven by local runs in Phase 0.
- Playwright + `.team-names` / `.team-name.first` / `.team-name.second` selectors are correct
  **from a Cairo residential IP**.
- Actions workflow syntax, `contents: write` permission, and the commit-back step all function.
  "Everything up-to-date" was correct behaviour — the state file genuinely had not changed.

### Not yet verified
- **Telegram delivery from inside Actions.** Every CI run so far hit the `No change.` branch,
  which never touches `send_telegram()`. The notification path is completely untested in CI.
- Whether the scheduled cron actually fires (only `workflow_dispatch` runs have happened).
- Whether Tazkarti is reachable at all from a GitHub runner.

### Standing Blockers

- **Scraper returns empty on GitHub runners** — the Phase 1 blocker. Diagnose with the debug
  artifact (screenshot + HTML) before writing any more code.
- **Node 20 deprecation warning** — `actions/checkout@v4` and `actions/setup-python@v5` are
  forced onto Node 24. Cosmetic today, breaking eventually. Fix: pin `checkout@v5` and
  `setup-python@v6`.
- **Signal is wrong for the stated goal** — `.team-names` detects fixtures being added or
  removed from the listing. Tickets opening for an *already-listed* match changes nothing in
  that element, so no alert fires. This is Phase 2.
- **Scheduled workflows are disabled after 60 days of repository inactivity.** State commits
  only happen when the listing changes. A quiet off-season could silently switch the monitor
  off with no notification. Mitigation: touch the repo periodically, or accept it and re-enable
  manually before a big fixture window.
- **GitHub cron drift** — `*/10` is a request, not a promise. Under load, real intervals are
  frequently 20–40 minutes. Do not design anything that assumes 10-minute precision.
- **Prefill selectors are fabricated** — `#username`, `#password`, `#login-button`,
  `#seat-category`, `#quantity`, `#add-to-cart` were all invented as placeholders. None have
  been verified against Tazkarti's real DOM.

---

## ⚠️ SESSION MEMORY PROTOCOL — READ THIS AT THE START OF EVERY SESSION

**This section is the handoff between sessions. Read it before writing a single line of code.**

### How to Start Every New Session
1. Read this entire CLAUDE.md top to bottom.
2. Read the Known Bug section — if it is still present, that is the work.
3. Find the last row in the Session Log — that is where we left off.
4. Check the current contents of `last_seen.json` in the repo. Compare against
   `e3b0c442...b855` (empty-string hash). If it still matches, the scraper is still broken.
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
| 2026-08-24 | 0 → 1 | Local monitor confirmed working. Actions workflow written, secrets added, first manual run green. | Scrape returns empty on runner. Telegram untested in CI. | Commit rewritten check script, run manually, read the debug artifact. |

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
`.team-names` is the wrong element for "tickets are buyable." The right signal is the per-match
status control: the buy button's label, its disabled state, or a sold-out / coming-soon badge.
**Do not guess these selectors.** Get them from the `debug/*.html` artifact or from devtools on
a live match page, then write them down here.

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
- [ ] A run parses more than zero total match cards
- [ ] A deliberately broken baseline produces a real Telegram message
- [ ] A deliberately broken selector produces a red job plus a debug artifact
- [ ] A scheduled (not manual) run appears in the Actions tab

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
