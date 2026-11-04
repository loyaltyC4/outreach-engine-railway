# Surgical scrape spec — zero-ambiguity rules for the scraping agent

**Built:** 2026-11-04. **Purpose:** eliminate the "emailing low-interest people, not business owners" failure mode. **This file is operational — every rule is a hard constraint, not a suggestion.**

> **If a rule is unclear or a page shape doesn't match — SKIP the lead. We'd rather scrape 500 clean leads than 5,000 noisy ones. One bad email damages deliverability for every future lead on that domain.**

---

## Universal rules (apply to every campaign)

### Rule 1 — Owner-reach: the email must plausibly reach a decision-maker

**ALLOWED email local-parts** (left of @):
- `firstname` (e.g. `sarah@domain`)
- `firstname.lastname` or `firstname-lastname` or `firstnamelastname` (e.g. `sarah.jones@`)
- `firstname+anything` (common for alias routing)
- `initials` if company is clearly ≤ 5 people (verified from About page or LinkedIn)

**REJECT email local-parts** (regex, case-insensitive):
```
^(info|support|sales|contact|contactus|enquiries|enquiry|office|admin|administration|hello|hi|team|help|customer|customercare|customerservice|service|services|reception|frontdesk|hr|jobs|careers|recruit|recruitment|accounts|accounting|billing|invoices|payroll|finance|legal|compliance|privacy|dpo|press|media|pr|marketing|newsletter|news|comms|outreach|affiliates|affiliate|partnership|partnerships|wholesale|b2b|returns|refunds|shipping|delivery|logistics|warehouse|dispatch|orders|order|noreply|no-reply|donotreply|do-not-reply|unsubscribe|abuse|dmca|security|webmaster|postmaster|mailer-daemon|test|demo|example|null|placeholder|null@)$
```

**SPECIAL CASE — tiny companies.** If the business has ≤ 10 staff AND website/LinkedIn/registry confirms this, `hello@` and `info@` are often the owner. Keep them, but **tag `owner_confidence=medium`**. The Jev gate will catch most misses.

**Role-inbox verification signal (the "Is this probably a human?" check):**
- Does the company's About/Team page show ≤ 3 named staff? → `info@`/`hello@` is probably the owner. OK.
- Does the site show a "Support" or "Help Center" subdomain? → `support@` goes to a ticket queue. REJECT.
- Does the site have a chatbot widget? → `info@` goes to the same queue. REJECT.
- Is there a "Contact the founder" or "Message [First Name]" link? → that email wins, discard any generic ones.

### Rule 2 — The business must be reachable as a buyer, not as a support desk

**REJECT the lead entirely if ANY of these hit:**
- Company is Fortune 500, ASX 200, FTSE 100, or JSE Top 40 (maintain a public list; refresh quarterly)
- Website has a "Partners" or "Reseller" portal with gated login (= enterprise sales)
- Company employs > 500 people (check LinkedIn company page `staff_count`)
- Domain matches any government/education pattern (regex below)
- The company is itself a competitor (see per-campaign exclusion lists)
- No email domain match: if the email is `founder@gmail.com` but the company website is `acme.com.au`, demand a work email OR verify owner identity another way

**Government/education domain reject regex** (apply to email domain):
```
\.gov(\.|$)|\.gov\.[a-z]{2}$|\.edu(\.|$)|\.ac\.[a-z]{2}$|\.ndia\.gov|\.hmrc\.gov|\.ato\.gov|\.sars\.gov|^(parliament|assembly|senate|whitehouse|council)\.
```

### Rule 3 — Revenue proof: the company must be able to pay

- Website has pricing OR a product catalogue
- OR company has public revenue signals (press, funding round, award value, review count ≥ 20)
- OR company is on a prequalification register (pay-to-play filter)
- Reject "coming soon" sites, parked domains, Wix-default templates with no custom content

### Rule 4 — Trigger freshness: a buying moment in the last 90 days

Every lead needs a dated trigger. Without a trigger, don't send.

Allowed triggers (one of):
- `award_won`: public contract award dated last 12 months (12mo because government contracts are long cycles)
- `new_license`: business registration or free-zone license last 90 days
- `recent_funding`: funding round announcement last 180 days
- `prequalification`: joined/renewed prequalification last 12 months
- `ndis_registration`: NDIS registration added last 12 months
- `active_ad`: Meta/Google ad active in last 30 days targeting a country we care about
- `recent_review`: Google/Trustpilot review on their business ≤ 30 days old (proves trading)

**Reject leads with no trigger. Log them to `candidates_no_trigger.jsonl` for later review.**

### Rule 5 — Jev scoring is non-negotiable

Every lead must pass through Jev's `score()` before being added to the campaign's seed. If Jev returns `None` (API down), **hold the lead, don't skip it** — queue in `pending_jev.jsonl` for later rescore.

**Jev call pattern (lifted from the engine):**
```python
# See engine/<campaign>.py for the exact JEV_Q per campaign.
# Jev uses TYPESAFE_API_KEYS (pool, comma-separated) now; falls back to TYPESAFE_API_KEY.
from util import jev
s = jev(context_string, CAMPAIGN_JEV_Q)
if not s: queue(lead)                       # don't drop — Jev might be down
if not s["ok"]: discard(lead, "jev_fail")   # discard with reason, for audit
if s["score"] < MIN_SCORE: discard(lead, f"score_{s['score']}")
```

### Rule 6 — Dedupe is sacred

Before writing a lead to any campaign seed:

1. Normalise email to lowercase, strip +tags (e.g. `sarah+shop@` → `sarah@`)
2. Check against `seed/acd_contacted.csv` (global contact history — ACD legacy + modern)
3. Check against each campaign's own `state/sent.json` on the Railway volume
4. Check against the campaign's current `seed/*.json` pool (don't re-add)
5. Domain-level dedupe: never more than 2 addresses per domain in the same campaign
6. If any check hits, **skip and log to `dedup_skipped.jsonl`**

### Rule 7 — Output JSON schema (same across all campaigns)

```json
{
  "email": "sarah.jones@acmetrades.com.au",
  "domain": "acmetrades.com.au",
  "name": "Acme Trades Pty Ltd",
  "country": "AU",
  "trade": "electrical",
  "state": "NSW",
  "trigger": {"kind": "award_won", "date": "2026-09-15", "ref": "CN12345", "value": 240000, "buyer": "Dept of Defence"},
  "signals": {
    "owner_confidence": "high",
    "revenue_proxy": "awardtotal_2026=1.2M",
    "staff_estimate": 15,
    "website_live": true
  },
  "source_tag": "tw_p1_austender_awardwinner",
  "scraped_at": "2026-11-05T02:14:09Z",
  "jev_score": null,
  "jev_ok": null
}
```

The Jev fields are null at scrape time; the engine's prescore step fills them.

---

## TenderWin (AU) — source-by-source tactical spec

### Source 1 (PRIORITY): AusTender awarded-contracts feed

**URL:** `https://www.tenders.gov.au/Contracts/Search/Download?type=Csv`
Alternative API (JSON, undocumented): `https://www.tenders.gov.au/Contracts/Search/Advanced?...&_rsc=...`

**Filter parameters (set on the search page then export):**
- `awardDateFrom = (today - 365 days).ISO`
- `awardDateTo = today.ISO`
- `value_min = 100000` (contracts under $100k are usually variations, not open bids)
- `value_max = 10000000` (over $10M = mega-prime contractor, not our ICP)

**Fields to extract** (CSV column names):
- `CN ID` → `trigger.ref`
- `Contract Start Date` → `trigger.date`
- `Value (AUD)` → `trigger.value`
- `Agency` → `trigger.buyer`
- `Supplier Name` → `name`
- `Supplier ABN` → `signals.abn`
- `Category` → category text to classify into `trade`

**Trade classification:** apply the TRADE_RX dict from `engine/tenderwin.py` to the Category + the contract description. If no regex matches, drop the row (we don't send into trades we don't bucket).

### Source 2: ABR enrichment → website lookup → owner email

For each ABN from source 1:

1. **ABR lookup** (free, no key):
   `https://abr.business.gov.au/json/AbnDetails.aspx?abn={abn}&callback=&guid=`
   Extract: `EntityName`, `EntityTypeName`, `AddressState`, `AddressPostcode`, `EntityStatus`.
   **Reject if** EntityStatus ≠ "Active" OR EntityTypeName contains "Government" / "Public Authority" / "Religious".

2. **Website discovery:**
   - Google/TinyFish search: `"{EntityName}" site:{state}.gov.au -gov -council` to check it's NOT a gov supplier page
   - Fallback: Firecrawl search `{EntityName} ABN {abn}` → first result that's a `.com.au` or `.net.au`
   - Reject if no website found after 3 attempts (= ghost company, not reachable)

3. **Contact-page scrape** (Firecrawl `scrape` mode, extract `markdown`):
   - Try URLs in this order: `/contact`, `/contact-us`, `/about`, `/about-us`, `/`
   - Extract emails matching `EMAIL_RX` from `engine/util.py`
   - **Only keep emails whose domain matches the website domain** (reject `founder@gmail.com` when site is `acmetrades.com.au`)
   - Apply Rule 1's role-inbox reject regex
   - Pick the lowest-tier email (`firstname.lastname` beats `firstname`, which beats `info` if company ≤ 10 staff)

4. **Owner identity signal (bonus):**
   - Scrape `/team`, `/about`, LinkedIn company page
   - If a Director/Owner/Founder's name matches the email's local-part → `owner_confidence=high`
   - Otherwise → `medium`

### Source 3: State prequalification registers

| State | URL | API? | Filter |
|---|---|---|---|
| NSW | `buy.nsw.gov.au/schemes/prequalification` | HTML scrape | Scheme-specific; export the supplier list |
| VIC | `buyingfor.vic.gov.au/registers` | HTML scrape | Current panel members |
| QLD | `forgov.qld.gov.au/procurement/buying-selling/panels-prequal` | HTML scrape | PQC active |
| WA | `tenders.wa.gov.au/registered-suppliers` | HTML scrape | Active only |
| Federal | `dta.gov.au/our-work/digital-marketplace` | JSON API `marketplace.service.gov.au/api/2/suppliers` | On panels, active |

**Dedupe vs source 1:** if the supplier won a contract in the last 12mo, use the source-1 record. Only add prequal-only firms as separate leads.

### Source 4: Supply Nation Indigenous suppliers

**URL:** `supplynation.org.au/find-members`
**API?** Not public; scrape HTML with Firecrawl (pagination).
**Extract:** business name, city, state, trade categories, website URL (public on each member page).
**Reject:** members without a website or with only `info@supplynation.org.au` contact.
**Flag:** `signals.indigenous_business = true` — this unlocks the P3 opener variant.

### Exclusions (TenderWin)

**Hard-block list — do not even score:**
- `downergroup.com`, `ventia.com`, `cimicgroup.com`, `lendlease.com`, `transurban.com`, `telstra.com.au`, `optus.com.au`, `nbnco.com.au`
- All Big-4: `deloitte.com.au`, `pwc.com.au`, `ey.com`, `kpmg.com.au`
- Universities, hospitals, local councils, state government bodies
- Anything on the `seed/acd_contacted.csv` global suppress list

### Jev call signature (TenderWin)

```python
state_str = (
    f"Australian business: company='{EntityName}', trade='{trade}', state='{state}', "
    f"email='{email}', award_buyer='{buyer}', award_value='A${value:,}', award_date='{date}', "
    f"source='{source_tag}', has_website={website_live}, staff_estimate={staff_estimate}"
)
# JEV_Q from engine/tenderwin.py
s = jev(state_str, JEV_Q)
# ok = bids_gov >= 0.6 AND owner_reads >= 0.5
```

### TenderWin lead volume target

**P1 (award winners):** 5,000–15,000 scored, 3,000–8,000 clean after Jev. **This alone is 60 days of send capacity.**
**P2 (prequal):** +2,000 clean. Mix in once P1 queue is below 1,000.
**P3 (Supply Nation):** +500 clean. Mix in once P2 is below 500.

---

## BidCheck (SA) — source-by-source tactical spec

### Source 1 (PRIORITY): eTenders awarded contracts + CSD cross-reference

**URL for awards:** `etenders.treasury.gov.za/content/awarded-tenders` (HTML, paginated, Firecrawl scrape)
**Fields per row:** Tender Number, Department, Description, Supplier Name, Award Date, Award Amount.

**Filter:**
- `Award Date >= 2024-01-01` (24 months — SA has longer buy-side cycles)
- `Award Amount >= R50,000` (anything under is usually a quote, not a bid-won contract)
- Supplier Name contains a corporate suffix (`(Pty) Ltd`, `CC`, `Limited`, `Inc`) — if it doesn't, it's a sole-trader, usually a weaker ICP

**CSD cross-reference:**
- URL: `csd.treasury.gov.za/Account/VerifyRegistration` (public lookup by supplier name)
- Extract: CSD number, CSD status, registration date
- **Keep lead only if CSD status = "Active"** — this is the biggest filter for paid-conversion probability

**Website discovery:**
- Firecrawl search: `"{Supplier Name}" site:*.co.za` (South Africa TLD only)
- Reject if no `.co.za` or `.com` site found with SA address
- Reject if site is a WordPress default template

**Contact-page scrape:** Same as TenderWin source 2.step 3. Apply Rule 1 reject regex.

### Source 2: CIDB construction register

**URL:** `register.cidb.org.za/Reports/Contractors.aspx` (public search form)
**Filter:**
- Grade = 2, 3, 4, or 5 (grade 1 is too small, grade 6+ competes with the big primes)
- Status = Active
- Class of Works: one of `GB` (General Building), `CE` (Civil Engineering), `EB` (Electrical), `ME` (Mechanical), `SH` (Specialist: specialist trades)

**Extract:** CIDB reg number, trading name, province, grade, class, website (if present).

**Dedupe vs source 1:** if the firm already won an award, source 1 record wins.

### Source 3: SARS tax clearance holders (if accessible)

Partial public data via SARS eFiling query — need to verify if a scraping-tolerated endpoint exists. Lower priority; nice-to-have signal.

### Exclusions (BidCheck)

**Hard-block domain list** (seen in 14-day reply log — all were noise):
- `paintnite.com`, `terminal49.com`, `elpdata.com`, `subser.com`, `kayiseit.com`, any `.com` where WHOIS shows US/EU/IN/UK registration
- Big 4 (SA offices): `deloitte.co.za`, `pwc.co.za`, `ey.co.za`, `kpmg.co.za`
- State enterprises: `eskom.co.za`, `transnet.net`, `sapo.co.za`, `satensa.gov.za`
- Any `.gov.za` or `.ac.za`

### Jev call signature (BidCheck)

The BidCheck sender is separate (`bidcheck-deploy/send.py`), so the scraping agent produces leads in a different format. Use the same output schema as above with `country="ZA"`.

### BidCheck lead volume target

**P1 (CSD + award):** 2,000–5,000 scored, 1,500–3,500 clean. **Target 60–90 days of sending at current cap.**
**P2 (CIDB 2-5):** +3,000 clean.
**Expected quality lift:** from today's ~0.8% reply (noisy) to 1.5% (clean) and from ~0% paid to ~15–20% YES-to-paid (because the leads can actually afford R299/mo).

---

## NameMarshal (JP + UAE) — source-by-source tactical spec

> **The .nl leak is the lesson. Every lead must have `country ∈ {JP, AE}` verified by TWO independent signals (not just TLD).**

### Country verification (MANDATORY)

Before writing any lead to the NM seed, verify country with BOTH:

1. Business address shown on website, press, or registry → extract country
2. Email domain country code OR WHOIS country → country code

If the two disagree (e.g. site says "Tokyo" but WHOIS says "NL"), **skip the lead** and log to `nm_country_mismatch.jsonl`.

### Source 1 (PRIORITY): Japan Amazon.com storefronts

**Approach:** search Amazon.com for products with "Ships from Japan" filter, extract seller storefronts, then find each seller's independent website.

**Step 1 — product discovery:**
Amazon.com search URL pattern:
```
https://www.amazon.com/s?k={category}&rh=p_6%3A{seller_country_filter}
```
Category list (rotate through): watches, tea, stationery, handmade, kitchenware, matcha, skincare, bento, washi, pottery, denim, workwear.

**Step 2 — seller extraction:**
From each product page, extract "Sold by {seller name}" link → seller storefront URL → "About Seller" page → business name, address.
Keep only if address is in Japan.

**Step 3 — independent website discovery:**
Firecrawl/Google search `"{seller name}" site:*.jp OR site:*.co.jp OR site:*.ne.jp`
Fallback: TinyFish Agent run (uses $0.016/step from $8 wallet):
```
{
  "url": "https://www.google.com/search?q=\"{seller}\"+shop+Japan",
  "goal": "Find the seller's official independent website (not Amazon or Rakuten). Return the URL."
}
```

**Step 4 — owner email:**
Firecrawl `/contact` or `/about`, extract email. **Reject if `support@`, `cs@`, `customer@`, `info@`.** Japan uses `info@` as the catch-all almost universally — only accept if the About page shows ≤ 3 named staff. Strongly prefer a `firstname@` or Japanese name local-part.

### Source 2: Dubai free-zone member directories

| Free zone | URL | Notes |
|---|---|---|
| DMCC | `dmcc.ae/members-directory` | 20,000+ members; filter by sector |
| DIFC | `difc.ae/business/public-register` | Financial services heavy — skip unless e-commerce |
| ADGM | `registration.adgm.com/public-registry` | Partial public |
| Hub71 | `hub71.com/startups` | ~250 portfolio startups |
| in5 | `in5.ae/startups` | Design/tech focused |
| Dubai Internet City | `dubaiinternetcity.com/community/members` | Tech companies |

**Filter per directory:**
- Licensed in last 24 months (for DMCC); last 12 months (for Hub71/in5)
- Sector in: E-commerce, Retail, Consumer Goods, SaaS, Digital Services, Food & Beverage
- **Reject sectors:** Oil & Gas, Real Estate, Construction (local, not US-selling), Hospitality, Finance (regulated, already US-aware)

**Owner identity:**
- DMCC lists the company name only; website discovery as per NM source 1 step 3
- Hub71/in5 list founder names on the startup page — use that to prefix email guess
- Email guess pattern: `{firstname}@{domain}` is often correct for UAE startups; verify by sending a test to a verification service before adding to seed

### Source 3: Rakuten / STORES / BASE cross-border sellers

| Platform | URL | Signal |
|---|---|---|
| Rakuten Global Market | `global.rakuten.com/en/` | Explicit international-shipping flag |
| STORES.jp | `stores.jp/directory` | Enable "International shipping" filter |
| BASE.ec | `thebase.in/discovery` | "海外配送対応" flag |

Owner email: scrape the seller's own site (links from the platform page to their independent site). Same rules as source 1.

### Source 4: Meta Ad Library reverse lookup

**URL:** `facebook.com/ads/library/?active_status=active&ad_type=all&country=US&view_all_page_id=...&source=page-transparency-widget`

**Approach:**
1. Search Ad Library for ads active in the US
2. For each ad, check the advertiser's Page info → Page Transparency → Primary country
3. Keep only pages where Primary country = JP or AE
4. Extract the advertiser's website URL

This is harder than other sources; treat as supplementary.

### Source 5: JETRO cross-border programme participants

**URL:** `jetro.go.jp/en/success/ecommerce/` and `jetro.go.jp/en/success/consumer/`
Public case-study pages list participating companies by name. Low volume (50-300 total) but all are owner-committed to US expansion.

### NM-specific exclusions

- Any Shopify/platform support desk (`support@company.com` where company's whois is Shopify Inc)
- Any domain whose WHOIS country ≠ JP and ≠ AE, regardless of what the site says
- Big brands: `nordgreen.com`, `anker.com`, `ugreen.com`, `baseus.com`, `uniqlo.com`, `muji.com`
- Any company whose ABOUT page mentions "US office" or "Delaware incorporated" or "LLC" (they already have the entity)

### Jev call signature (NameMarshal)

Same `state_str` pattern as existing `engine/namemarshal.py` but with the enriched signals:
```python
state_str = (
    f"E-commerce store: name='{store}', domain='{domain}', country='{country}', "
    f"products={products_count}, reviews={review_count}, address='{business_address}', "
    f"amazon_seller={amazon}, ships_to_us={ships_us}, source='{source_tag}'."
)
```

### NameMarshal lead volume target

**P1 (JP Amazon):** 500–2,000 scored, 300–1,200 clean. Lower volume, higher quality.
**P2 (Dubai free zones):** 1,000–3,000 scored, 500–1,500 clean.
**P3 (Rakuten/BASE/STORES):** 300–800 clean.
**Expected quality lift:** from currently-contaminated pool (5/14 recent replies were .nl) to all-AE/JP with verified US-selling signal. Reply rate should roughly double to ~2%, and conversions start flowing because Doola's $300–$1,000 formation fits a real buyer.

---

## ACD (AU) — source-by-source tactical spec

### Source 1 (PRIORITY): NDIS Provider Finder

**URL:** `ndis.gov.au/participants/working-providers/find-registered-provider`

**Scrape pattern (using TinyFish Agent, ~3–5 steps per query):**
Agent prompt:
```
Go to ndis.gov.au/participants/working-providers/find-registered-provider.
Select state = {state}. Select registration group = {group_id}.
Click search. For each result on the page, extract:
- Business name
- Registration ID
- Address + postcode
- Registration groups
- Website URL (click into the detail page)
Return a JSON array of results.
```

Loop over: state × registration_group combinations.
Registration groups to prioritise (biggest pay-per-intro value):
- `0107` Daily Personal Activities
- `0115` Household Tasks
- `0117` Development of Daily Living and Life Skills
- `0128` Therapeutic Supports
- `0106` Assistance with Social, Economic and Community Participation
- `0120` Household and Yard Maintenance

**Cross-check:** After scraping, verify each provider's registration is still active via a direct ABN lookup on ABR.

### Source 2: My Aged Care HCP provider finder

**URL:** `myagedcare.gov.au/find-a-provider`

Same Agent pattern as Source 1. Scrape by postcode (loop through metro postcodes in each state). Extract HCP provider details.

**Filter:**
- Provider type = Home Care Package only (not residential)
- At least one package level listed (1, 2, 3, or 4)
- Website present

### Source 3: State NDIS worker screens + association member directories

- `nds.org.au/membership/find-a-member` (National Disability Services member directory)
- `community.ndis.gov.au/providers`

### Owner-reach for ACD

ACD is Australia; email conventions are more informal. Most providers list the Director or Owner by name on the About page. For leads ≤ 20 staff:
- `firstname@` or `firstname.lastname@` is the owner → `owner_confidence=high`
- `info@` or `enquiries@` is the owner too for ≤ 10 staff → `owner_confidence=medium`, keep
- `admin@` or `office@` on ≤ 10-staff provider → `owner_confidence=medium`, keep but deprioritise

### ACD-specific exclusions

Hard block (replied "remove" historically):
- `bupa.com.au`, `estia.com.au`, `uniting.org`, `baptistcare.org.au`, `anglicare.com.au`, `cathhealth.org.au`, `allity.com.au`, `opalhealthcare.com.au`, `regisagedcare.com.au`, `juniper.org.au`
- All hospitals (regex: `\bhosp|hospital\b`), councils, universities, LHDs (Local Health Districts)
- Equipment suppliers (the old legacy pitch — regex: `equipment|mobility|wheelchair|aids|supplies` in trading name)

### Jev call signature (ACD)

Same as `engine/acd.py`:
```python
state_str = (
    f"Australian business listing: company='{company}', email='{email}', city='{city}', "
    f"state='{state}', directory_source='{source}', ndis_reg='{ndis_id}', ndis_groups='{groups}'."
)
```
`ok = takes_clients >= 0.65 AND owner_reads >= 0.5`

### ACD lead volume target

**P1 (NDIS registered, priority groups):** 5,000–10,000 scored, 3,000–6,000 clean.
**P2 (HCP providers):** 2,000–5,000 scored, 1,500–3,000 clean.
**Reply-rate target:** 4% (up from 0.9%) — pure targeting lift, no copy change beyond the commission line that shipped today.

---

## The dumb-agent kill switches

Three guardrails the scraping agent can't bypass:

1. **Country-verification gate** (NM only): two independent signals must agree. If not, skip + log.
2. **Owner-confidence gate** (all campaigns): leads with `owner_confidence=low` are written to `candidates_lowconfidence.jsonl` and **never** merged into a campaign seed. Owner reviews weekly.
3. **Jev score gate**: `jev_ok=false` leads go to `discards.jsonl`. **Never into the live pool.** The engine's prescore already enforces this; the scraping agent respects the same rule before writing.

**Rate limits for safety:**
- Max 300 new leads per campaign per day added to the pool (anything more and we overload AgentMail bounce guards)
- Max 2 scrape jobs per source per day (we don't want to hammer public registries)

**Monitoring:**
- Daily digest from the scraping agent (separate from the sending engine's digest):
  - scraped: {campaign: N}
  - jev_passed: {campaign: N}
  - discarded_by_reason: {role_inbox: N, no_trigger: N, country_mismatch: N, ...}
  - added_to_seed: {campaign: N}

---

## Deploy checklist for Jev key-pool

Four Railway services need `TYPESAFE_API_KEYS` set. Owner runs these (classifier blocks the agent from writing Railway secrets):

```bash
set -a; . ~/AutoClaw/Shared/.secrets/keys.env; set +a
export RAILWAY_API_TOKEN="$RAILWAY_TOKEN_TENDERWIN"
for SVC in \
  80f02a60-6df5-4f4c-88be-83ff23a4fc12 \
  9614178d-b3c4-4cdb-8722-311d9f019cb1 \
  5a76bd60-5021-408c-b15c-eb6a68d6ebc3 \
  4c83fa0a-36fa-4fa2-a922-7b43e903c013 ; do
  npx --yes @railway/cli@latest variables \
    --set "TYPESAFE_API_KEYS=$TYPESAFE_API_KEYS" \
    --project 3541d8e7-aaec-46b8-ab1a-5a03eee845d9 \
    --environment 1820ffc0-e3de-4662-a2c9-b4a7b5ccdc93 \
    --service "$SVC" --skip-deploys
done
```

After that runs, the three engine services and BidCheck see the pool on next restart (Railway auto-restarts on var change unless `--skip-deploys` keeps it off; next deploy or 30-min cron tick picks it up).

---

*Last updated 2026-11-04. Related docs: `TARGETING-PLAN.md` (strategic priorities), `COLD-EMAIL-PACK.md` (templates).*
