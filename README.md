# PC-Gov Opportunity Finder

Finds and ranks government contract opportunities relevant to Palcon's metal
fabrication capabilities (gas turbine ducts, air inlet filter housings,
expansion joints, skids, and related large fabricated structures), and
emails a ranked digest every weekday morning.

**Phase 1:** SAM.gov (all federal opportunities, nationwide) + San Antonio,
Austin, and Oklahoma (state/local).
**Phase 2:** Louisiana, Houston, Dallas County, and Wichita Falls (done) —
Missouri not yet built.
**Bonfire/CivicEngage expansion (2026-07):** City of Dallas, City of Fort
Worth, Harris County, City of San Angelo, City of Waco, City of Amarillo,
Port of Galveston (all Bonfire), and City of Galveston, City of Odessa,
City of Midland (all CivicEngage).
**New Orleans, LA (2026-07-22):** its own Kentico CMS-hosted listing
(`nola.gov/view-bid-opportunities`) — sits right at the edge of the old
500-mile radius (505.9mi from Stephenville, TX), so `company.radius_miles`
was widened to 525 specifically to bring it into scope; see
`src/sources/new_orleans.py` for the full story.
**Tulsa, OK (2026-07-22):** a plain server-rendered bid table
(`cityoftulsa.org`'s "Bid Opportunities and Results" page) — the simplest
source in this project (bid number, deadline, short title, nothing else);
see `src/sources/tulsa.py`. Oklahoma City was checked the same round and
is a dead end — its own site just points to BidNet Direct, already
declined project-wide.
**Wichita, KS (2026-07-23):** another Bonfire org (`wichita.bonfirehub.com`)
found open the same way the earlier seven were — robots.txt permits
crawling, and its public "Opportunity RSS Feed" matches the shared
`bonfire_rss.py` format exactly; see `src/sources/wichita_bonfire.py`. See
[Sources not automated](#sources-not-automated-yet) for what's covered by
email alerts instead of code, and why — including TX ESBD/TxSmartBuy, whose
scraper works but is disabled because the site's `robots.txt` disallows all
crawling.

## How it works

Every weekday morning, `run_daily.py`:
1. Scans your inbox via IMAP for GOOD/BAD feedback replies from the previous digest and records them.
2. Pulls opportunities from each enabled source (SAM.gov + the Texas sources), isolating failures so one broken source never blocks the others.
3. For state/local opportunities, checks whether the listing is within `company.radius_miles` (525 miles, widened from 500 on 2026-07-22 to bring New Orleans into scope) of Stephenville, TX (Texas is always in-radius; Oklahoma/Louisiana/Arkansas/New Mexico/Kansas/Missouri opportunities get a real distance check).

4. Scores every new opportunity against `config.yaml`'s keywords/weights and stores it in SQLite, deduped by notice number so nothing is ever emailed twice. If `ANTHROPIC_API_KEY` is set and `llm_scoring.enabled` is true, each opportunity also gets a quick relevance judgment from Claude — this catches genuine fits that don't happen to use any configured keyword, and supplies a plain-English fit reason for the digest.
5. Emails a ranked HTML digest — or a short "nothing new today" email if nothing qualified, so you know it's still running.

**Point of contact (2026-07-29):** SAM.gov's API includes a real `pointOfContact` field per notice (name/email/phone) — confirmed against SAM.gov's published API schema, not guessed. `sam_gov.py` now parses this (preferring the entry typed "primary") into the `Opportunity`'s `poc_name`/`poc_email`/`poc_phone` fields, which flow through the DB and show up as a "Contact:" line in the digest whenever present — useful both for the current notice and for reaching out about future similar work from the same office. Every other source leaves these fields `None` (no source scraped so far exposes contact data), so the digest simply omits the line for those rows rather than showing empty contact info.

## Project layout

```
config.yaml               # NAICS/PSC codes, keywords, capability profiles, scoring weights, source toggles — edit this, not the code
.env / .env.example       # secrets: SAM.gov key, Gmail address/app password, Anthropic/Voyage keys (never commit .env)
run_daily.py              # entry point the scheduler calls
src/
  sources/                # one module per source (sam_gov.py, tx_esbd.py, san_antonio.py, austin.py, oklahoma.py, louisiana.py, houston.py, dallas_county.py, wichita_falls.py, dallas_bonfire.py, fort_worth_bonfire.py, harris_county_bonfire.py, san_angelo_bonfire.py, waco_bonfire.py, amarillo_bonfire.py, port_of_galveston_bonfire.py, galveston.py, odessa.py, midland.py, new_orleans.py, tulsa.py, wichita_bonfire.py, bonfire_rss.py, civicengage_bids.py, html_table.py, base.py)
  db.py                   # SQLite: opportunities, feedback, learned_weights, embedding_cache, run_log
  geo.py                  # distance filtering for state/local sources
  scoring.py              # config-driven ranking (keywords, NAICS/PSC, capability profiles, semantic similarity)
  llm_scoring.py          # optional Claude-based relevance judgment layered on scoring.py
  semantic.py             # optional Voyage AI embeddings for semantic similarity, layered on scoring.py
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

**If you're on a corporate/managed Windows machine**, requests to some `.gov` sites may fail with `SSLError` / `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` — this happens when antivirus or a corporate proxy does HTTPS inspection, re-signing traffic with a corporate root certificate that Python doesn't trust by default (even though Windows and your browser do). Fix it by installing one more package into this same venv:

```powershell
pip install pip-system-certs
```

This patches Python to trust whatever certificates Windows itself trusts, instead of only the bundled `certifi` list. **Remember this is per-venv** — if you ever delete and recreate `venv\` (e.g. rebuilding it for the scheduled task), you'll need to re-run this install, or sources on affected domains will start failing with the same error again.

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
- `DIGEST_RECIPIENT` — defaults to `GMAIL_ADDRESS` if left blank. Comma-separate multiple addresses to send the digest to more than one person (e.g. `jerod.mund@palconltd.com,amund@palconltd.com`). Feedback links always reply back to `GMAIL_ADDRESS`'s own inbox regardless of how many people are listed here — every recipient's thumbs-up/down still gets picked up by the next run's IMAP scan.
- `ANTHROPIC_API_KEY` — **optional.** Powers the LLM relevance judgment (below) and the occasional source-discovery script. Leave blank to skip both; the daily digest works fine without it. To get one: go to [console.anthropic.com](https://console.anthropic.com) → sign in → **Settings → API Keys → Create Key**. Copy it in. At typical daily opportunity volume this runs well under $1/day on Claude Haiku — a rough estimate, not a quote, since your actual volume varies.
- `VOYAGE_API_KEY` — **optional.** Powers semantic similarity scoring (below). Leave blank to skip it; the daily digest works fine without it. Get one at [dashboard.voyageai.com](https://dashboard.voyageai.com).

### Capability profile & matching engine

Rather than a single flat keyword/NAICS/PSC list, `config.yaml`'s `capabilities` section names each distinct thing Pal-Con actually manufactures/does (e.g. "Turbine ducts, filter housings & expansion joints," "Hydrovac / vacuum excavation services"), each with its own keywords and NAICS/PSC/NIGP codes. Every opportunity is checked against every capability, and the single best-fitting one contributes a `Capability: ...` line to the digest and a score component (`scoring.weights.capability_relevance` in `config.yaml`).

This runs **alongside**, not instead of, the original flat `keywords`/`sam_gov.naics_codes`/`psc_codes` lists — an opportunity only needs to clear the relevance gate through *one* of: a flat keyword match, a flat NAICS/PSC match, a capability-profile match, or a positive LLM judgment.

NAICS/PSC/NIGP codes are a **graduated signal, not a hard filter**: an exact code match earns full credit, but a code in the same family (same first `naics_prefix_length` NAICS digits, or `psc_prefix_length` PSC/FSC digits — see `scoring.capability_scoring` in `config.yaml`) still earns partial credit instead of nothing. NIGP is often just a free-text category name rather than a clean numeric code (see Houston below), so it's matched as substring text instead.

### LLM relevance judgment (optional)

With `ANTHROPIC_API_KEY` set and `llm_scoring.enabled: true` in `config.yaml` (on by default), each new opportunity is also judged by Claude for fit against `company.capabilities_description` in `config.yaml` — a short plain-English description of what Palcon does and doesn't do. This is layered on top of, not a replacement for, the keyword/NAICS scoring:

- A positive judgment can by itself satisfy the relevance gate (normally requiring a keyword or NAICS/PSC match), so a genuine fit that happens to use none of the configured terms still surfaces.
- A positive judgment adds a bonus to the score, scaled by the model's own confidence (`scoring.weights.llm_relevance` in `config.yaml`).
- The model's one-sentence reasoning becomes the digest's fit explanation in place of the bare matched-keyword list.
- If the API key is missing, or any individual call fails, that opportunity just falls back to keyword/NAICS-only scoring — this never blocks a run or the digest send.

Edit `company.capabilities_description` in `config.yaml` any time to sharpen what Claude considers in-scope or out-of-scope (it explicitly lists things Palcon does *not* do, to stop "mentions steel in passing" false positives).

**Judgments are cached** (2026-07-23), same idea as the embedding cache below: keyed in SQLite on `dedup_key` + a hash of the judged text (title/agency/description/NAICS/minimum_value), so a recurring listing that hasn't changed since yesterday reuses its cached judgment instead of hitting the API again. Before this existed, every in-scope opportunity was re-judged by Claude on every single run regardless of whether it had already been judged — with 20+ sources and several hundred recurring listings, that was the dominant cost of both runtime (a run could take 10-15 minutes) and API spend. A changed title/description/NAICS naturally busts the cache for just that listing, since it changes the hash.

### Semantic similarity scoring (optional)

With `VOYAGE_API_KEY` set and `semantic_scoring.enabled: true` in `config.yaml` (off by default), each opportunity's text is compared via text embeddings against every capability's `description`, and the best similarity adds a bonus to that capability's score (`semantic_scoring.max_points`/`min_similarity`). This is a third independent signal alongside keyword/NAICS/capability-code matching and the LLM judgment above — it's what catches a genuine fit phrased in language that shares no keywords, codes, or NIGP terms with anything configured (e.g. "combustion exhaust conduit" scoring well against "Turbine ducts, filter housings & expansion joints" on meaning alone).

Anthropic doesn't serve embeddings directly; this uses [Voyage AI](https://dashboard.voyageai.com) (the `voyageai` package, model configurable via `semantic_scoring.model`). Opportunity embeddings are cached in SQLite by listing + content hash so a recurring listing isn't re-embedded (and re-billed) every day it stays open; capability-description embeddings are always recomputed fresh so editing `config.yaml` takes effect immediately. If the key is missing or a call fails, that run just falls back to keyword/NAICS/capability-code scoring — this never blocks a run or the digest send.

## 4. First run (do this before scheduling anything)

```powershell
python run_daily.py
```

Check `logs/run.log` for what happened per source, and check your inbox for the digest (or the "nothing new today" email). If SAM.gov or a Texas source fails, the log will say exactly which one and why — the others still run and the email still goes out.

### Debugging a source

`tx_esbd.py` was rewritten against a real HTML sample from the live site and confirmed working (parses `esbd-result-row` divs, maps agency codes to names, filters out Awarded/Closed/No Award/Cancelled postings, paginates the first 5 pages) — but it's disabled in `config.yaml` (`tx_esbd: false`) because `robots.txt` disallows crawling the site; do not re-enable it. `san_antonio.py` was similarly rewritten against a real HTML sample: it's a genuine ASP.NET GridView (`ContentPlaceHolder1_gvBidContractOpps`), and paging past page 1 is a real `__doPostBack` form submission (simulated here with `requests` — no headless browser needed). Its `robots.txt` returns 404 (no restrictions declared), so it's clear to run. `austin.py` was also rewritten against a real HTML sample after the original RSS-feed guess turned out to be a wrong URL (404) — Austin Finance Online has no RSS feed; the real active-solicitations page (`.../account_services/solicitation/solicitations.cfm`) is plain server-rendered HTML with the full listing already in the initial page load, no pagination found so far. Its `robots.txt` also returns 404. `oklahoma.py` is a plain server-rendered PHP page (OMES Central Purchasing's Solicitation Search Utility) with simple `?page=N` GET pagination — no login, no JS. Its "open-pending" status bucket includes some listings whose bid window closed years ago despite the status text still saying something like "Pending Award," so it filters by closing date instead of trusting the status label; it also has no per-listing agency/city field, so distance filtering falls back to the Oklahoma state centroid (a reasonable approximation since even the Oklahoma panhandle is within ~400 miles of Stephenville, TX). Its `robots.txt` blocks unrelated paths only. `louisiana.py` (LaPAC, Office of State Purchasing) is a plain server-rendered ColdFusion page with no pagination found (the "open" search appears to return everything currently open on one page) — its one real wrinkle is that a bid's original posting and its addenda share a run of physical `<tr>`s via `rowspan`, so the scraper only reads the first physical row of each group (identified by a `<span>` holding the bid number) and skips continuation rows, since the first row's description cell already reflects current status (e.g. `Bid Cancelled: <date>`), which is also how cancelled bids get filtered out. No per-listing agency/city field either, so distance filtering falls back to the Louisiana state centroid. Its `robots.txt` only blocks an unrelated `/checkbook/stateEmployees/` path. `houston.py` (Beacon Bid) is different from every other source here — it's a JS single-page app, so the listing page itself has no usable HTML, but its `robots.txt` is genuinely permissive (unlike Dallas/Fort Worth's Bonfire, which blocks all crawling), and the real data loads through a plain JSON GraphQL API (`beaconbid.com/api/gql?operation=ListSolicitations`) that only needs an anonymous "guest" session cookie — obtained with a normal page GET, no JavaScript execution or login required, confirmed end-to-end with plain HTTP requests before writing the scraper. The GraphQL query is deliberately trimmed to exclude the `ebid` field (full bid-response form definitions, including line-item pricing tables) since fetching it made a single record balloon to 600+ KB for no benefit here. Houston's own commodity codes (NIGP, not NAICS/PSC) and department names get folded into the description text for keyword matching rather than mapped to `naics_code`/`psc_code`, since conflating the two classification systems would misrepresent them as a configured-code match in scoring. Like Oklahoma and TX ESBD, the server's own `status: "open"` filter isn't fully trusted — solicitations are also skipped client-side if `canceledAt` is set or the due date has already passed. `dallas_county.py` is **Dallas County**, a separate government entity from the City of Dallas (see `dallas_bonfire.py` below) — its own domain (`dallascounty.org`) has a wide-open `robots.txt` (`Allow: /`, no restrictions) and a plain server-rendered "current business opportunities" page with a real `<table>` (Solicitation Number / Title / Anticipated Closing Date / Buyer Name / Buyer E-mail Address), each row linking directly to the actual bid packet PDF. Two markup quirks: the header row is a real `<tr>` with `<td>` cells (not `<th>`), distinguished only by a `tableHeaderBlue` row class rather than cell count, since it has the same number of cells as data rows; and a blank spacer `<tr>` immediately follows the header, skipped by checking for an empty first cell. "Anticipated Closing Date" is sometimes literally "TBD," left as `response_deadline: None` rather than treated as a parse error. `wichita_falls.py` is CivicEngage (CivicPlus), the same platform Abilene uses — but unlike Abilene, whose `robots.txt` explicitly disallows `ClaudeBot` (a deliberate policy, treated as a hard stop there), Wichita Falls' `robots.txt` has no such block, so it's clear to run. The board was empty (zero open bids) at build time, so the row markup was verified against `?showAllBids=on` (closed/awarded bids — structurally identical rows, just a different Status value) rather than guessed from Abilene's markup. Each row's own Status span is still checked client-side (only "Open" is kept) rather than trusting the page's server-side filter alone. `dallas_bonfire.py`, `fort_worth_bonfire.py`, `harris_county_bonfire.py`, `san_angelo_bonfire.py`, `waco_bonfire.py`, `amarillo_bonfire.py`, and `port_of_galveston_bonfire.py` are **City of Dallas**, **City of Fort Worth**, **Harris County**, **City of San Angelo**, **City of Waco**, **City of Amarillo**, and the **Port of Galveston** — all seven originally skipped as blocked (see the Bonfire caveat above), each independently re-checked 2026-07-20 and found open, each with a genuinely public per-organization RSS feed (`<org>.bonfirehub.com/opportunities/rss`, documented by Bonfire itself as an "Opportunity RSS Feed" meant for external embedding — not a reverse-engineered endpoint). Plain RSS 2.0 XML, no JS, no session/login — parsed with the standard library's `xml.etree.ElementTree`, no new dependency needed. Item titles follow a fixed `Reference #: <ref>. Name: <name>` shape and descriptions end with `Project closes <Mon DD, YYYY> <time>`, both extracted by regex and confirmed against real fetched samples from multiple orgs rather than guessed or ported from one to another. Since all seven orgs share identical item structure, the fetch/parse logic itself lives in `bonfire_rss.py`; each org's module is just a thin wrapper supplying its own subdomain/agency/city (Harris County has no city, same convention as `dallas_county.py`, since it's a county not a municipality; San Angelo's feed loads fine but currently has zero open items — an empty board, not a broken source; Waco's real feed included a "vertical turbine pump" installation for a water treatment plant, which correctly scores 0 since it's a water pump, not a gas turbine, and shouldn't be mistaken for a capability match). No per-item value/NAICS/PSC field in the feed, same limitation as Dallas County/Wichita Falls.

`galveston.py` is the **City of Galveston**'s CivicEngage `Bids.aspx` — independently confirmed open 2026-07-20, with real page markup (checked via view-source) that's structurally identical to Wichita Falls' already-working scraper (`listItemsRow`/`bidTitle`/`bidStatus` divs, same span ordering), so `wichita_falls.py` was refactored alongside it into a shared `civicengage_bids.py` module — each org's module is now a thin wrapper, same pattern as the Bonfire family above. One correction made while generalizing: Wichita Falls' original bid-number regex (`Bid No\.\s*(\S+)`) only captured a single token, which would truncate a real Galveston bid number like "RFQ 22-02" down to just "RFQ" — the shared module instead strips the literal "Bid No." prefix from the full span text, preserving multi-token bid numbers intact.

`odessa.py` and `midland.py` (2026-07-22) followed the same pattern — both share Galveston's open `robots.txt` and rendered the same confirmed structure across repeated full-page fetches (though unlike Galveston, byte-level view-source wasn't independently pulled for either; confidence rests on that structural consistency plus the platform being proven twice elsewhere). Two real wrinkles found along the way: Odessa's page only confirmed the "Request for Proposal" category (a separate "Invitation to Bid" category may exist and go uncovered — not blocking, since RFP alone already surfaces real open items); and Midland cross-lists the same bid under multiple department headings on one board (its descriptions are also generic boilerplate pointing to Bonfire/email rather than real solicitation text, since the city migrated actual solicitation management to a Bonfire subdomain that remains blocked — a separate host/platform from this CivicEngage board, don't confuse the two). The cross-listing meant `civicengage_bids.py` needed a dedup-by-bid-number step so the same job isn't scored twice.

`tulsa.py` (2026-07-22) is a different platform again — a plain server-rendered `<table>` on `cityoftulsa.org`'s own "Bid Opportunities and Results" page, confirmed via real view-source. `robots.txt` 404s at this exact path (no file declared at all), the same "no restriction declared" precedent already used for San Antonio and Austin. Structurally it's the simplest source in the project: just a bid number, a response deadline, and a short description — no agency field, no dollar value, no full description paragraph. One real wrinkle caught before it could cause a bug: the bid-number cell includes a parenthesized addendum counter that increments over a bid's life (a real item, `"RFP 26-917 (2)"`, was already on its second addendum) — using the full string as `notice_id` would have made the same bid look like a brand-new opportunity every time an addendum posted, so `tulsa.py` strips the `"(N)"` suffix before assigning `notice_id`, keeping the full text in `raw` for reference. Oklahoma City was investigated the same round and rejected: its own `okc.gov` "Bidding" page (confirmed via real page content) is purely a pointer to BidNet Direct, with no native listing of its own — a dead end, not an exception, given BidNet Direct's project-wide rejection.

`wichita_bonfire.py` (2026-07-23) needed no new parsing code at all — Wichita's real bid data turned out to live on `wichita.bonfirehub.com` (the city's own `wichita.gov` site is just an informational page pointing there), and its `robots.txt` reads the same open `Disallow:` (empty) as the seven Bonfire orgs already built. The public "Opportunity RSS Feed" was independently fetched and matched the shared `bonfire_rss.py` item format byte-for-byte — a third independent confirmation of that format, not assumed from the first two orgs — so this is just a thin identity wrapper, same pattern as `dallas_bonfire.py`.

`new_orleans.py` (2026-07-22) is a different platform entirely — `nola.gov`'s own Kentico CMS-hosted "View bid opportunities" page, confirmed via real view-source (not just rendered text) to be plain server-rendered HTML, not JS-rendered, even though each listing's detail/submission link points out to an external Infor CloudSuite supplier portal. `robots.txt`'s wildcard rule only disallows `/admin`; the more restrictive rules further down (blocking query-string URLs, `/311/quick-access`) are scoped to named bots like Googlebot/bingbot, not the wildcard group, so this page is clear. One real bug caught while building this: **`lxml` silently corrupts this page's structure** — each bid's date list is itself a `<ul>` of `<li>` elements nested inside that bid's own outer `<li>`, and lxml's parser mishandles the nested-`<li>` boundary, leaking fields (e.g. one item's "Set-Aside Program Eligible" flag) onto every earlier sibling. Switching to BeautifulSoup's `html.parser` backend fixed it, confirmed against the real fetched page. Also: this page's dates are abbreviated-month (`"Jul 24, 2026"`), which `html_table.parse_date`'s `"%B %d, %Y"` format doesn't match — rather than add a format to that shared helper, `new_orleans.py` has its own local date parser, following the same convention `bonfire_rss.py` already uses for this exact date shape. New Orleans itself is 505.9 miles from Stephenville, TX — right at the edge of the old 500-mile radius — so `company.radius_miles` was widened to 525 specifically to bring it into scope (see `geo.py`'s explicit `("New Orleans", "LA")` `CITY_CENTROIDS` entry, added so resolution uses New Orleans' real coordinates rather than the much-closer Louisiana state centroid, which would have silently misjudged it as well within range). If a source starts returning 0 results:

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
- **`sam_gov.lookback_days`** — how many days back each run's SAM.gov query looks for newly posted/modified notices (currently 3, widened 2026-07-29 from 1 as a safety net against a missed run day; re-fetching an already-seen notice is a harmless no-op since dedup is by `notice_id`).
- **`keywords`** — four buckets (`high_value`, `medium_value`, `low_value`, `negative`), each with a `weight` and a `terms` list. Add phrases you see relevant postings using that the current list misses; add negative terms for false-positive patterns you keep seeing.
- **`capabilities`** — named capability profiles (own keywords + NAICS/PSC/NIGP codes + a description used for semantic similarity); see [Capability profile & matching engine](#capability-profile--matching-engine) above. Add a new entry any time Pal-Con adds a genuinely distinct capability.
- **`scoring.weights`** — how much each factor (keyword match, NAICS/PSC match, capability match, contract value, set-aside, proximity, deadline urgency, LLM judgment) contributes to the final score.
- **`scoring.capability_scoring`** — how a capability's own keyword/code matches turn into points, and the NAICS/PSC prefix lengths used for graduated (family-level) code credit.
- **`scoring.qualifying_set_asides`** — only claim set-asides you actually qualify for.
- **`scoring.minimum_contract_value`** — hard floor on project size (currently $500,000, per company direction 2026-07-21). Only drops an opportunity when its value is actually *known* to be below the floor (today, only SAM.gov reports a structured value, and only on already-awarded notices) — every other source's opportunities have no value field at all and pass through unaffected, since there's no size data to judge them by. When `llm_scoring` is enabled, this same threshold is also passed to Claude's relevance judgment so it can reason about likely project scope from the work description itself (e.g. correctly rejecting a single spare vehicle part as nowhere near $500K) even when no dollar figure is stated anywhere in the listing.
- **`scoring.contract_value_curve` / `proximity_curve` / `deadline_curve`** — shape how those factors score (see inline comments in the file).
- **`sources`** — flip a source off entirely (e.g. if TX ESBD's scraper breaks and you want to silence the error emails until you fix it) without deleting code.
- **`email.digest_min_score_to_include`** — raise this if you're getting too much noise; lower it if you're worried about missing marginal fits.
- **`source_urls`** — where each scraper points; update here if a portal's URL changes.
- **`company.capabilities_description`** / **`llm_scoring`** — see [LLM relevance judgment](#llm-relevance-judgment-optional) above.
- **`semantic_scoring`** — see [Semantic similarity scoring](#semantic-similarity-scoring-optional) above.

No restart or redeploy needed — `run_daily.py` reads `config.yaml` fresh every run.

## 7. Feedback loop

Each opportunity in the digest has two links: 👍 **Good match** / 👎 **Not relevant**. Clicking either opens a pre-filled email reply — just hit send, don't edit the subject line. The next run scans your inbox via IMAP and records the feedback (run `python run_daily.py` again any time to pick it up immediately instead of waiting for the next scheduled run).

Feedback improves the system across four dimensions, not just the exact opportunity you voted on — each bounded to a small nudge (±0.5 max, layered on top of — never overwriting — your `config.yaml` base config):
- **Keyword weights** — the specific words that matched get nudged up or down.
- **Source trust** — a source (e.g. San Antonio) that keeps getting thumbs-down gets its *whole* future output dampened, even on listings that don't share any keywords with what you voted on.
- **NAICS code trust** — same idea, per NAICS code.
- **Capability trust** — same idea, per capability profile (e.g. if "Hydrovac / vacuum excavation services" keeps getting thumbs-down, its future matches get dampened too).

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

> **Bonfire caveat (2026-07-20, extended 2026-07-23):** every Bonfire/Euna-family row below was marked blocked based on that specific portal's own `robots.txt`, checked directly — never inferred from another Bonfire portal's policy. That discipline turned out to matter: City of Dallas, City of Fort Worth, Harris County, San Angelo, City of Waco, City of Amarillo, and the Port of Galveston's Bonfire subdomains were ALL originally checked and found blocked, then re-checked the same day and found *open*, each with a genuinely public per-organization "Opportunity RSS Feed" (see `src/sources/bonfire_rss.py` and the per-org wrapper modules, all now live). Wichita, KS's Bonfire subdomain was checked for the first time on 2026-07-23 (not a re-check — it hadn't been looked at before) and found open the same way, becoming an eighth org on the shared feed format. Ion Wave (a different platform under the same Euna Procurement parent, used by Tarrant County), Midland's Bonfire subdomain, and Galveston COUNTY's Bonfire subdomain were re-checked the same round and found **still blocked** — other Bonfire orgs relaxing their policy is still not evidence any of these three did too. Separately, City of Galveston's CivicEngage `Bids.aspx` (a different platform/entity from Galveston County's Bonfire portal) was independently confirmed open and its markup matched byte-for-byte against the already-working Wichita Falls scraper, so both now share `src/sources/civicengage_bids.py`. Odessa and Midland's CivicEngage `Bids.aspx` boards (2026-07-22) followed the same pattern — both share Galveston's open `robots.txt`, and both rendered the same confirmed structure across repeated fetches, so both are now built too (Midland's CivicEngage board is a separate host/platform from Midland's still-blocked Bonfire subdomain — don't confuse the two). Every remaining "confirmed blocked" row below still reflects its own last-checked date, not an assumption, and is worth periodically re-checking rather than treated as permanent.

| Source | Why not automated | What to do instead |
|---|---|---|
| TX ESBD/TxSmartBuy | The scraper (`src/sources/tx_esbd.py`) works and is tested against real page structure — but `www.txsmartbuy.com/robots.txt` disallows all crawling (`User-agent: * / Disallow: /`), so it's disabled in `config.yaml` and stays that way regardless of technical feasibility | Register for **CMBL** (Centralized Master Bidders List) vendor notifications — see the "CMBL" link in the site's Vendor menu |
| TxDOT open lettings | Forward schedule is PDF-only; the only structured data (Socrata) is historical/awarded, not open opportunities | Subscribe at TxDOT's GovDelivery page: `public.govdelivery.com/accounts/TXDOT/subscriber/new` |
| Arkansas | Mid-migration to SAP Ariba as of July 2026 — actively unstable | Register on the current OSP/ARBuy portal for email alerts; revisit automation after the cutover settles |
| Missouri (MissouriBUYS, powered by MOVERS) | Investigated live 2026-07-21: robots.txt doesn't block it (missouribuys.mo.gov's is Drupal-boilerplate and doesn't disallow the bid board; the actual data lives on a separate Oracle Fusion Government Cloud host that 404s on `/robots.txt`, i.e. no restriction declared), and the page genuinely shows real, current, publicly-viewable open solicitations without a login wall. Not built anyway: it's a heavy Oracle Redwood UI single-page app, and reverse-engineering its REST API (same approach that worked for Houston) went several layers deep — a telemetry beacon, a metadata-only resource, two per-item child sub-resources — without reaching the actual base list endpoint, and one request surfaced an OAuth/IDCS redirect suggesting part of the app may need an authenticated session a stateless script can't replicate. Needs a dedicated reverse-engineering pass (direct DevTools access) or a headless-browser (Playwright) approach — a bigger lift than any other source here | Register in the new MissouriBUYS, powered by MOVERS for commodity-code email notifications |
| New Mexico | Three parallel/transitioning systems (Jaggaer, Sunshine Portal, new Euna/Bonfire network); unclear which is authoritative | Register on whichever system NM State Purchasing currently directs vendors to |
| Kansas | PeopleSoft Fluid — JS/session-driven enterprise portal | Register on the eSupplier portal for bid-event email notifications |
| Tarrant County (Fort Worth's county) | Uses Ion Wave, a different eProcurement vendor than Bonfire — but Ion Wave, Bonfire, EqualLevel, and DemandStar are all now under one parent company (Euna Procurement). Re-checked live 2026-07-20 in the same round as the Bonfire re-checks above: `tarrantcountytx.ionwave.net/robots.txt` is STILL an identical blanket `Disallow: /` — unlike Bonfire, Ion Wave's policy has not relaxed. The listing page itself is a perfectly real, scrapable ASP.NET grid with genuine current bids — not built anyway. Ion Wave also has no known public RSS-feed equivalent to Bonfire's, so this would need a real page scrape even if it opened up, not a feed parse | Register on the Ion Wave portal for commodity-code email notifications |
| Abilene | `robots.txt` explicitly names `User-agent: ClaudeBot / Disallow: /` (inserted under a "Cloudflare Managed content" block, alongside GPTBot/Amazonbot/CCBot/etc.) — a deliberate policy against AI crawlers specifically, treated as a hard stop regardless of the page itself being a perfectly workable CivicEngage bid board (confirmed real "Open Bids" listing). Not something to route around with a different User-Agent | Register on the city's bid-notification list |
| Midland (Bonfire) | `midlandtexas.bonfirehub.com/robots.txt` re-checked 2026-07-20 (same round as the Dallas/Fort Worth/Harris County/San Angelo/Waco/Amarillo/Port of Galveston re-checks) and found **still** a blanket `Disallow: /` — unlike those seven, Midland's policy has not relaxed. Its RSS content is reachable in a normal browser, but that doesn't override robots.txt for automated fetching | Register on the Bonfire portal for commodity-code email notifications |
| Galveston County (Bonfire) | `galvestoncountytx.bonfirehub.com/robots.txt` re-checked 2026-07-20, still a blanket `Disallow: /` — a separate government entity from both the Port of Galveston (Bonfire, open, built) and the City of Galveston (CivicEngage, open, built); don't confuse the three | Register on the Bonfire portal for commodity-code email notifications |
| Lubbock | Every request to `ci.lubbock.tx.us`'s bid-opportunities page gets its connection aborted (`The connection was closed unexpectedly`), even with a normal browser User-Agent — a connection-level rejection, not a simple header check. Treated the same as an active block rather than something to work around further | Check the city's bid-opportunities page manually, or register for notifications |
| El Paso | Real bid data lives on `elpasotexas.ionwave.net` (Ion Wave, the same Euna Procurement family as Bonfire), confirmed same blanket `robots.txt` block as Tarrant County's Ion Wave portal — not individually re-checked as part of the 2026-07-20 round (only Tarrant County's Ion Wave instance was), so don't assume it's still blocked without checking | Register on the Ion Wave portal for commodity-code email notifications |
| Corpus Christi | Split across two platforms, neither pursued: "Capital Procurements" routes through CivCast, an AngularJS single-page app (raw HTML is just a loading shell) whose `robots.txt` is actually permissive — the same DevTools approach that found Houston's hidden API could work here, but CivCast's own site says a new platform version is coming (mid-migration, same instability concern that deprioritized Arkansas). "Operational Procurements" routes through an unidentified "Supplier Portal" — couldn't even determine the vendor from the public page | Register on CivCast and/or the city's Supplier Portal |
| Oklahoma City | Investigated 2026-07-22 alongside Tulsa: `okc.gov`'s own "Bidding" page (confirmed via real page content, not inferred) is purely an informational pointer to BidNet Direct — already declined project-wide for blocking `anthropic-ai`/`ClaudeBot` by name in `robots.txt`. No native listing exists on `okc.gov` itself | Register on BidNet Direct for email alerts |

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
