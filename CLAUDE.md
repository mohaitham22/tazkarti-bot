# Al Ahly Tazkarti Monitor — Claude Code Context

## TL;DR
A personal ticket-availability watcher. Polls Tazkarti's public match listing with headless
Playwright, detects when the Al Ahly fixture list changes, and pushes a Telegram message.
A separate local-only helper opens a visible browser that remembers your login and types your
credentials into the login form — then stops. You click Sign in and solve the CAPTCHA yourself.

Stack: Python 3.12 + Playwright (Chromium) + Telegram Bot API + GitHub Actions (cron).
No server, no database, no web UI. State is a single JSON file committed back to the repo.

**Phases 0, 1, 2 and 4 are DONE. The monitor reads the entire listing and now alerts on
`matchStatus` — "tickets are buyable" — rather than on the fixture list changing. It currently
tracks `ZED FC vs Al Ahly FC` (matchStatus 1, AVAILABLE), and runs twice over: a 30-second
local loop for latency and a `*/5` CI job as the backstop. There is no blocking bug. A
Phase 2 alert has been delivered to Telegram for real; the outstanding Phase 4 item is reboot
recovery, which needs an actual reboot.**

**Phase 3 is DONE, at a deliberately reduced scope agreed 2026-08-25. Tazkarti's login is
behind an invisible reCAPTCHA v2 whose token is a REQUIRED field of the login API call, so
automating login is impossible without solving a CAPTCHA, which rule 11 forbids. Rather than
chase it, the helper was cut down to one job: open a visible browser on a PERSISTENT profile
that remembers the session, and type the credentials in. The human clicks Sign in and solves
the CAPTCHA. Seat/quantity/add-to-cart automation was DELETED, not deferred — see the v2 table
for why it is low-value, and do not re-add it.**

Repo: `mohaitham22/tazkarti-bot` — **PUBLIC**. Every rule about secrets in this file follows
from that one fact.

---

## Phase Roadmap — Read This First

```
Phase 0  ✅ DONE         Local monitor: Playwright scrape + hash diff + Telegram alert.
                         Confirmed working — real alerts received on hash change.
Phase 1  ✅ DONE         GitHub Actions migration so the monitor runs without a terminal open.
                         All four acceptance criteria proven. Runs #10/#11/#12, 2026-08-24.
Phase 2  ✅ DONE         Signal is now each fixture's raw matchStatus, not the fixture list.
                         Verified against the live site 2026-08-25, and a Phase 2 alert has
                         since been delivered to Telegram from the local runner.
Phase 3  ✅ DONE (cut)   Login pre-fill helper, rescoped. Persistent browser profile keeps the
                         session; the script fills the two login fields and stops. It never
                         submits — invisible reCAPTCHA v2 makes that impossible, so the human
                         clicks Sign in. Seat/quantity/cart code DELETED, not deferred.
                         Verified live 2026-08-25 for LOGGED OUT and SESSION EXPIRED; the
                         LOGGED IN path needs a human CAPTCHA solve and is unproven.
Phase 4  ✅ DONE         Always-on local runner. alahly_ticket_monitor.py now runs under
                         Windows Task Scheduler at 30s, with its own state file, browser-crash
                         recovery, sustained-failure alerting and a rotating log. Verified
                         2026-08-25. Reboot recovery is the one unobserved criterion.
```

**Why Phase 4 exists, and why it outranks Phase 3.** Tazkarti runs a virtual queue for
high-demand matches, and **queue position is assigned by arrival time**. That makes alert
latency the only variable worth optimising: a pre-filled form does not move you up a queue,
arriving 40 minutes earlier does. Observed GitHub cron drift is 8–45 minutes, which is the
entire drop window — so the CI job cannot be the fast signal no matter how it is tuned.

**The two runners are a division of labour, not redundancy. Keep both.**

| | GitHub Actions, `*/5` requested | Local loop, 30s |
|---|---|---|
| Job | Slow signal: "a match opened for booking" | Fast signal: the actual drop |
| Drift tolerance | Hours of slack, drift irrelevant | Seconds matter |
| Hardware | None | One always-on machine |
| Fails when | Rarely; it is the backstop | The machine sleeps, travels, or loses power |

The CI job is what makes the local runner's failure survivable: if the laptop is asleep you
degrade to the CI signal, you do not go blind. That is the entire reason not to delete
it once the local runner is up.

**A PER-MATCH URL DOES NOT EXIST. Confirmed live 2026-08-25 — do not go looking for it again.**
Earlier versions of this file speculated that `TZK_MATCH_URL` could be derived from the feed's
`matchId` (Al Ahly's is 2559). It cannot. The route table in the bundle has no `matches/:id`;
match cards contain **zero anchors**; "Book Ticket" is a `<button>` with no href that opens a
modal (`#book-ticket-modal`) on the listing itself, and the app returns to `/matches` when done.
Clicking it while logged out navigates to `#/login`, not to any match page. So
`https://www.tazkarti.com/#/matches` is the best link that exists, which is what the Telegram
alert already sends and what `TZK_MATCH_URL` correctly defaults to. (`detail/:id` in the bundle
is Angular's own `HeroDetailComponent` tutorial boilerplate inside an error string, not a
Tazkarti route — it is a trap, not a lead.)
**Phase 3 is LOCAL ONLY and never runs in CI. See Coding Rules.**
**Phase 3 step 1 is DONE — the login selectors are real and verified. Steps 2–4 (submit login,
navigate to the match, add to cart) are all downstream of a login that cannot be automated, so
none of them can proceed until the scope decision is made.**

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
| `alahly_ticket_check.py` | ✅ Verified locally, CI run pending | Source of truth for the shared block. Parses the FULL listing, reads raw `matchStatus`, detects availability change, alerts, fails loudly, preserves the baseline on failure, recovers. |
| `alahly_ticket_monitor.py` | ✅ Trustworthy reference | Local loop, `POLL_SECONDS = 30`. Shared block copied by `sync_shared_block.py` and SHA-verified identical. Four consecutive polls verified locally. |
| `sync_shared_block.py` | ✅ New, working | Enforces rule 13 mechanically. `python sync_shared_block.py` copies the block from the check script into the monitor; `--check` verifies and exits 1 on drift. Run `--check` before committing. |
| `alahly_ticket_prefill.py` | ✅ Rewritten and RUN for real | Login pre-fill only, and that is the finished scope. `launch_persistent_context` on a profile outside the repo; real `name`-based selectors; reports LOGGED IN / SESSION EXPIRED / LOGGED OUT; fills both fields and verifies the round-trip; **never submits**. Credentials read lazily, so the logged-in case needs none. No fabricated selectors and no TODOs remain. Carries its own RUNBOOK. |
| `get_telegram_chat_id.py` | ✅ Working | One-shot helper, purpose served. |
| `.github/workflows/monitor.yml` | ✅ Working | `cron: */5` (the floor GitHub allows), `contents: write`, `checkout@v5` / `setup-python@v6`, Playwright cache, artifact upload on failure, concurrency group. Node 20 warning gone. |
| `last_seen.json` | ✅ Migrated to v3 | `{hash: a086020c...66c5, matches: [{match_id: 2559, fixture: "ZED FC vs Al Ahly FC", status: 1, ...}]}`. `matches` is now a list of OBJECTS, not strings, and the hash covers `matchStatus`. Not comparable with any pre-2026-08-25 hash. |
| `env.example` | ✅ Exists | Docstrings say `.env.example`; the repo file is `env.example`. Harmless. |
| `install_local_monitor_task.ps1` | ✅ New, working | Registers the always-on Task Scheduler job. Idempotent — re-run it to apply changes. Header documents the Task Scheduler vs NSSM decision. |
| `%LOCALAPPDATA%\tazkarti-monitor\` | ✅ New | The local runner's private working dir, **outside the repo and outside OneDrive**: `last_seen_local.json`, `monitor.log` (+5 rotations), `debug/`, `last-start-ping`, and since Phase 3 `browser-profile/` — the prefill helper's Chromium profile, which holds a **live session token**. Same OneDrive reasoning as the state file, only more so: a Chromium profile is large and rewritten constantly. |

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

- ~~**A Phase 2 alert actually arriving in Telegram.**~~ **RESOLVED 2026-08-25.** Delivered
  from the local runner: `Change detected -- sending Telegram alert...` / `Telegram alert sent
  OK.` at 22:25:37, by doctoring the tracked fixture's `status` to `4` in
  `last_seen_local.json`. Doing this is now risk-free — the local and CI baselines are separate
  files, so the test cannot disturb the CI baseline the way it would have before.
- **Reboot recovery of the local runner.** The At-log-on trigger is registered and the
  1-minute watchdog is proven to start the task from cold, but **no reboot has been
  performed** — deliberately, it is not mine to trigger on a machine that is currently
  watching. Verify it: reboot, log in, wait ~2 minutes, expect a `✅ Local Tazkarti watcher
  started` Telegram message.
- ~~**Phase 2 running in CI at all.**~~ **RESOLVED 2026-08-25.** It has been running unattended
  for hours. `origin/main`'s `last_seen.json` is v3 with object entries, `hash a086020c641a`,
  `consecutive_failures: 0`, `last_error: null`, tracking
  `{match_id: 2559, fixture: "ZED FC vs Al Ahly FC", status: 1, status_label: "AVAILABLE"}`.
  **The hash independently matches the value the local runner computed** — two different
  machines, two different code paths, same 64 hex characters, which is far stronger evidence
  than a green job. Note the local clone can be many commits behind: `git fetch` before
  concluding anything about CI from `git log`. A quiet local `git log` is not a quiet CI.
- **matchStatus values 2, 3 and 4 in the wild.** Every fixture on the site has been `1` the
  whole time. The vocabulary is not guesswork — it was read out of Tazkarti's own compiled
  template and i18n files (see Feature Specs) — but no transition has ever been *observed*.
  This is why the hash covers the raw integer: an unrecognised value still moves it.
- **The `*/5` schedule actually running in CI.** The cron was changed 2026-08-25 but no
  scheduled run has happened on it yet. Confirm from the Actions tab that runs are arriving as
  `event: schedule`, and note the REAL gaps between them — if they still cluster at 8–45
  minutes, that is the drift blocker, not a broken schedule, and nothing is wrong with the
  config. Also worth one glance: `FAILURE_REALERT_EVERY = 12` has never fired at the new cadence.
- **Being signed in on the PHONE.** Nothing in this repo can do this and nothing tests it. The
  alert links to `#/matches`, and Book Ticket there goes to `#/login` if that browser has no
  session — verified live. Sign in once in your phone's browser so a drop alert is one tap.
  This is the single highest-value manual step left, and it is worth more than any code here.
- **The prefill helper's LOGGED IN path.** `LOGGED OUT` and `SESSION EXPIRED` were both verified
  against the live site 2026-08-25. `LOGGED IN` cannot be reached without a real sign-in, which
  needs a human CAPTCHA solve, so it has never executed. Verify it by running
  `python alahly_ticket_prefill.py`, signing in for real, pressing Enter, then running it a
  second time: expect `Status:  LOGGED IN` and `Already signed in as <your name>`. **Until that
  is done, "the session persists across runs" is proven for a planted token but not for a real
  one.**

### Standing Blockers

- ~~**Signal is fixture-list, not availability**~~ — RESOLVED 2026-08-25 by Phase 2. The hash
  now covers each fixture's raw `matchStatus`.
- **Team identity depends on a hardcoded id.** `AL_AHLY_TEAM_ID = 77`. If Tazkarti ever
  reissues it, the id test stops matching — the name test is kept as a fallback precisely so
  that failure is noisy rather than silent, but the fallback is also what makes `NBE Club`
  match, so `DECOY_TEAM_IDS` has to stay accurate. If a fixture you don't care about starts
  showing up in alerts, add its team id there.
- **The availability signal depends on a second, undocumented source.** `matchStatus` comes
  from `/data/matches-list-json.json`, which Tazkarti can rename or restructure independently
  of the page's markup. The script refuses to fall back to the badge text when the feed is
  missing (it raises), so this fails loudly — but it is a new dependency the DOM-only version
  did not have.
- **`.env` was committed to PUBLIC history.** Commit `b8ccce9` contains a real `.env` with
  `TZK_USERNAME`, `TZK_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Removing it in
  `acbc288` did not remove it from history — the blob still returns HTTP 200 with no auth.
  **Both credentials were rotated 2026-08-24**: the old bot token now returns 401, and the
  Tazkarti password was changed. History was deliberately NOT rewritten — rotation is the real
  fix, and GitHub can retain unreachable blobs anyway. Never treat anything in `.env` as
  having been private.
- **Every run commits `last_seen.json`** — `updated_at` changes even when nothing else does,
  so the state commit lands on every run rather than only on change. Side effect: ~288 bot
  commits/day at `*/5` (was ~144 at `*/10`). Upside: it keeps the repo active, which defuses the 60-day
  scheduled-workflow shutoff below. Fix, if it ever annoys: only write when `hash` or
  `consecutive_failures` changes.
- **Scheduled workflows are disabled after 60 days of repository inactivity.** Currently
  defused by the commit-every-run behaviour above. If that is ever "fixed", this comes back.
- **GitHub cron drift** — `*/5` is a request, not a promise. Scheduled runs are best-effort and
  GitHub delays or skips them under load. The interval is the floor, the drift is the ceiling,
  and the drift is why the local 30s runner exists. Do not read `*/5` as "a 5-minute signal".
  **Measured 2026-08-25 from the state-commit timestamps on `origin/main`, at `*/10`:**

  ```
  17:45 -> 18:16 -> 19:03 -> 19:42 -> 20:05
   gaps:   31min    47min    39min    23min
  ```

  That is GitHub already ignoring a 10-minute request by 3-5x. It is the single clearest
  argument for why the local runner is not redundant, and for why tightening the cron is close
  to cosmetic. `git log origin/main --format="%ad %s" --date=format:"%H:%M"` regenerates this.
- ~~**Prefill selectors are fabricated**~~ — RESOLVED 2026-08-25. The three login selectors are
  real, verified live, and now written into the script. The other three — `#seat-category`,
  `#quantity`, `#add-to-cart` — were **deleted along with the code that used them**, so there
  are no fabricated selectors left in the repo. See the v2 table before rebuilding them.
- **🚧 PHASE 3 BLOCKER: Tazkarti's login cannot be automated — invisible reCAPTCHA v2.**
  *Symptom:* the login form at `#/login` renders `<re-captcha size="invisible"
  id="ngrecaptcha-0">` (sitekey `6LcgZfUsAAAAAAji0eMKvFPicrHdkNbPQ9gneFJo`) between the
  password field and the Sign in button, with the `bframe` challenge iframe preloaded. It is
  not decorative: in `main.57e770ff8543ee8f6d96.js` the API call is
  `this._http.post(url+"Login", {Username:e, Password:n, recaptchaResponse:t})` — the token is
  a required field — and the Sign in button's click handler is `recaptchaRef.execute()`, not a
  submit. Login only fires from reCAPTCHA's own callback:
  `resolved: function(e,n){ this.recaptchaResponse=e, e ? (this.submitted=!0, this.submitLogin(n)...`
  So there is NO code path to a session without a Google-issued token.
  *Fix path — AGREED AND IMPLEMENTED 2026-08-25, so this is now a documented constraint rather
  than an open blocker.* Do not chase the CAPTCHA. Solving or bypassing it is forbidden by rule
  11, and relying on the invisible challenge silently passing a headless browser's risk score is
  the kind of thing that works in testing and fails on the morning tickets actually drop. The
  helper now uses `launch_persistent_context()` with a dedicated user-data dir: the human signs
  in by hand in that window — CAPTCHA and any OTP included — the session persists in the
  profile as `localStorage["ETMS-Token"]`, and later runs reuse it and skip login entirely.
  **The script never submits the login form, by design.** Anything that would change that is
  out of bounds.
- **⚠️ THE ALWAYS-ON MACHINE IS A LAPTOP. This is the local runner's real failure mode.**
  `Mohamed` is a Dell G15 5511 — chassis type 10, `PCSystemType 2`, i.e. a notebook with a
  battery. Measured 2026-08-25, it behaves like a desktop *in its current configuration*:
  wired Ethernet, on AC, **sleep-after on AC = Never**, hibernate on AC = Never, 8 days of
  uptime, and the Kernel-Power log shows only 2–11 **second** sleep blips over 14 days — no
  overnight sleeps at all. But the configuration is the only thing holding that up:
  - **On battery, sleep-after is 5 minutes** (`DC index 0x12c`). Unplug it and the 30s watcher
    is gone within five minutes of going idle.
  - Its only sleep state is **S0 Low Power Idle (Modern Standby)**, which throttles desktop
    processes rather than announcing a clean suspend.
  - The task runs as the logged-on user, so it also stops if you sign out.
  A sleeping 30-second poller is **worse than the CI job**, because it looks healthy
  while delivering nothing. Two things exist specifically to stop that becoming false
  confidence: the **daily heartbeat** (`TZK_HEARTBEAT_HOURS`, absence is the symptom) and
  **keeping the CI job**, which degrades you to a slow-but-real signal instead of to zero. If this
  machine starts travelling, move the runner to a Raspberry Pi or a cheap always-on box —
  running this same local script there is much simpler than a self-hosted Actions runner.
- **The local runner restarts on a ~60s watchdog, so restart latency is not zero.** A crash
  costs up to a minute of blindness, plus a few seconds of Chromium start-up. Acceptable
  against 8–45 minutes of cron drift, but it is not "instant" and should not be described that
  way.
- **A start-up Telegram ping is rate-limited to one per 10 minutes.** If the script ever
  crash-loops you get ONE message, not sixty an hour. The trade-off is that a genuine restart
  within 10 minutes of a previous one is silent — the log line
  `Skipping the start-up ping` is where that is recorded.
- ~~**`load_state()` swallowed every read error**~~ — FIXED 2026-08-25. It used to `return {}`
  on any exception, which callers cannot distinguish from "no baseline yet", so a corrupt file
  silently re-established the baseline and threw away the alert about to fire. It now warns,
  preserves the file as `.corrupt`, and reads `utf-8-sig` so a BOM is not fatal. `save_state()`
  writes to a temp file and `os.replace()`s it, so a crash mid-write cannot truncate the
  baseline — which matters much more now that something rewrites it 2,880 times a day.
- **Login may also be behind an OTP — UNKNOWN, not ruled out.** `main.57e770ff8543ee8f6d96.js`
  contains `id="btn_sendOTP"`, itself also gated behind `recaptchaRef.execute()`. Whether the
  *login* flow triggers it cannot be determined without submitting the form, and submitting is
  blocked by the reCAPTCHA above. If it does, it is a second, independent reason the login step
  cannot be automated — and the persistent-profile rescope handles both at once.

## ⚠️ SESSION MEMORY PROTOCOL — READ THIS AT THE START OF EVERY SESSION

**This section is the handoff between sessions. Read it before writing a single line of code.**

### How to Start Every New Session
1. Read this entire CLAUDE.md top to bottom.
2. Read the Known Bug section — if it is still present, that is the work.
3. Find the last row in the Session Log — that is where we left off.
4. Check `last_seen.json`. `matches` should be non-empty and its entries should be OBJECTS
   carrying an integer `status`. If they are plain strings, the state is pre-Phase-2 and the
   next run will silently re-baseline. If `hash` is `e3b0c442...b855` — the SHA-256 of the
   empty string — the scrape is returning nothing; treat that as broken until the run log's
   card count proves otherwise.
   Also run `python sync_shared_block.py --check`; if it reports drift, fix that first.
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
| 2026-08-25 | 2 → ✅ | Phase 2 built. Signal is now the raw `matchStatus` from the page's own JSON feed, not `.team-names`. Structured state (v3), transition-aware alert wording, DOM/feed cross-check. Fixed two bugs found by testing: `NBE Club` tracked as Al Ahly, and the SPA never reloading between polls. Added `sync_shared_block.py` to enforce rule 13 mechanically. | Phase 2 alert not yet delivered to Telegram; not yet run in CI. | Force one alert to prove delivery, watch the first scheduled CI run, then Phase 3. |
| 2026-08-25 | 4 ✅ | Promoted the local monitor to an always-on 30s runner under Task Scheduler. Separate state file, browser-crash recovery, sustained-failure alerting, rotating log, atomic + loud state I/O. Delivered the first-ever Phase 2 alert to Telegram. | Machine is a laptop — always-on only while on AC + Ethernet. Reboot recovery not observed. | Reboot once, confirm the `✅ started` ping arrives. Then Phase 3's scope decision. |
| 2026-08-25 | 3 🚧 | Phase 3 step 1 only. Dumped the real login DOM and replaced three of the six fabricated selectors with verified ones (`input[name="txtFanId"]`, `input[name="txtPassword"]`, `form button.button-green`). Ran a visible fill with no submit — both fields round-tripped. Then STOPPED: login is gated by an invisible reCAPTCHA v2 that is a required field of the login API. No project code changed. | Login cannot be automated (reCAPTCHA v2, required token). OTP after login unknown. `TZK_MATCH_URL` still points at the listing, not a match page. | Get the user's decision on the persistent-profile rescope. If yes, rewrite the prefill helper around `launch_persistent_context()` and delete the login block, then confirm the per-match URL shape from `matchId` 2559. |
| 2026-08-25 | 3 ✅ / CI | Chased the per-match URL to a definitive NEGATIVE: it does not exist, so the alert's existing link is already optimal. Cut CI cron `*/10` → `*/5` (GitHub's floor) and doubled `FAILURE_REALERT_EVERY` 6 → 12 to keep failure nudges hourly. | `*/5` does not mean a 5-minute signal — drift is unchanged. State commits now ~288/day. | Sign in once for real to prove the prefill LOGGED IN path; sign in on the PHONE so the alert link is one tap; reboot for the Phase 4 criterion. |
| 2026-08-25 | 3 ✅ | Rescope AGREED and built. `alahly_ticket_prefill.py` rewritten: persistent profile, login pre-fill only, never submits. Deleted seat/quantity/add-to-cart entirely. Re-verified the login selectors live. Found that the session token is **localStorage**, so the profile really does persist a login. Ran it for real — LOGGED OUT and SESSION EXPIRED both verified against the live site. | LOGGED IN path unproven (needs a human CAPTCHA solve). `TZK_MATCH_URL` still the listing, not a match page. | Sign in once for real to prove the LOGGED IN path and confirm the session survives a restart. Then reboot the machine for the outstanding Phase 4 criterion. |

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
  baseline preserved on failure, hourly re-alert instead of every-run spam.
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

**Session 2026-08-25 (second) — Phase 2 built**

*The instruction that shaped the design.* The first proposal was to read the `.status` badge,
map its text to a canonical token (`AVAILABLE`, `COMING_SOON`, …) and hash the token. That was
rejected for a good reason: **hash the raw value, not a token derived from it.** If Tazkarti
adds a `matchStatus 5` and the mapping funnels unknowns into an existing token, the hash never
moves and the monitor goes quiet on a state it did not recognise — the empty-hash bug wearing a
different hat. This is now rule 15.

*Which forced a better source.* `matchStatus` **is not in the DOM**. The badge only ever
carries a colour class and a translated label, both derived from it. Chasing the raw value
turned up that the listing page fetches its own data from the public static file
`/data/matches-list-json.json`, and renders the cards from it. The script now captures the
response the page already requested (`page.on("response")`, registered before `goto()`), so it
makes no extra request — rule 12 intact. That payload also carries `matchId`, which is a
better identity than the fixture string and is what Phase 3 needs.

*Selectors were read, never guessed.* The full rendered page was dumped to
`debug/phase2-full.html` and each `.match` card to `debug/phase2-cards.json`. The status
vocabulary came out of the compiled Angular bundle `8.7c7ab3ab9f9641d7d4c4.js` plus
`assets/i18n/{en,ar,fr}.json` — all four values, in three languages, in the Feature Specs
table. The Book Ticket button was examined and rejected: its colour class is static, and its
`disabled` depends on login state and a transient `startBooking` flag.

*The noise the brief warned about was real.* Two of the twelve `.match` elements are hidden
virtual-queue templates carrying `Last update time : 05 : 07 PM`. Sampled a minute apart it
read `05 : 12` then `05 : 13`. Hashing card text wholesale would have alerted on every run.
They are excluded by skipping cards with blank team names.

*Bug found by testing, #1 — `NBE Club` tracked as an Al Ahly fixture.* Reading the JSON meant
reading Arabic team names for the first time, and `NBE Club` is `نادى البنك الاهلى المصرى` —
the National Bank of Egypt. `الاهلى` is just the Arabic for "national", so it matches any
reasonable "al ahly" pattern. A test asserting the fixture count caught it returning 2 where
there should be 1; reading the code would not have. Fixed by matching `teamId 77` first, with
the name test kept only as a fallback so a reissued id is noisy rather than silent, and
`DECOY_TEAM_IDS = {171: NBE}` to stop the fallback firing. Now rule 16.

*Bug found by testing, #2 — the local monitor never actually reloaded.* Running the loop for
more than one poll produced `The page never fetched 'matches-list-json'` on polls 2+.
`TZK_URL` is a hash route, so `page.goto()` to the identical URL is a **same-document
navigation**: no page load, Angular never re-bootstraps, the feed is never re-fetched. The
monitor reuses one page across polls, **so every poll after the first was re-reading the DOM
left over from the first one.** This is pre-existing and predates Phase 2 — the old monitor
would have printed `No change.` forever no matter what happened on the site. Together with
last session's truncated `TZK_URL`, the Phase 0 claim that the local monitor was "confirmed
working with real Telegram alerts" should be treated as unproven. Fixed with a
`page.goto("about:blank")` before each real navigation; verified across four consecutive polls.

*Rule 13, now mechanical.* `sync_shared_block.py` copies everything between the
`SHARED SCRAPE BLOCK` markers from `alahly_ticket_check.py` into `alahly_ticket_monitor.py`,
re-extracts it, and SHA-compares. `--check` exits 1 on drift. The block is currently 501 lines,
`sha256 155cbaf83039...`. The previous session did this by hand-driven script; this makes it a
committed, repeatable step.

*State migrated in place.* `last_seen.json` went from the v2 string list to v3 objects. The old
hash covered fixture names only and is not comparable, so the migration re-establishes the
baseline **quietly** rather than firing an alert about a format change. Verified: first run
printed the migration notice and no alert, second run printed `No change.`

*What is NOT proven.* No Phase 2 alert has been delivered to Telegram, and none of this has run
in CI yet. `send_telegram()` is unchanged and previously proven, and `describe_change()` is
unit-tested for every transition, but neither fact is delivery. Force one alert before trusting
this: set the tracked fixture's `status` to `4` in `last_seen.json` and run the script.

**Session 2026-08-25 (third) - Phase 3 step 1, then a hard stop**

Brief was explicit: replace the six fabricated selectors in `alahly_ticket_prefill.py`, work one
step at a time, stop after each for verification - and, critically, *"if Tazkarti's login is
behind a CAPTCHA or an OTP, stop and tell me."* That last clause is what this session turned out
to be about.

*Pre-flight.* `last_seen.json` is v3 with object entries and an integer `status` (hash
`a086020c...66c5`, `ZED FC vs Al Ahly FC`, status 1) - not the empty-string hash.
`python sync_shared_block.py --check` printed `In sync: 501 lines, sha256 155cbaf83039...`,
exit 0. Nothing to fix before starting.

*Selectors were read, never guessed - same method as Phase 2.* A read-only Playwright dump of
`https://www.tazkarti.com/#/login` went to `debug/phase3-login-route.html`,
`debug/phase3-login-route.json` and `debug/phase3-login-route.png`. The dump script lives in the
session scratchpad, not the repo. **The form has no `id` attributes at all** - Angular renders it
with `name` attributes only, so every single `#`-prefixed selector in the existing script was
structurally incapable of matching anything, not merely pointed at the wrong thing.

| Fabricated | Real, confirmed | Detail |
|---|---|---|
| `#username` | `input[name="txtFanId"]` | label `Tazkarti ID *`, `maxlength=16`, placeholder `12345678901234` |
| `#password` | `input[name="txtPassword"]` | `maxlength=20` |
| `#login-button` | `form button.button-green` | text `Sign in`, **`type="button"`** - not a native submit |

*Step 1 executed as asked: visible browser, fill, no submit.* Each of the three selectors plus
`re-captcha#ngrecaptcha-0` resolved to exactly **1 element**. Both fields round-tripped their
values via `input_value()` (`fan id filled correctly: True (len 14)` /
`password filled correctly: True (len 14)`), and the button read `text='Sign in' disabled=False`.
Screenshot at `debug/phase3-step1-filled.png`, left on disk rather than pasted into the
transcript because it shows the Tazkarti ID in plain text; `debug/` is gitignored, confirmed with
`git check-ignore -v`. **Nothing was submitted.**

*The stop condition, and why it is not negotiable.* The dump flagged
`captcha markers: ['captcha', 'g-recaptcha', 'recaptcha']` and two live Google iframes - the
`anchor` and, notably, the `bframe` challenge frame. The form carries
`<re-captcha size="invisible" id="ngrecaptcha-0">` with sitekey
`6LcgZfUsAAAAAAji0eMKvFPicrHdkNbPQ9gneFJo`, sitting between the password field and Sign in.

Rather than assume, this was confirmed against the compiled bundle
`main.57e770ff8543ee8f6d96.js` (2.9 MB, fetched once). Two findings settle it:

```js
// the token is a REQUIRED field of the login request
login: function(e,n,t){ ... this._http.post(url+"Login", {Username:e, Password:n, recaptchaResponse:t}) }

// the Sign in button does not submit -- it only kicks off the captcha
(click) -> e.component.recaptchaRef.execute()

// login fires ONLY from reCAPTCHA's own callback
resolved: function(e,n){ this.recaptchaResponse=e, e ? (this.submitted=!0, this.submitLogin(n), ...) : ... }
```

There is no code path to a session without a Google-issued token. The only two ways past are
solving the challenge - forbidden by rule 11 and by the prefill docstring's stated boundary,
which the brief also reaffirmed - or hoping the invisible challenge silently passes a headless
browser's risk score, which is precisely the sort of thing that works while you are testing it
and fails at 9am on the morning tickets drop. Stopped here and reported, per the brief.

*A second, independent gate may also exist.* The same bundle contains `id="btn_sendOTP"`, also
wired to `recaptchaRef.execute()`. Whether **login** triggers an OTP cannot be determined without
submitting, and submitting is blocked by the reCAPTCHA. Recorded as UNKNOWN rather than ruled
out. Note the bundle also has `0 == getAllowRecaptcha() && (isCheckRecaptcha=!0, showRecaptcha=!1)`
- a server-side kill switch - but production currently renders the widget, so it is on. Do not
build on it being off.

*Incidental finding: `TZK_USERNAME` is not an email.* The prefill docstring and the Environment
Variables section both described it as "your Tazkarti account email". The field is `Tazkarti ID *`
and wants a 14-16 digit numeric ID. The value in `.env` is already a correct 14-digit one
(verified by shape - `len=14 all_digits=True` - without printing it), so only the documentation
was wrong. Environment Variables is now corrected; the docstring is not, because the script is
about to be rewritten.

*`TZK_MATCH_URL` is still wrong for its purpose.* It reads `https://www.tazkarti.com/#/matches` -
the listing, not a match page. Deriving it from `matchId` 2559 is still unconfirmed, exactly as
the Phase 2 notes warned. That is a step-3 problem and needs a read-only navigation, no login.

*What changed in the repo: only this file.* `alahly_ticket_prefill.py` was deliberately **not**
touched. The three real login selectors are recorded in Feature Specs -> Phase 3, but writing
them into the script would have been writing code we are about to delete - under the proposed
rescope the login block goes away entirely, along with `TZK_USERNAME` and `TZK_PASSWORD`, which is
a real side benefit given both were in the `.env` committed to public history in `b8ccce9`.

*`last_seen.json` did NOT change meaning this session.* Still v3, still
`{match_id, fixture, status, status_label, status_badge, status_class}` with the hash covering the
raw `matchStatus`. Nothing in Phase 3 reads or writes it, and no scraping logic was touched, so
`sync_shared_block.py --check` is still clean and rule 13 is not in play.

*Next session must start by getting a decision, not by writing code.* The rescope to a persistent
browser profile is a proposal the user has not yet accepted.

**Session 2026-08-25 (fourth) — Phase 4, the always-on local runner**

*The reframing that drove it.* Tazkarti assigns virtual-queue position by **arrival time**. So
alert latency is the only variable worth optimising — a pre-filled form does not move you up a
queue, arriving 40 minutes earlier does. Cron drift of 8–45 minutes is the whole drop window,
which means the CI job structurally cannot be the fast signal. Hence a 30s local runner, with
CI kept as the slow backstop. This also demotes Phase 3 (prefill) from "the next thing" to
"a nice-to-have", which is worth remembering the next time the reCAPTCHA blocker feels urgent.

*Rule 13 was already satisfied and stayed that way.* `sync_shared_block.py --check` was clean
at the start (501 lines, `155cbaf83039`). Every shared-block change this session was made in
`alahly_ticket_check.py` and synced across; the block ended at 552 lines, `47dca6502a4e`.
Nothing was hand-copied.

*Two paths in the shared block became absolute.* `STATE_FILE` and `DEBUG_DIR` were bare
relative strings. Task Scheduler sets **no working directory**, so under it a relative baseline
would have been written to wherever the process happened to start — and a baseline the next
run cannot find reads as "no baseline yet", which re-establishes silently and eats the alert.
Both now resolve next to the script, and both accept a `TZK_*` override. CI is unaffected: it
runs from the repo root, so the resolved path is the same file it always was.

*The wedge that was actually there.* The old loop's `except Exception` printed, slept, and then
called `fetch_al_ahly_matches(page)` again **with the same page object**. If the browser itself
had died, that page was dead for good and every later poll raised the identical error, forever
— the loop still running, still printing, never scraping again. Proven live: killing Chromium
under a running monitor produced
`TargetClosedError('Page.goto: Target page, context or browser has been closed')` at 22:22:30,
then `Launched a fresh Chromium.` at 22:23:00 and a clean scrape at 22:23:03. The fix throws
the browser away on **every** failure rather than trying to classify which exceptions mean "the
browser is gone" — that classification is a guess that eventually goes wrong silently, and in
the direction of staying wedged. A transient blip pays ~1s for a relaunch; the wedge becomes
structurally impossible. Chromium is also recycled every 240 polls (~2h) so a week-long process
cannot leak its way into slowness.

*Failure alerting, tuned against notification fatigue.* Silent for the first 6 failures (3
min), because one timeout is not news; then hourly; then a recovery message. An alert that
could not be sent retries in ~5 min rather than an hour, since the usual cause is the same
outage that broke the poll. Verified by forcing the threshold: `Telegram alert sent OK.`, and
the repeat scheduled 120 polls out.

*Closed the oldest open item in this file.* A Phase 2 alert has now actually been delivered:
`Change detected -- sending Telegram alert...` / `Telegram alert sent OK.` at 22:25:37, by
setting the tracked fixture's `status` to `4` in the LOCAL state file. Worth noting that this
test only became safe *because* the state files were split — doing it before would have
doctored the baseline CI commits.

*A bug the test harness found by accident.* The first attempt at that test wrote the state file
from PowerShell, which emits a UTF-8 **BOM**. Python's `json.load` threw, `load_state()`
swallowed it and returned `{}`, and the run re-baselined and alerted nothing. That is rule 1
wearing yet another hat: an unreadable baseline was indistinguishable from no baseline. Now it
warns loudly, keeps the file as `.corrupt`, and reads `utf-8-sig`. And since the local runner
rewrites this file 2,880 times a day, `save_state()` now writes to a temp file and
`os.replace()`s it, so an unclean shutdown cannot leave a truncated baseline behind.

*Task Scheduler over NSSM, and why.* Recorded in the header of
`install_local_monitor_task.ps1`. Short version: the two things NSSM would buy — auto-restart
and log rotation — the script now does itself, leaving NSSM's only real advantage as "starts
before anyone logs in". That advantage is expensive here. A service runs as SYSTEM, and
Playwright's Chromium lives in the **user** profile (`%LOCALAPPDATA%\ms-playwright`, confirmed:
`chromium-1223/1234`), so SYSTEM cannot find it without extra path plumbing; and running the
service as this account means storing a password for what is a **MicrosoftAccount**
(`PrincipalSource : MicrosoftAccount`), which is worse. So: run as the logged-on user, no
stored password, `LogonType Interactive`.

*Two triggers.* At-log-on is what brings it back after a reboot. A second trigger repeats
**every minute** forever with `MultipleInstances = IgnoreNew` — a no-op while the monitor is
alive, and a restart within ~60s of it dying for any reason the script could not catch itself.
That is the piece replacing NSSM's auto-restart. It was 5 minutes first and tightened to 1
precisely because a restart gap *is* alert latency. Measured: 82s at 5-minute spacing, 20s at
1-minute spacing, and from a cold `Ready` state the watchdog started the task by itself in 10s
with no manual start at all. Restarts reload the existing baseline — `No change.`, not a
re-baseline.

*`pythonw.exe`, not `python.exe`.* The task runs in the interactive session, so `python.exe`
would flash a console window at every logon and every watchdog restart. The cost is that a
failure *before* `install_logging()` runs — an import error, say — is invisible except as the
task's `LastTaskResult` and a missing heartbeat. Everything after that first line is captured.

*Logging, because there is no console.* stdout and stderr are teed into
`%LOCALAPPDATA%\tazkarti-monitor\monitor.log`, rotating at 2 MB × 5. The tee also swallows
console encoding errors: an Arabic team name through a cp1252 console raises
`UnicodeEncodeError` inside the `print()` itself, down in the shared block, where there is no
`try/except` to catch it.

*The honest finding about the hardware.* See the Standing Blockers entry. Summary: this is a
laptop that currently behaves like a desktop, and every acceptance criterion above would pass
identically on a laptop about to be put in a bag. The heartbeat and the retained CI job are
the mitigations; a Pi is the answer if it ever starts travelling.

*Not done, deliberately.* **No reboot was performed** — it is not mine to trigger on a machine
that is currently watching for a drop. The At-log-on trigger is registered and cold-start via
the watchdog is proven, but reboot recovery is unobserved and is listed as such.

**Session 2026-08-25 (fifth) — Phase 3 rebuilt at a smaller scope, and finished**

*The decision that unblocked it.* The user cut the scope rather than fight the CAPTCHA: the
helper does exactly one thing — open a visible browser on a persistent profile and type the
login fields in. The human clicks Sign in. Everything downstream of a submitted login was
**deleted**, not deferred, with the explicit reasoning that *a future session reads a `# TODO`
as unfinished work and tries to complete it*. That instruction is why there is now not one TODO
or fabricated selector left in the file, and why the deleted seat/quantity work is parked in the
v2 table with the reason attached rather than as a stub in the code.

*Selectors re-derived live rather than trusted from these notes.* A read-only Playwright dump of
`#/login` confirmed all three, each resolving to exactly one element: `input[name="txtFanId"]`
(text, maxlength 16, placeholder `12345678901234`), `input[name="txtPassword"]` (maxlength 20),
and one visible `form button.button-green` reading `Sign in`, `type="button"`. The form still
carries **no `id` attributes at all**, which is why the original `#username` / `#password` could
never have matched anything — they were not merely wrong, they were structurally incapable.

*The finding the whole rescope depended on, and it was not assumed.* A persistent profile only
helps if the session lives in `localStorage` (survives a browser restart) rather than
`sessionStorage` (does not). From the site's own bundle:
`getToken = () => localStorage.getItem("ETMS-Token")`, and `isLoggedIn = !!getToken()`.
`ETMS-Token` / `ETMS-RefreshToken` / `ETMS-ExpireToken` / `profileData` are all localStorage;
only the *guest* token is sessionStorage. Then proven empirically rather than left as inference:
a token written by one process was read back by a **separate process after a full browser
restart**. Using the site's own `!!ETMS-Token` test also means the login check does not depend
on reading English text out of the header, which would have broken the day the site renders in
Arabic — the same trap rule 6 exists for.

*A hole found by testing the check instead of trusting it.* The first version decided "logged
in" by seeing whether the site bounced us to the login form. But `TZK_MATCH_URL` defaults to the
**public** match listing, which never bounces — so a dead token would have read as LOGGED IN,
which is this project's signature failure mode (a healthy-looking report that delivers nothing).
The fix uses the site against itself: the header requests the cart-icon count on every page, and
that call is authenticated, so a revoked token 401s and Tazkarti's own interceptor runs
`clearCache()` and deletes it. The script therefore reads the token, lets the page settle, and
reads it **again**. Verified by planting `ETMS-Token = 'planted-not-a-real-token'` in a scratch
profile: the run correctly reported `SESSION EXPIRED`.

*The residual limit is written down rather than papered over.* Every client-side signal — token,
header, `Welcome <name>` — comes from the same localStorage, so if the site happens to make no
authenticated call while we look, a dead token can still read as LOGGED IN. That is stated in the
script's RUNBOOK with the human tell (the header says "Sign in" instead of your name). Detecting
it properly would need an authenticated request of our own, which was judged not worth it for a
human-triggered one-shot tool.

*Actually run, three times, against the live site.* `LOGGED OUT` on a fresh profile: both fields
round-tripped, `Tazkarti ID filled: True (14 chars)` / `Password filled: True (14 chars)` — the
14 matching the ID length recorded last session. `SESSION EXPIRED` via the planted token. Both
left the browser open and closed cleanly on Enter. **`LOGGED IN` is NOT verified** — it needs a
real sign-in with a human CAPTCHA solve, so it is listed under Not Yet Verified rather than
claimed.

*Small things that were wrong and are now not.* Credentials are read **lazily**, inside the
logged-out branch only — the old module-level `os.environ["TZK_USERNAME"]` would have crashed the
*common* case (already logged in, no credentials needed) for no reason. `env.example` still
described `TZK_USERNAME` as "your-tazkarti-username"; it is a 14–16 digit Tazkarti ID, and the
template said so nowhere. The `Sign in` box printed in the terminal was hand-aligned and ragged,
so it is now built by a helper that pads to the widest line.

*Where the profile lives, and why not next to the script.* `%LOCALAPPDATA%\tazkarti-monitor\
browser-profile`, overridable with `TZK_PROFILE_DIR`. Same reasoning as the local runner's state
file but stronger: the repo is in OneDrive, and a live Chromium profile is a large, constantly
rewritten pile of files. `browser-profile/` was also added to `.gitignore` — the default is
outside the repo, but `TZK_PROFILE_DIR` can point anywhere, and this directory holds a **live
session token**. Given `.env` was once committed to this public repo, the belt-and-braces guard
is cheap.

*Not done, deliberately.* `TZK_MATCH_URL` still points at the listing rather than a match page —
the per-match URL shape derived from `matchId` 2559 remains unconfirmed, exactly as the Phase 2
notes warned, so the script defaults to the listing and says so at runtime instead of inventing
a URL shape. No scraping logic was touched, so rule 13 is not in play and
`sync_shared_block.py --check` is still clean (552 lines, `47dca6502a4e`). `last_seen.json` did
not change meaning.

**Session 2026-08-25 (sixth) — the per-match URL question, closed; and the CI cron floor**

*The question that started it.* "If I tap the Telegram link, does it open the match page, logged
in?" Both halves of that turned out to be wrong assumptions, and both are now documented above so
they do not get re-assumed.

*Half one: there is no match page.* This file had speculated since Phase 2 that `TZK_MATCH_URL`
could be derived from the feed's `matchId`. It cannot, and this is now settled by evidence rather
than left as a lead:

- The bundle's route table has `matches`, `login`, `profile`, `events`, `e/:id`, `stadium` … and
  **no `matches/:id`**.
- On the live listing, `.match a` returns **`[]`** — the cards contain no anchors at all. The only
  hrefs on the page are `javascript:void(0)`.
- `Book Ticket` is a `<button>` with no `href`. Its handler opens a **modal** on the listing
  (`#book-ticket-modal` / `#queueModal`), and the app calls `router.navigateByUrl("/matches")`
  when the flow ends.
- Clicked it live: `#/matches` → **`#/login`**. Not a match page.

**The trap to avoid next time:** the bundle *does* contain `path: 'detail/:id'`, which looks
exactly like the answer. It is inside an Angular framework error string demonstrating a malformed
route config, referencing `HeroDetailComponent` — Angular's own Tour of Heroes tutorial. It is
boilerplate in a diagnostic message, not a Tazkarti route. Grepping route-shaped strings out of a
bundle finds the framework's examples as readily as the app's own routes.

*So the deliverable here was a negative, and the alert was left alone.* `#/matches` is the best
link that exists. Changing it would have meant inventing a URL shape, which is precisely what the
Phase 2 note warned against.

*Half two: the persistent profile has nothing to do with the phone.* Worth stating plainly
because it is an easy and expensive thing to assume: the profile is a Chromium user-data
directory in `%LOCALAPPDATA%` on the monitoring machine, used only by the prefill helper. A
Telegram link tapped on a phone opens the phone's browser with its own separate session. Combined
with the click test above — logged out, Book Ticket goes to `#/login` — **being signed in on the
phone is what makes the alert one tap**, and nothing in this repo can do it for you.

*The cron change, and the correction it forced.* `*/10` → `*/5`. Five minutes is the floor twice
over: GitHub rejects anything shorter, and rule 12 sets the same limit. The concern was stated
and the user reaffirmed, so it landed — but the honest framing is in Standing Blockers: **this
does not make CI a 5-minute signal.** Observed drift at `*/10` was 8–45 minutes, scheduled runs
are best-effort, and halving the request does not halve the drift. The local 30s runner is still
the only fast signal.

*What the cron change silently broke, and why it was caught.* `FAILURE_REALERT_EVERY = 6` counts
**runs**, not minutes, and its comment said "one nudge per hour at a 10-minute cadence". At `*/5`
that becomes a nudge every 30 minutes — double the notification fatigue the failure-detection
spec explicitly warns about. Raised to 12, with the rule written at the constant: `N = 60 /
interval_mins`. This is the kind of coupling that survives a green job indefinitely, because
nothing fails — you just get quietly spammed the first time the scraper breaks, months later.
It sits at line 57, **outside** the shared block, and the local monitor has its own independent
`FAILURE_REALERT_EVERY = 120` (~1h at 30s), so rule 13 was not in play and
`sync_shared_block.py --check` stayed clean at 552 lines / `47dca6502a4e`.

*Verified, not assumed.* `monitor.yml` re-parsed as YAML after editing (an early version of the
edit duplicated the `workflow_dispatch` key — caught immediately, fixed). The check script was
then run end-to-end against a **scratch state file** so the repo baseline was not disturbed:
`Parsed 10 match cards after 1 'View More' click(s), 1 of them Al Ahly.` /
`ZED FC vs Al Ahly FC -- AVAILABLE (matchStatus=1)` / quiet v2→v3 migration / exit 0, no alert
sent. `git diff last_seen.json` was empty afterwards, as intended.

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

Since Phase 4, (1) and (3) run **twice over**: a 30-second local loop for latency and a
`*/5` CI job as the backstop. They keep separate baselines on purpose — see the State File
Schema section.

---

## What NOT to Build

```
❌ Auto-purchase / auto-click "Pay" or "Confirm"     — never, in any phase
❌ CAPTCHA solving or bypass                          — never
❌ Submitting the login form / clicking "Sign in"     — never (it IS the CAPTCHA)
❌ Seat / quantity / add-to-cart automation           — deleted 2026-08-25, see v2 table
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
| Loop | `while True` + `sleep(30)`, under Task Scheduler | Single run, exits |
| Repeat driver | The script itself | GitHub Actions cron |
| State | `last_seen.json` on disk | `last_seen.json` committed to the repo |
| Secrets | `.env` via `python-dotenv` | Repo Actions secrets |
| Requires terminal open | Yes | No |
| Status | ✅ Reference implementation | ✅ Working; source of truth for the shared block |

**Why both exist:** two reasons now. The local version is still the ground truth — when the CI
version misbehaves, run the local one to find out whether the problem is the code or the
environment. Since Phase 4 it is also **the fast signal**, the one that actually gets you into
the virtual queue early. Do not delete either.

**Keep the scraping logic identical between them.** If a selector or normalisation rule changes
in one, change it in the other in the same commit. A divergence here destroys the whole point of
having a reference implementation.

### Flow

```
GitHub Actions cron (*/5)
  └─> checkout repo (brings last_seen.json)
      └─> headless Chromium -> about:blank -> tazkarti.com/#/matches
          │   (capturing the page's own /data/matches-list-json.json response)
          └─> wait for .team-names, then for .status
              ├─ timeout / 0 cards  -> save screenshot+HTML -> Telegram warning -> exit 1
              └─> click "View More" until exhausted
                  └─> DOM card count MUST equal feed row count, else exit 1
                      └─> keep rows where teamId 77 plays -> {match_id, fixture,
                          │                                   raw matchStatus}
                          └─> sort -> join -> sha256
                              ├─ hash == baseline   -> "No change." -> exit 0
                              ├─ no baseline yet    -> establish it, stay quiet
                              ├─ pre-Phase-2 state  -> re-baseline quietly
                              └─ hash != baseline   -> Telegram, worded by
                                                       transition -> exit 0
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
│       └── monitor.yml              ✅ cron */5 + workflow_dispatch
├── .vscode/                         ✅ editor config
├── alahly_ticket_check.py           ✅ CI single-run — SOURCE OF TRUTH for the shared block
├── alahly_ticket_monitor.py         ✅ local loop — reference implementation
├── alahly_ticket_prefill.py         ✅ local helper — login pre-fill ONLY, never submits
├── sync_shared_block.py             ✅ copies + verifies the shared block (rule 13)
├── install_local_monitor_task.ps1   ✅ registers the always-on Task Scheduler job
├── get_telegram_chat_id.py          ✅ one-shot setup helper
├── last_seen.json                   ✅ committed state — v3, hashes raw matchStatus
├── env.example                      ✅ template
├── .gitignore                       ✅ must contain .env
├── debug/                           ⬜ created at runtime on failure, NOT committed
└── CLAUDE.md                        ✅ this file
```

---

## State File Schema (`last_seen.json`)

**Current (v3, since 2026-08-25 — Phase 2):**
```json
{
  "hash": "<sha256 of the sorted, newline-joined match payloads>",
  "matches": [
    {
      "match_id": 2559,
      "fixture": "ZED FC vs Al Ahly FC",
      "status": 1,
      "status_label": "AVAILABLE",
      "status_badge": "Available",
      "status_class": "green"
    }
  ],
  "consecutive_failures": 0,
  "last_error": null,
  "updated_at": "2026-08-25T14:39:32+00:00"
}
```

Superseded: **v1** `{"hash": ...}`; **v2** the same shape as v3 but with `matches` as a list of
plain fixture STRINGS and a hash covering only those names.

**There are now TWO state files with this schema, and they must never be pointed at each other:**

| File | Owner | Why separate |
|---|---|---|
| `last_seen.json` (repo root) | `alahly_ticket_check.py` in CI | Committed on every run |
| `%LOCALAPPDATA%\tazkarti-monitor\last_seen_local.json` | `alahly_ticket_monitor.py` | See below |

Sharing one file makes each runner's write look like a change to the other, so the two
cross-fire false alerts at each other indefinitely. The local copy is also kept out of the repo
because the repo lives in OneDrive — a 30-second loop rewriting a file there is ~2,880 uploads
a day, and a sync lock landing on the one write that mattered loses a baseline. Both paths are
now overridable with `TZK_STATE_FILE`, and both default to a path resolved **next to the
script**, not to the working directory, because Task Scheduler does not set one.

Note the repo copy is still **v2** as committed (`8fbc6677...`, `matches` as strings) — the
Phase 2 commit landed after the last CI state commit, so the next CI run migrates it quietly.
The `a086020c...66c5` hash recorded in the Current State table is the v3 value, and it was
independently reproduced by the local runner on 2026-08-25.

Rules:
- **`matches` is a list of objects, not strings.** A v2 state is detected (`any(isinstance(m,
  str) ...)`) and migrated by re-establishing the baseline **quietly** — the old hash covered
  fixture names only and is not comparable, so alerting on it would be alerting on a format
  change. Both scripts do this.
- **`status` is Tazkarti's RAW `matchStatus` integer.** Only `status` and `match_id` and
  `fixture` reach the hash — see `match_payload()`. `status_label` / `status_badge` /
  `status_class` are diagnostics and alert wording, and are deliberately NOT hashed:
  `status_label` is derived from `status`, and the badge fields are language-dependent.
- `hash` is computed over the **sorted** payloads. Unsorted hashing makes a mere reordering of
  the page look like a change and fires a false alert.
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
# NOTE: TZK_USERNAME is NOT an email. The login field is "Tazkarti ID *"
# (input[name="txtFanId"], maxlength 16, placeholder 12345678901234) and wants
# a 14-16 digit numeric ID. The value currently in .env is a correct 14-digit one.
# Both are read LAZILY -- only when you are actually logged out. Once the
# profile holds a session, the helper never touches them.
TZK_USERNAME=<your 14-16 digit Tazkarti ID>
TZK_PASSWORD=<your Tazkarti account password>
TZK_MATCH_URL=<specific match page; defaults to the #/matches listing>
TZK_PROFILE_DIR=<optional; default %LOCALAPPDATA%\tazkarti-monitor\browser-profile>

# TZK_SEAT_CATEGORY and TZK_QUANTITY are GONE -- the code that read them was
# deleted with the seat-selection scope. Do not reintroduce them; see the v2 table.
```

```bash
# ── Always-on local runner (all optional; defaults are what is deployed) ──
TZK_STATE_FILE=<baseline path>   # default: %LOCALAPPDATA%\tazkarti-monitor\last_seen_local.json
TZK_DEBUG_DIR=<evidence dir>     # default: %LOCALAPPDATA%\tazkarti-monitor\debug
TZK_NOTIFY_START=1               # Telegram on start-up; this is the reboot signal. 0 to mute.
TZK_HEARTBEAT_HOURS=24           # "still alive" ping. 0 to mute -- but read the caveat first.
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
12. **Be polite to the server.** 5 minutes in CI (GitHub's own floor, and this rule's), 30 seconds locally, single client, no
    parallel requests, no proxy rotation.
13. **Changes to scraping logic land in both scripts in the same commit.** Do not hand-copy.
    Edit the block in `alahly_ticket_check.py` between the `SHARED SCRAPE BLOCK` markers, then
    run `python sync_shared_block.py`, and `python sync_shared_block.py --check` before
    committing. Hand-copying is exactly how they drifted the first time.
14. **`[skip ci]` on state commits** so the commit-back never causes surprises.
15. **Hash the raw value, never a value you derived from it.** Change detection runs on
    Tazkarti's own `matchStatus` integer; labels like `AVAILABLE` exist only to word the
    alert. A derived label is lossy in the one direction that matters — an unrecognised state
    funnelled into an existing label leaves the hash unmoved and the monitor silent about a
    state it did not recognise, which is the empty-hash bug wearing a different hat.
16. **Prefer a stable id over a name for identity.** Al Ahly is `teamId 77`, not a string
    match. `NBE Club` is `نادى البنك الاهلى المصرى` and matches any sane "al ahly" pattern
    without being Al Ahly at all.

---

## Feature Specs (Binding)

### Change detection
Compare the SHA-256 of the sorted, newline-joined Al Ahly match payloads — `match_id`,
`fixture`, and the **raw** `matchStatus` — against the stored baseline. Alert on any
difference. Do not alert when no baseline exists, or when the stored baseline predates Phase 2
— establish it silently, so neither a fresh clone nor a schema migration fires a spurious
notification.

### Failure detection
Zero total match cards on the page means failure, not emptiness. Alert on the first failure,
then once per hour (`FAILURE_REALERT_EVERY = 12` runs at the `*/5` cadence) while it persists.
Do not alert every run — an unfixable notification every few minutes trains you to ignore the
bot entirely. **That constant counts RUNS, so it must track the cron interval: N = 60 /
interval_mins.** It was 6 at `*/10`; leaving it there when the schedule moved to `*/5` would
have silently halved the gap to 30 minutes.

### Alert content
Telegram plain text. Show the delta, not the full list. Include the Tazkarti URL so it is one
tap to act. Keep it short enough to read on a lock screen.

**Different events must not read the same.** "Tickets are now on sale" and "a fixture was
added" mean very different things to someone glancing at a notification. `describe_change()`
emits these sections, most actionable first, so the important one survives truncation in a
notification preview:

```
🎫 TICKETS ON SALE       any transition INTO matchStatus 1, and new fixtures already on sale
🆕 FIXTURE ADDED         a new fixture that is not on sale yet
🔒 NO LONGER ON SALE     a transition OUT of matchStatus 1
ℹ️ STATUS CHANGED        any other transition, including UNKNOWN_STATUS_<n>
❌ REMOVED FROM LISTING  the fixture is gone from the feed
```

If the hash moved but no transition explains it, say exactly that rather than inventing a
reason.

### Phase 2 — availability signal (BUILT 2026-08-25)

**What is hashed:** `match_id \t fixture \t matchStatus`, sorted, SHA-256. `matchStatus` is
Tazkarti's **raw integer**, never a label derived from it. Deriving first and hashing the
derivation is lossy in the one direction that matters — an unrecognised status would fall
through to an existing label, the hash would not move, and the monitor would go quiet on a
state it did not recognise. That is the empty-hash bug in a new hat.

**Where `matchStatus` comes from — this is NOT in the DOM.** The listing page fetches its own
data from the public static file below and renders the cards from it. The rendered card only
ever shows a colour class and a translated label, both derived from `matchStatus`:

```
https://www.tazkarti.com/data/matches-list-json.json?_=<cache-buster>
```

The script captures the response the page already requested (`page.on("response")`, registered
before `goto()`), so it makes **no extra request of its own** — rule 12 is intact. Relevant
fields per row: `matchId`, `matchStatus`, `teamId1`/`teamId2`, `teamName1`/`teamName2`,
`teamNameAr1`/`teamNameAr2`, `showInPortal`, `isDeleted`.

**The four status values — complete, read out of the compiled Angular bundle
`8.7c7ab3ab9f9641d7d4c4.js` and `assets/i18n/{en,ar,fr}.json`, NOT guessed:**

| `matchStatus` | Badge class | English | Arabic | French | Token used in alerts |
|---|---|---|---|---|---|
| 1 | `status green` | `Available` | `متاح` | `Disponible` | `AVAILABLE` |
| 2 | `status red` | `Match Ended` | `انتهت المباراة` | `Match terminé` | `MATCH_ENDED` |
| 3 | `status red` | `Booking Closed` | `تم غلق الحجز` | `Réservation fermée` | `BOOKING_CLOSED` |
| 4 | `status red` | `Coming Soon` | `قريبًا` | `Bientôt disponible` | `COMING_SOON` |

The template that produces them, decompiled:

```js
// badge (node 66/67)
<div class="status" [class.green]="matchStatus==1"
                    [class.red]="matchStatus==2||==3||==4">
  {{ matchStatus==1 ? 'Available'   : matchStatus==2 ? 'NotAvailable'
   : matchStatus==3 ? 'FullBooking' : 'MatchComingSoon' | translate }}
```

Anything outside 1–4 renders as `Coming Soon` (it is the `else` branch) but still hashes
distinctly, and `status_label()` reports it as `UNKNOWN_STATUS_<n>`.

**Why the badge and not the Book Ticket button.** Both were examined. The button loses twice:

```js
// button (node 37/40) -- class is STATIC "button button-green width-auto"
[disabled] = (matchStatus!=1 && matchStatus!=4)
          || (matchStatus==4 && !isSystemFan)
          || startBooking
```

Its colour class never changes, so it is green even when booking is closed; and its `disabled`
also depends on login state (`isSystemFan`) and a transient per-card `startBooking` flag. The
badge is a function of `matchStatus` alone. **Do not switch the signal to the button.**

**Noise that is deliberately excluded from the hash.** The page carries two hidden
virtual-queue templates that are also `.match` elements — blank team names, no `.status`, and
text including `People waiting`, `Approx. waiting time`, and `Last update time : 05 : 13 PM`.
That clock ticks every minute; it was observed changing `05:12 PM` → `05:13 PM` between two
runs a minute apart. Hashing card text wholesale would fire an alert on every single run.
Cards with no team name are skipped, which drops them. Verified: four consecutive live polls
produced an identical hash.

**Al Ahly identification is by team id, not by name.** `AL_AHLY_TEAM_ID = 77`. The name test
is kept only as a fallback so a reissued id is noisy rather than silent. `DECOY_TEAM_IDS` is
load-bearing and NOT a nicety: `NBE Club` (teamId 171) is `نادى البنك الاهلى المصرى` — the
National Bank of Egypt — and `الاهلى` is just the Arabic word for "national", so it matches any
reasonable "al ahly" pattern. Without the decoy list every NBE fixture is tracked as an Al Ahly
one. This was caught by a test asserting the fixture count, not by reading the code.

**DOM/feed cross-check.** The number of rendered fixture cards must equal the number of feed
rows (after dropping `showInPortal: false` / `isDeleted: true`); a mismatch raises. This is an
independent guard on the pagination fix — with `View More` disabled it correctly reports
`rendered 6 ... feed lists 10`.

---

**DOM selectors, originally read out of the `debug-11` artifact HTML on 2026-08-24 and
re-confirmed against a fresh dump on 2026-08-25. Not guessed.**

```
.match                       match card root — iterate THIS, not .team-names
  .top.clearfix
    .teams
      .team-names            fixture name; blank on the queue templates
        .team-name.first
        .team-name.second
    .blocks
      button.button.button-green.width-auto    "Book Ticket" — NOT the signal, see above
  .bottom
    .one > .first            metadata label ("Tournament", "Match No.", "Group :")
    .one > .second           metadata value
    .status                  AVAILABILITY BADGE — cross-check + alert wording only
```

Observed markup: `<div class="status green"> Available </div>`. The colour is a second class
on the same element, so `.status` carries the text and `.status.green` encodes the state.

Iterate `.match` and skip cards whose team names are blank. Iterating `.team-names` directly
picks up the two hidden queue templates, which have one but no `.status`.

Also in the markup: the load-more control, `button.button.button-blue.width-auto` with the
text `View More`, which reports `disabled` once the list is exhausted. It is selected by class
rather than text so it survives an Arabic render; see the pagination record above.

The booking modal is `#book-ticket-modal`, containing `.book-second-step` and
`.book-ticket-modal-footer`. That is Phase 3 territory and is still unverified.

---

### Phase 3 - login pre-fill helper (BUILT 2026-08-25, deliberately reduced scope)

**The scope is: open a visible browser on a persistent profile, and type the two login fields
in. That is all it does, and that is finished — not a stepping stone to something larger.**
The human clicks Sign in and solves the CAPTCHA. The script never submits.

**Login selectors - read from the live DOM 2026-08-25, each confirmed to resolve to exactly one
element. NOT guessed.** Re-derive them by dumping `https://www.tazkarti.com/#/login`; note the
form carries **no `id` attributes**, so select on `name`:

```
https://www.tazkarti.com/#/login
  form
    input[name="txtFanId"]      label "Tazkarti ID *", maxlength 16, placeholder 12345678901234
                                -- a 14-16 digit numeric ID, NOT an email
    input[name="txtPassword"]   maxlength 20
    re-captcha#ngrecaptcha-0    invisible reCAPTCHA v2 -- THE BLOCKER, see Standing Blockers
    button.button-green         text "Sign in", type="button" (NOT a submit; its click handler
                                is recaptchaRef.execute())
```

**These are now written into `alahly_ticket_prefill.py`.** `SIGN_IN_BUTTON` is defined there and
**intentionally never clicked** — it is recorded because it was expensive to find and because it
is how you confirm you are looking at the real login form. The file says so at the definition, so
a future session does not "fix" the unused constant by wiring a `.click()` to it.

**Session persistence — why the persistent profile actually works.** Read out of
`main.57e770ff8543ee8f6d96.js`, not assumed:

```js
getToken   = () => localStorage.getItem("ETMS-Token")   // localStorage, NOT sessionStorage
isLoggedIn = !!getToken()                               // the app's own definition
clearCache = () => { localStorage.removeItem("ETMS-Token"); ... }   // logout / 401
```

`ETMS-Token`, `ETMS-RefreshToken`, `ETMS-ExpireToken` and `profileData` are all **localStorage**;
only the *guest* token is sessionStorage. localStorage lives in the user-data dir, so it survives
closing the browser — which is the entire premise of the rescope. **Verified empirically, not
just read:** a token written by one process was read back by a different process after a full
browser restart.

**Stale-session detection, and its limit.** The site's header requests the cart-icon count on
every page, and that request is authenticated; if the token is dead the response 401s and
Tazkarti's own interceptor runs `clearCache()`, deleting `ETMS-Token`. So the script reads the
token, lets the page settle, and reads it again — a token that vanished in between is a session
the server just rejected. **Confirmed live** by planting a bogus token and watching the site
delete it. The limit, which is written into the script's runbook too: every client-side signal
(token, header, "Welcome <name>") comes from the same localStorage, so if the site makes no
authenticated call while we look, a dead token can still read as LOGGED IN. The tell is then the
ordinary one — the header says "Sign in" instead of your name.

**`TZK_MATCH_URL` correctly defaults to the LISTING, and that is permanent, not a placeholder.**
There is no per-match URL to point it at — see the roadmap section above for the evidence. The
alert links to the same place for the same reason. Note what this means in practice: tapping the
Telegram link opens the match **list**, and "Book Ticket" there sends you to `#/login` if that
browser has no session. The persistent profile does NOT help — it is a Chromium user-data dir on
the monitoring machine, and a phone is a different device with a different browser. Being signed
in on the phone is a manual, human, one-time thing.

**`#seat-category`, `#quantity`, `#add-to-cart` are GONE**, along with the code that used them.
They were fabricated and never matched a real element. Deleted rather than left as TODOs, because
a TODO reads as unfinished work and invites a future session to finish it. See the v2 table for
why rebuilding them is low-value.

**The boundary is unchanged and is not an unfinished TODO.** No auto-pay, no "Confirm", no CAPTCHA
solving. The helper stops at the cart and hands control to the human. Keep the prefill docstring's
explanation of both boundaries intact - the brief reaffirmed this explicitly.

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

# Force an alert, to test the Telegram path end-to-end.
# Since Phase 2 the hash covers matchStatus, so change the STATUS, not the
# hash -- that way the alert text exercises a real transition:
#   in last_seen.json, set the tracked fixture's "status" to 4, then run.
#   Expect: "TICKETS ON SALE: ZED FC vs Al Ahly FC (COMING_SOON -> AVAILABLE)"
# Changing a character of the hash still fires, but produces the
# no-transition-identified wording instead, which tests less.

# ── THE ALWAYS-ON LOCAL RUNNER (Phase 4) ─────────────────────────
# Install / re-install (idempotent -- re-run after editing the .ps1):
powershell -ExecutionPolicy Bypass -File .\install_local_monitor_task.ps1

# Is it alive?
Get-ScheduledTask -TaskName "Tazkarti Local Monitor" | Select-Object State
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Select-Object ProcessId

# What has it been doing? THIS is the console you do not otherwise have:
Get-Content "$env:LOCALAPPDATA\tazkarti-monitor\monitor.log" -Tail 40
Get-Content "$env:LOCALAPPDATA\tazkarti-monitor\monitor.log" -Wait   # live tail

# Stop it for a while (the 1-minute watchdog WILL restart it otherwise):
Disable-ScheduledTask -TaskName "Tazkarti Local Monitor"
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Enable-ScheduledTask -TaskName "Tazkarti Local Monitor"    # and it comes back within 60s

# Remove it entirely:
Unregister-ScheduledTask -TaskName "Tazkarti Local Monitor" -Confirm:$false

# Verify reboot recovery (the one criterion not yet observed):
#   reboot -> log in -> wait ~2 min -> expect a Telegram "Local Tazkarti
#   watcher started" message. If it does not arrive, check the log above
#   and Get-ScheduledTaskInfo -TaskName "Tazkarti Local Monitor".

# ── THE LOGIN PRE-FILL HELPER (Phase 3) ──────────────────────────
# Opens a VISIBLE browser on a persistent profile and types your login
# in. You click Sign in and solve the CAPTCHA. It never submits.
python alahly_ticket_prefill.py
#   First run  -> "LOGGED OUT",     fills both fields, you sign in.
#   Later runs -> "LOGGED IN",      goes straight to TZK_MATCH_URL.
#   Stale one  -> "SESSION EXPIRED", fills both fields again.
# Press Enter in the terminal to close -- that flush is what saves the
# session. The file's own RUNBOOK section has the full detail.

# Where the profile lives (holds a LIVE session token -- treat as a
# credential, and keep it out of the repo and out of OneDrive):
#   %LOCALAPPDATA%\tazkarti-monitor\browser-profile
# Full reset, only if signing in repeatedly fails -- it also throws away
# cookies and the profile's CAPTCHA reputation, so not routine:
#   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\tazkarti-monitor\browser-profile"

# ── CHANGING THE SCRAPER (rule 13) ───────────────────────────────
# Edit ONLY alahly_ticket_check.py, between the SHARED SCRAPE BLOCK
# markers. Then:
python sync_shared_block.py           # copy into the monitor + verify
python sync_shared_block.py --check   # run before every commit
```

---

## How to Deploy (GitHub Actions)

**Already done:**
- `.github/workflows/monitor.yml` committed with `cron: "*/5 * * * *"` + `workflow_dispatch`
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

**Acceptance criteria for Phase 2 — all six, verified locally 2026-08-25:**
- [x] The scrape returns structured objects carrying a raw `matchStatus`, not strings —
      `{"match_id": 2559, "fixture": "ZED FC vs Al Ahly FC", "status": 1, ...}`
- [x] Changing only `matchStatus` moves the hash — `a086020c` → `063ae110`
- [x] An **unrecognised** `matchStatus` (99) also moves the hash — this is the criterion that
      forced hashing the raw integer instead of the derived label
- [x] Repeated live runs produce an identical hash, so no live-updating text is in it —
      four consecutive polls, all `a086020c641a`
- [x] The alert distinguishes the events — `TICKETS ON SALE` / `FIXTURE ADDED` /
      `NO LONGER ON SALE` / `REMOVED`, with the most actionable section first
- [x] A partial listing is refused by comparing the rendered card count to the feed —
      `rendered 6 ... feed lists 10` when `View More` is suppressed
- [x] **A Phase 2 alert delivered to Telegram** — 2026-08-25 22:25:37, from the local runner.

**Acceptance criteria for Phase 4 (always-on local runner) — verified 2026-08-25:**
- [x] The local monitor reads the full listing and the raw `matchStatus` — six consecutive
      polls, `Parsed 10 match cards after 1 'View More' click(s), 1 of them Al Ahly.`, hash
      `a086020c641a` on every one, matching the value Phase 2 recorded independently
- [x] It keeps a baseline that CI cannot touch and cannot touch CI's — local writes went to
      `%LOCALAPPDATA%`, and the repo's `last_seen.json` was byte-identical afterwards
- [x] **A killed browser does not wedge the loop** — Chromium killed out from under a running
      monitor at 22:22, `TargetClosedError` at 22:22:30, `Launched a fresh Chromium.` at
      22:23:00, clean scrape at 22:23:03, `Recovered after 1 failed poll(s).`
- [x] Sustained failure reaches Telegram — `maybe_alert_failure` delivered with a forced
      threshold, and scheduled its repeat 120 polls (~1h) out
- [x] A corrupt state file is loud, not silent — prints a WARNING and keeps the bad file as
      `.corrupt`, instead of the old silent `return {}`
- [x] **Killing the process restarts it** — killed twice; the watchdog brought it back in 82s
      at the 5-minute interval and in 20s after tightening to 1 minute, reloading the existing
      baseline (`No change.`, not a re-baseline)
- [x] It survives a restart loop without spamming — second restart inside 10 minutes logged
      `Skipping the start-up ping`
- [ ] **Reboot recovery.** Not observed; no reboot performed. See Not Yet Verified.

**What would a passing Phase 4 suite still miss?** That the machine is *awake*. Every check
above passes identically on a laptop that is about to be closed and put in a bag. That gap is
covered by the daily heartbeat and by keeping the CI job, not by a test — see the
always-on caveat in Standing Blockers.

**Acceptance criteria for Phase 3 (login pre-fill helper) — verified 2026-08-25:**
- [x] Every selector it uses resolves to exactly one element on the live page — all three
      re-derived from a fresh `#/login` dump, not trusted from these notes
- [x] No fabricated selector and no `TODO` remains anywhere in the file — `#seat-category`,
      `#quantity`, `#add-to-cart` are deleted along with the code that used them
- [x] It never submits the login form — no `.click()` anywhere in the file; `SIGN_IN_BUTTON`
      is defined, documented as intentionally unused, and never called
- [x] A fresh profile reports `LOGGED OUT` and fills both fields, verified by round-tripping
      the typed values — `Tazkarti ID filled: True (14 chars)` / `Password filled: True (14 chars)`
- [x] **A dead session is not reported as a healthy one** — a planted bogus `ETMS-Token` was
      deleted by the site's own 401 interceptor and correctly reported `SESSION EXPIRED`.
      This is the criterion that caught the real bug: the first version tested for a bounce to
      the login form, which the *public* listing page never does
- [x] The profile persists localStorage across a full browser restart, across processes
- [x] The logged-in case needs no credentials at all — they are read lazily, so a missing
      `TZK_USERNAME` cannot break the common path
- [ ] **The `LOGGED IN` path itself.** Needs a real sign-in. See Not Yet Verified.

**What would a passing Phase 3 suite still miss?** That the session survives *days*, not just a
restart. Every check above passes on a token minutes old. `ETMS-ExpireToken` and the refresh-token
flow mean a long gap between runs is the untested case — and drop mornings are exactly when the
gap will have been long. The mitigation is not a test: it is that `SESSION EXPIRED` degrades to
the same pre-fill you would have got anyway, so the bad case costs one CAPTCHA, not a lost drop.

**Asking what a passing suite would still miss is what caught two bugs this time.** The
count-asserting test caught `NBE Club` being tracked as an Al Ahly fixture; running the local
monitor for more than one poll caught the SPA never reloading. Neither would have been found by
reading the code, and the second had been latent since Phase 0.

---

## v2+ Future Enhancements (Do NOT Build Now)

| Enhancement | Design consideration for today |
|---|---|
| ~~Ticket-availability signal instead of fixture-list~~ | ✅ BUILT 2026-08-25. See Feature Specs → Phase 2. |
| **Seat-category / quantity / add-to-cart automation** — moved here from Phase 3 and **deleted from the code** 2026-08-25 | **LOW VALUE. Read this before rebuilding it.** Tazkarti allocates virtual-queue position by **arrival time**, so a pre-filled cart does not move you up the queue — being alerted 40 minutes earlier does, which is what Phase 4 exists for. It also cannot be built honestly today: the `#seat-category` / `#quantity` / `#add-to-cart` selectors were **fabricated**, never matched a real element, and cannot be derived without a logged-in session at a real drop. They were removed rather than left as `# TODO`, because a future session reads a TODO as unfinished work and tries to finish it. If it is ever rebuilt, derive the selectors from a live booking modal (`#book-ticket-modal`, `.book-second-step`) and keep rule 11's boundary: stop at the cart, never click Pay. |
| Self-hosted runner in Egypt | The fallback if the geo-block hypothesis is confirmed. A Raspberry Pi or a cheap always-on box running the *local* script is simpler than a self-hosted Actions runner — prefer it. |
| Multiple teams | Filter predicate is already isolated in the page script. Make it a list of patterns, not a hardcoded one. |
| Per-match alert routing | Telegram supports multiple chat IDs. `CHAT_ID` would become a comma-separated list. |
| Alert deduplication | If cron drift causes double runs, the hash comparison already makes repeats harmless. Revisit only if it proves otherwise. |
| Playwright stealth / fingerprint evasion | Only if a debug screenshot actually shows a bot challenge. Do not add speculatively — and if the site is deliberately blocking automation, the honest answer is to stop, not to escalate. |
