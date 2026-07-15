# PC-Gov Opportunity Finder

Finds and ranks government contract opportunities relevant to Palcon's metal
fabrication capabilities (gas turbine ducts, air inlet filter housings,
expansion joints, skids, and related large fabricated structures), and
emails a ranked digest every weekday morning.

**Phase 1:** SAM.gov (all federal opportunities, nationwide) + San Antonio,
Austin, and Oklahoma (state/local).
**Phase 2 (not yet built):** Louisiana, Missouri. See
[Sources not automated](#sources-not-automated-yet) for what's covered by
email alerts instead of code, and why — including TX ESBD/TxSmartBuy, whose
scraper works but is disabled because the site's `robots.txt` disallows all
crawling.

## How it works

Every weekday morning, `run_daily.py`:
1. Scans your inbox via IMAP for GOOD/BAD feedback replies from the previous digest and records them.
2. Pulls opportunities from each enabled source (SAM.gov + the Texas sources), isolating failures so one broken source never blocks the others.
3. For state/local opportunities, checks whether the listing is within 500 miles of Stephenville, TX (Texas is always in-radius; Oklahoma/Louisiana/Arkansas/New Mexico/Kansas/Missouri opportunities get a real distance check).
4. Scores every new opportunity against `config.yaml`'s keywords/weights and stores it in SQLite, deduped by notice number so nothing is ever emailed twice. If `ANTHROPIC_API_KEY` is set and `llm_scoring.enabled` is true, each opportunity also gets a quick relevance judgment from Claude — this catches genuine fits that don't happen to use any configured keyword, and supplies a plain-English fit reason for the digest.
5. Emails a ranked HTML digest — or a short "nothing new today" email if nothing qualified, so you know it's still running.

## Project layout

```
config.yaml               # NAICS/PSC codes, keywords, scoring weights, source toggles — edit this, not the code
.env / .env.example       # secrets: SAM.gov key, Gmail address/app password (never commit .env)
run_daily.py              # entry point the scheduler calls
src/
  sources/                # one module per source (sam_gov.py, tx_esbd.py, san_antonio.py, austin.py, html_table.py, base.py)
  db.py                   # SQLite: opportunities, feedback, learned_weights, run_log
  geo.py                  # distance filtering for state/local sources
  scoring.py              # config-driven ranking
  llm_scoring.py          # optional Claude-based relevance judgment layered on scoring.py
  email_digest.py         # HTML render + SMTP send
  feedback.py             # IMAP scan for feedback replies
  logging_setup.py
scripts/
  log_feedback.py         # CLI fallback: python scripts/log_feedback.py <dedup_key> good|bad
  setup_task_scheduler.ps1
  discover_sources.py     # optional, run-by-hand: AI-assisted candidate-source report (never auto-wired in)
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
- `ANTHROPIC_API_KEY` — **optional.** Powers the LLM relevance judgment (below) and the occasional source-discovery script. Leave blank to skip both; the daily digest works fine without it. To get one: go to [console.anthropic.com](https://console.anthropic.com) → sign in → **Settings → API Keys → Create Key**. Copy it in. At typical daily opportunity volume this runs well under $1/day on Claude Haiku — a rough estimate, not a quote, since your actual volume varies.

### LLM relevance judgment (optional)

With `ANTHROPIC_API_KEY` set and `llm_scoring.enabled: true` in `config.yaml` (on by default), each new opportunity is also judged by Claude for fit against `company.capabilities_description` in `config.yaml` — a short plain-English description of what Palcon does and doesn't do. This is layered on top of, not a replacement for, the keyword/NAICS scoring:

- A positive judgment can by itself satisfy the relevance gate (normally requiring a keyword or NAICS/PSC match), so a genuine fit that happens to use none of the configured terms still surfaces.
- A positive judgment adds a bonus to the score, scaled by the model's own confidence (`scoring.weights.llm_relevance` in `config.yaml`).
- The model's one-sentence reasoning becomes the digest's fit explanation in place of the bare matched-keyword list.
- If the API key is missing, or any individual call fails, that opportunity just falls back to keyword/NAICS-only scoring — this never blocks a run or the digest send.

Edit `company.capabilities_description` in `config.yaml` any time to sharpen what Claude considers in-scope or out-of-scope (it explicitly lists things Palcon does *not* do, to stop "mentions steel in passing" false positives).

## 4. First run (do this before scheduling anything)

```powershell
python run_daily.py
```

Check `logs/run.log` for what happened per source, and check your inbox for the digest (or the "nothing new today" email). If SAM.gov or a Texas source fails, the log will say exactly which one and why — the others still run and the email still goes out.

### Debugging a source

`tx_esbd.py` was rewritten against a real HTML sample from the live site and confirmed working (parses `esbd-result-row` divs, maps agency codes to names, filters out Awarded/Closed/No Award/Cancelled postings, paginates the first 5 pages) — but it's disabled in `config.yaml` (`tx_esbd: false`) because `robots.txt` disallows crawling the site; do not re-enable it. `san_antonio.py` was similarly rewritten against a real HTML sample: it's a genuine ASP.NET GridView (`ContentPlaceHolder1_gvBidContractOpps`), and paging past page 1 is a real `__doPostBack` form submission (simulated here with `requests` — no headless browser needed). Its `robots.txt` returns 404 (no restrictions declared), so it's clear to run. `austin.py` was also rewritten against a real HTML sample after the original RSS-feed guess turned out to be a wrong URL (404) — Austin Finance Online has no RSS feed; the real active-solicitations page (`.../account_services/solicitation/solicitations.cfm`) is plain server-rendered HTML with the full listing already in the initial page load, no pagination found so far. Its `robots.txt` also returns 404. `oklahoma.py` is a plain server-rendered PHP page (OMES Central Purchasing's Solicitation Search Utility) with simple `?page=N` GET pagination — no login, no JS. Its "open-pending" status bucket includes some listings whose bid window closed years ago despite the status text still saying something like "Pending Award," so it filters by closing date instead of trusting the status label; it also has no per-listing agency/city field, so distance filtering falls back to the Oklahoma state centroid (a reasonable approximation since even the Oklahoma panhandle is within ~400 miles of Stephenville, TX). Its `robots.txt` blocks unrelated paths only. If a source starts returning 0 results:

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
- **`company.capabilities_description`** / **`llm_scoring`** — see [LLM relevance judgment](#llm-relevance-judgment-optional) above.

No restart or redeploy needed — `run_daily.py` reads `config.yaml` fresh every run.

## 7. Feedback loop

Each opportunity in the digest has two links: 👍 **Good match** / 👎 **Not relevant**. Clicking either opens a pre-filled email reply — just hit send, don't edit the subject line. The next run scans your inbox via IMAP and records the feedback (run `python run_daily.py` again any time to pick it up immediately instead of waiting for the next scheduled run).

Feedback improves the system across three dimensions, not just the exact opportunity you voted on — each bounded to a small nudge (±0.5 max, layered on top of — never overwriting — your `config.yaml` base config):
- **Keyword weights** — the specific words that matched get nudged up or down.
- **Source trust** — a source (e.g. San Antonio) that keeps getting thumbs-down gets its *whole* future output dampened, even on listings that don't share any keywords with what you voted on.
- **NAICS code trust** — same idea, per NAICS code.

This is why a source or code with a consistently bad track record gradually surfaces less, even before you've explicitly voted on every individual listing from it. Query the current learned adjustments any time:
```powershell
python -c "from src import db; c = db.connect('data/opportunities.db'); [print(dict(r)) for r in c.execute('SELECT * FROM learned_adjustments')]"
```

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

These portals aren't scraped, either because they're JS-heavy enterprise systems (fragile against plain HTTP requests), mandate login to see anything actionable, disallow crawling in `robots.txt`, or are mid-platform-migration as of this writing. Register directly with each for email alerts as your supplement:

| Source | Why not automated | What to do instead |
|---|---|---|
| TX ESBD/TxSmartBuy | The scraper (`src/sources/tx_esbd.py`) works and is tested against real page structure — but `www.txsmartbuy.com/robots.txt` disallows all crawling (`User-agent: * / Disallow: /`), so it's disabled in `config.yaml` and stays that way regardless of technical feasibility | Register for **CMBL** (Centralized Master Bidders List) vendor notifications — see the "CMBL" link in the site's Vendor menu |
| TxDOT open lettings | Forward schedule is PDF-only; the only structured data (Socrata) is historical/awarded, not open opportunities | Subscribe at TxDOT's GovDelivery page: `public.govdelivery.com/accounts/TXDOT/subscriber/new` |
| Dallas, Fort Worth | Bonfire — `robots.txt` confirmed `Disallow: /` for both (`dallascityhall.bonfirehub.com` and `fortworthtexas.bonfirehub.com`), a blanket crawling opt-out; also a modern JS SPA even setting that aside | Register as a vendor on each city's Bonfire portal; enable commodity-code email notifications |
| Houston | Beacon Bid + mandatory SAP Ariba login for solicitation details | Use the portal's "Subscribe to Agency" feature |
| Arkansas | Mid-migration to SAP Ariba as of July 2026 — actively unstable | Register on the current OSP/ARBuy portal for email alerts; revisit automation after the cutover settles |
| New Mexico | Three parallel/transitioning systems (Jaggaer, Sunshine Portal, new Euna/Bonfire network); unclear which is authoritative | Register on whichever system NM State Purchasing currently directs vendors to |
| Kansas | PeopleSoft Fluid — JS/session-driven enterprise portal | Register on the eSupplier portal for bid-event email notifications |

### Third-party bid aggregators — investigated, not integrated

We looked at whether a third-party aggregator could cover many small counties/school districts/utility districts at once instead of one-off scrapers per agency. None panned out as a free, automatable source:

| Service | Finding |
|---|---|
| BidNet Direct | `robots.txt`'s wildcard rule technically permits crawling most public pages, but it explicitly, individually blocks `anthropic-ai`, `ClaudeBot`, and `Claude-Web` (plus GPTBot, Google-Extended, PerplexityBot, etc.) by name. That's a deliberate, targeted signal, not something to route around with a different User-Agent string — declined on principle, not technical grounds. Free vendor registration + email alerts remain a legitimate option if you want this source. |
| Public Purchase | `robots.txt` is genuinely permissive, but real bid data sits behind a client-side region→agency selection flow, not a single browsable page. The one shortcut endpoint found (`/gems/global/home/nationalBidList`) returned empty ("No bids at this time") when tested directly. Would require mapping the full region/agency drill-down across potentially dozens of TX agencies — not pursued given the uncertain payoff. |
| DemandStar | The public page only exposes a "Historical Bids" widget (already-awarded/closed, confirmed via its own real API at `api.demandstar.com/contents/agency/bids`). Actually-open bids require a paid vendor subscription — confirmed at **$550/year for Texas alone**. Not a free source; a business decision for Palcon to make independently if broader paid coverage is wanted, not something this project builds against. |
| BidPrime, GovWin IQ, Periscope S2G | All paid enterprise/SLED subscription services (roughly $400/yr–$29k/yr average, GovWin ranging up to $119k/yr). Same as DemandStar — a standalone business decision, not a build target here. |

If any of these change (Public Purchase's drill-down turns out simpler than expected, DemandStar adds a genuine free tier, etc.), they're straightforward to revisit. If any of the state/local sources above stabilize (a real API appears, or a portal moves to a simpler server-rendered system), they're likewise straightforward to add as a new `src/sources/*.py` module following the same `Opportunity` dataclass shape as the existing ones.

## 9. Occasional source discovery (optional, AI-assisted)

`scripts/discover_sources.py` is a **report-only** research tool, meant to be run occasionally by hand (monthly or so) — not by the scheduled task, and not something that runs automatically:

```powershell
python scripts\discover_sources.py
```

It uses Claude (with web search) to look for state/local government procurement portals within the 500-mile bid radius that this project doesn't already cover, and that haven't already been investigated and rejected (see the tables above — it's given that list so it doesn't waste time rediscovering them). It writes a markdown report to `data/source_discovery_<date>.md` listing each candidate's likely relevance, apparent tech stack, and whatever it could find out about `robots.txt` — then stops. It never edits `config.yaml`, never writes a scraper, and never gets wired into `run_daily.py` on its own.

Treat every candidate in the report as a lead, not a verified fact — the model's guesses about tech stack or robots.txt are a starting point, not a substitute for actually checking. To act on one, follow the exact same process used for every existing source in this project: check `robots.txt` yourself, fetch the real listing page, confirm the actual markup, then build a scraper against confirmed structure (see [Debugging a source](#debugging-a-source) above for the pattern).

Requires `ANTHROPIC_API_KEY` (same key as the LLM relevance judgment feature); uses Claude Opus rather than Haiku since this needs real research/reasoning, not bulk classification, and only runs occasionally so the higher per-call cost doesn't add up.

## Reliability notes

- Every run logs to `logs/run.log` (rotated at 5MB, 5 backups kept) — what was searched, how many results per source, and any failures.
- Each source's success/failure is also recorded in the `run_log` SQLite table for querying later.
- A source failure never stops the others or blocks the digest — you'll see the failure in the log and the digest still arrives (possibly with fewer opportunities than usual).
- If **both** SAM.gov and all enabled Texas sources fail, you'll still get an email (a "nothing new" digest) rather than silence — check `logs/run.log` immediately if that happens unexpectedly.
