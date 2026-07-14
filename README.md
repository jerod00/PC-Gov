# PC-Gov Opportunity Finder

Finds and ranks government contract opportunities relevant to Palcon's metal
fabrication capabilities (gas turbine ducts, air inlet filter housings,
expansion joints, skids, and related large fabricated structures), and
emails a ranked digest every weekday morning.

**Phase 1 (this build):** SAM.gov (all federal opportunities, nationwide) +
Texas ESBD/TxSmartBuy, San Antonio, and Austin (state/local, home turf).
**Phase 2 (not yet built):** Oklahoma, Louisiana, Missouri. See
[Sources not automated](#sources-not-automated-yet) for what's covered by
email alerts instead of code, and why.

## How it works

Every weekday morning, `run_daily.py`:
1. Scans your inbox via IMAP for GOOD/BAD feedback replies from the previous digest and records them.
2. Pulls opportunities from each enabled source (SAM.gov + the Texas sources), isolating failures so one broken source never blocks the others.
3. For state/local opportunities, checks whether the listing is within 500 miles of Stephenville, TX (Texas is always in-radius; Oklahoma/Louisiana/Arkansas/New Mexico/Kansas/Missouri opportunities get a real distance check).
4. Scores every new opportunity against `config.yaml`'s keywords/weights and stores it in SQLite, deduped by notice number so nothing is ever emailed twice.
5. Emails a ranked HTML digest — or a short "nothing new today" email if nothing qualified, so you know it's still running.

## Project layout

```
config.yaml               # NAICS/PSC codes, keywords, scoring weights, source toggles — edit this, not the code
.env / .env.example       # secrets: SAM.gov key, Gmail address/app password (never commit .env)
run_daily.py              # entry point the scheduler calls
src/
  sources/                # one module per source (sam_gov.py, tx_esbd.py, san_antonio.py, austin_rss.py, html_table.py, base.py)
  db.py                   # SQLite: opportunities, feedback, learned_weights, run_log
  geo.py                  # distance filtering for state/local sources
  scoring.py              # config-driven ranking
  email_digest.py         # HTML render + SMTP send
  feedback.py             # IMAP scan for feedback replies
  logging_setup.py
scripts/
  log_feedback.py         # CLI fallback: python scripts/log_feedback.py <dedup_key> good|bad
  setup_task_scheduler.ps1
data/opportunities.db     # created on first run
logs/run.log              # created on first run
```

## 1. Install Python and project dependencies

Requires Python 3.11+.

```powershell
cd path\to\pc-gov-finder
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Get a free SAM.gov API key

1. Go to [sam.gov](https://sam.gov) and sign in (create a free account if you don't have one — "Sign In" top right, then "Create an Account").
2. Once logged in, click your name (top right) → **Account Details**.
3. Find **API Key** section → **Request Public API Key** (it's free, no approval wait — the key appears immediately).
4. Copy the key.

Note: SAM.gov account creation now typically requires ID verification (Login.gov). Budget 10-15 minutes the first time.

## 3. Fill in `.env`

Copy the template and fill in real values — **never commit `.env`** (it's already in `.gitignore`):

```powershell
copy .env.example .env
```

Edit `.env`:

- `SAM_GOV_API_KEY` — from step 2.
- `GMAIL_ADDRESS` — `jerod.mund@palconltd.com` (sends and receives the digest).
- `GMAIL_APP_PASSWORD` — **not** your normal Google password. Since this is a Google Workspace account:
  1. Go to [myaccount.google.com/security](https://myaccount.google.com/security).
  2. Turn on 2-Step Verification if it isn't already on (required for App Passwords).
  3. Search for **App Passwords** (or go directly to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)).
  4. Create one named something like "PC-Gov Digest", copy the 16-character password (no spaces) into `GMAIL_APP_PASSWORD`.
  5. If your Workspace admin has disabled App Passwords org-wide, you'll need them to allow it for this account, or use an OAuth2 flow instead (not built here — ask if you hit this wall).
- `DIGEST_RECIPIENT` — defaults to `GMAIL_ADDRESS` if left blank; already set to the same address.

## 4. First run (do this before scheduling anything)

```powershell
python run_daily.py
```

Check `logs/run.log` for what happened per source, and check your inbox for the digest (or the "nothing new today" email). If SAM.gov or a Texas source fails, the log will say exactly which one and why — the others still run and the email still goes out.

### Debugging a source

`tx_esbd.py` was rewritten against a real HTML sample from the live site and confirmed working (parses `esbd-result-row` divs, maps agency codes to names, filters out Awarded/Closed/No Award/Cancelled postings, paginates the first 5 pages). `san_antonio.py` is still generic/heuristic table-parsing that hasn't been confirmed against a live sample. If either starts returning 0 results:

1. Check `logs/run.log` for the specific warning/error.
2. Open the URL from `config.yaml`'s `source_urls` section in a browser and confirm it still resolves and still shows a results table.
3. If the markup changed, adjust `src/sources/html_table.py`'s `HEADER_ALIASES` (add whatever column header text the site now uses) or the table-selection heuristic.
4. If a source becomes JS-rendered (postback/SPA) instead of plain HTML, plain `requests` won't work anymore — that needs Playwright (headless browser) instead, which isn't built here. In the meantime, use the portal's own vendor email-alert signup as a supplement (see below).

## 5. Schedule it (Windows Task Scheduler)

From an **elevated (Administrator)** PowerShell prompt:

```powershell
cd path\to\pc-gov-finder
.\scripts\setup_task_scheduler.ps1
```

This installs a task named **"PC-Gov Opportunity Digest"** running Monday-Friday at 6:30 AM local time (30 minutes of buffer before your 8am deadline). Re-run the script any time to update it.

**Timezone note:** Task Scheduler uses your machine's local timezone, not "Central" specifically. If this machine isn't set to Central Time, either change the machine's timezone or edit the `-At` time in `scripts/setup_task_scheduler.ps1` to whatever local time corresponds to 6:30 AM Central, then re-run the script.

Useful commands after installing:
```powershell
Start-ScheduledTask -TaskName "PC-Gov Opportunity Digest"   # run it right now
Get-ScheduledTaskInfo -TaskName "PC-Gov Opportunity Digest" # check last run result
```

## 6. Tuning `config.yaml`

Everything you'd want to adjust without touching code lives here:

- **`sam_gov.naics_codes` / `psc_codes`** — add/remove codes as your product mix shifts.
- **`keywords`** — four buckets (`high_value`, `medium_value`, `low_value`, `negative`), each with a `weight` and a `terms` list. Add phrases you see relevant postings using that the current list misses; add negative terms for false-positive patterns you keep seeing.
- **`scoring.weights`** — how much each factor (keyword match, NAICS/PSC match, contract value, set-aside, proximity, deadline urgency) contributes to the final score.
- **`scoring.qualifying_set_asides`** — only claim set-asides you actually qualify for.
- **`scoring.contract_value_curve` / `proximity_curve` / `deadline_curve`** — shape how those factors score (see inline comments in the file).
- **`sources`** — flip a source off entirely (e.g. if TX ESBD's scraper breaks and you want to silence the error emails until you fix it) without deleting code.
- **`email.digest_min_score_to_include`** — raise this if you're getting too much noise; lower it if you're worried about missing marginal fits.
- **`source_urls`** — where each scraper points; update here if a portal's URL changes.

No restart or redeploy needed — `run_daily.py` reads `config.yaml` fresh every run.

## 7. Feedback loop

Each opportunity in the digest has two links: 👍 **Good match** / 👎 **Not relevant**. Clicking either opens a pre-filled email reply — just hit send, don't edit the subject line. The next day's run scans your inbox via IMAP, records the feedback, and nudges the weight of whatever keywords matched that opportunity (small steps, bounded, layered on top of — never overwriting — your `config.yaml` base weights).

CLI fallback, if you'd rather not use email replies (or want to backfill feedback on something):
```powershell
python scripts\log_feedback.py sam_gov:abc123 good
python scripts\log_feedback.py tx_esbd:xyz789 bad
```
The `dedup_key` (`source_id:notice_id`) is visible in the feedback link's URL if you hover it, or query directly:
```powershell
python -c "from src import db; c = db.connect('data/opportunities.db'); [print(r['dedup_key'], r['title']) for r in c.execute('SELECT dedup_key, title FROM opportunities ORDER BY first_seen_at DESC LIMIT 20')]"
```

## 8. Querying history

"What did we get last week?":
```powershell
python -c "from src import db; c = db.connect('data/opportunities.db'); [print(r['first_seen_at'][:10], r['score'], r['title']) for r in db.history_since(c, '2026-07-07')]"
```

## Sources not automated (yet)

These portals aren't scraped, either because they're JS-heavy enterprise systems (fragile against plain HTTP requests), mandate login to see anything actionable, or are mid-platform-migration as of this writing. Register directly with each for email alerts as your supplement:

| Source | Why not automated | What to do instead |
|---|---|---|
| TxDOT open lettings | Forward schedule is PDF-only; the only structured data (Socrata) is historical/awarded, not open opportunities | Subscribe at TxDOT's GovDelivery page: `public.govdelivery.com/accounts/TXDOT/subscriber/new` |
| Dallas, Fort Worth | Bonfire — modern JS SPA, no public API | Register as a vendor on each city's Bonfire portal; enable commodity-code email notifications |
| Houston | Beacon Bid + mandatory SAP Ariba login for solicitation details | Use the portal's "Subscribe to Agency" feature |
| Arkansas | Mid-migration to SAP Ariba as of July 2026 — actively unstable | Register on the current OSP/ARBuy portal for email alerts; revisit automation after the cutover settles |
| New Mexico | Three parallel/transitioning systems (Jaggaer, Sunshine Portal, new Euna/Bonfire network); unclear which is authoritative | Register on whichever system NM State Purchasing currently directs vendors to |
| Kansas | PeopleSoft Fluid — JS/session-driven enterprise portal | Register on the eSupplier portal for bid-event email notifications |

If any of these stabilize (a real API appears, or a portal moves to a simpler server-rendered system), they're straightforward to add as a new `src/sources/*.py` module following the same `Opportunity` dataclass shape as the existing ones.

## Reliability notes

- Every run logs to `logs/run.log` (rotated at 5MB, 5 backups kept) — what was searched, how many results per source, and any failures.
- Each source's success/failure is also recorded in the `run_log` SQLite table for querying later.
- A source failure never stops the others or blocks the digest — you'll see the failure in the log and the digest still arrives (possibly with fewer opportunities than usual).
- If **both** SAM.gov and all enabled Texas sources fail, you'll still get an email (a "nothing new" digest) rather than silence — check `logs/run.log` immediately if that happens unexpectedly.
