# Targeting plan — four campaigns, ranked for money

**Built:** 2026-11-04 after 14-day mailbox audit, PostHog read, industry scan.
**Goal:** every send comes from a scored, triggered, decision-maker-reachable lead so reply rate goes from the current 0.3–1.4% to 2–5% and interested replies convert to paid.
**Handover to the scraping agent:** this document is the source of truth for who to scrape and who to skip. Edits here, not in the engine.

---

## The one principle that governs all four campaigns

A lead is worth emailing only when it clears **three gates**:

1. **Trigger** — a public event in the last 90 days that says "this problem is live for them right now."
2. **Pay** — a revenue signal showing they can afford the offer (reviews, catalogue size, past contract value, licensing cost).
3. **Reach** — a path to the owner/decision-maker, not a support desk or a `info@` catch-all.

Fail any of the three, don't send. The current pool is maybe 20–40% clean by this rule; harvesting without this filter is why reply rates are stuck below 1%.

---

## 1. TenderWin (AU) — biggest money upside, already the best performer

**Why it wins:** real deadline, real dollar amount, the problem is universally felt.
**Current reply rate:** ~0.4% (best of the four).
**Target reply rate:** 2–3% with the plays below.
**Money path:** free account → free bid fit-check → done-for-you first bid (R2,500 equiv) → Starter A$ plan → Pro.

### Priority 1 — Recent award winners (highest LTV per send)

**Why:** they've already proven compliance (ABN, GST, insurance, past-performance references). They've been through a bid and know the pain. They can afford the subscription because they just won revenue.

**Source:** AusTender awarded contracts feed — **we already ingest this**. Query:
- `vula_awards` where `award_date >= today - 365 days` and `value >= $100,000` and `vendor_abn` is set.

**Signals to filter on:**
- ≥1 contract awarded in last 12 months
- Not on the exclusion list (large listed cos, government bodies, universities)
- ABN resolves to a trading entity with a website (verify via ABR lookup → website found on Firecrawl search)
- Trade matches one of the 15 TRADE_RX buckets in `engine/tenderwin.py`

**Expected pool:** 5,000–15,000 names (AusTender publishes ~100,000 awards/yr; filter to trades + size cutoff).

**Opener:** the existing `_award_line(lead)` is already perfect — "Saw {co} won work from {buyer} ({month}). Nice." Keep.

### Priority 2 — Prequalified panel suppliers (proven bidders, haven't won recently)

**Why:** they paid the money to get prequalified but haven't landed a contract in a while. High intent, high frustration with the status quo.

**Sources (public):**
- **NSW:** NSW Prequalification Scheme supplier register (`buy.nsw.gov.au/schemes/prequalification`)
- **VIC:** VicGov eServices register
- **QLD:** PQC (Prequalified Contractors) register
- **WA:** WA Tenders registered suppliers list
- **Federal:** DTA ICT Panels (digital, cloud) — expect lots of consulting firms

**Signals to filter on:**
- Prequalified in the last 24 months
- No contract >$50k on AusTender in last 18 months (hungry, not resting)
- Small/mid business (not the Big-4, not Downer, not Transfield)

**Expected pool:** 3,000–8,000.

### Priority 3 — Indigenous Procurement Policy (IPP) beneficiaries

**Why:** federal IPP requires 3% of contracts and 5% by value to go to Indigenous businesses. Supply Nation members have a procurement advantage AND a specific pain (knowing which contracts count toward IPP targets).

**Source:** Supply Nation member directory (`supplynation.org.au/find-members`) — public, searchable, ~5,000 members.

**Signals:**
- Member for ≥1 year
- Website functional, email on contact page
- Trade overlap with active federal procurement

**Opener variant** (add to `engine/tenderwin.py` arm D): "Saw {co} on Supply Nation. The ATO/Defence IPP targets mean they're actively looking for Indigenous suppliers in {trade} right now — want me to send what they've got open?"

### Priority 4 — Head contractors needing subcontractors

**Why:** when a Lendlease wins $200M civil work, they need 30–50 subbies. Opens a subcontractor marketplace angle.

**Source:** AusTender awards where value ≥ $5M → look up the vendor → scrape their "supplier" / "become a subcontractor" pages.

**Expected pool:** 100–300 head contractors that regularly win big. Too narrow for cold volume; good for a separate sub-campaign + manual outreach.

### Explicit exclusions

- Councils, state agencies, departments, universities, hospitals, schools (they ARE the buyers)
- Big 4 consulting (Deloitte, PwC, EY, KPMG)
- ASX200 listed firms (Downer, Transfield/Ventia, CIMIC/CPB, Lendlease ops)
- Businesses with no recent AusTender presence AND no prequalification AND no Supply Nation flag — they're probably not in market

### Industry benchmarks to beat

- **TenderLink** (the market leader) claims 50,000+ AU suppliers. We can emulate their reach by systematically scraping AusTender awards (public since 2006).
- **TendersAU / TenderSearch** push alerts via email, no AI, charging $99–$500/mo. Our wedge: TenderWin reads the pack (pack-reader is live per project memory), scores fit against the ABN, and gives a one-page "can you bid" answer.

### Measurement / kill rules

- If the Priority-1 arm is below 2% reply rate after 500 sends, open the openers (not just the subject).
- Track `arm_log.jsonl` + `sent_log.jsonl`. Every weekly digest should show: sends, replies, builds (people who clicked "walk me through"), paid signups.

---

## 2. BidCheck (SA) — fix the YES-but-no-payment leak

**Why it matters:** fit-check replies arrive but nobody pays R299/mo. Either the price is too high for the segment, or we're reaching people who can't convert. The data says the latter.

**Current reply rate:** ~0.8% (middle of the pack); **paid conversions: ~0** in 14 days.

**Target:** 1.5% reply rate AND 10% YES-to-paid conversion within 30 days.

### The problem with the current pool

Spot-checked the 14-day reply log:
- 5 of the "interested" replies came from `.com` domains (Terminal49, Paint Nite customer-support, ELP Data, Subser) — **these are US/global tech companies that got caught in our net by broad keyword matching.** Zero chance of paying R299/mo for SA government tender alerts.
- The 4 real wins (Khumalo Electrical, Alstan, LL Plumbing, UniBuilders) are small SA trades — the right ICP. They're buried under the noise.

### Priority 1 — CSD-registered + past award winner (will pay)

**Why:** paying the CSD registration effort already filters out the dabblers. Winning a past award proves fit. These are the people most likely to pay R299/mo.

**Source:**
- National Treasury eTenders awards feed (`etenders.treasury.gov.za`) — we scrape this already.
- Cross-reference: CSD public directory (`csd.treasury.gov.za`) — **partial public access** via contractor number.
- Join: vendor name → CSD registration → award history.

**Signals:**
- ≥1 government contract won in last 24 months (any province, any value ≥R50,000)
- Trade in: Cleaning, Security, Construction, Civil, Electrical, Plumbing, ICT, Supplies
- Based in RSA (domain ends `.co.za` OR website shows SA address OR company is a (Pty) Ltd)
- Owner-reachable (email domain matches company domain OR Gmail/personal but with a first name in the local-part)

**Expected pool:** 2,000–5,000 clean leads. **Much tighter than the current pool, but much more conversion-ready.**

### Priority 2 — CIDB-registered construction/civil firms

**Why:** CIDB grades are required to bid on most construction tenders. A firm paying CIDB fees annually is serious.

**Source:** CIDB register of contractors (`register.cidb.org.za/Reports/Contractors.aspx`) — public, searchable by grade, class of work, province.

**Signals:**
- CIDB grade ≥2 (grade 1 is too small; 2–5 is the ICP sweet spot for R299/mo)
- Active registration (not lapsed)
- Province overlap with provinces where open tenders cluster

**Expected pool:** 15,000–30,000 CIDB-registered firms; filter to grade 2–5 + email on their website = ~3,000–6,000 reachable.

### Priority 3 — Lost bidders (shortlist losers)

**Why:** they bid, they didn't win, they know exactly what they're missing. The highest-intent cold target in SA government procurement.

**Source:** eTenders "bid response" pages. Publicly discloses which vendors submitted but weren't awarded. Requires HTML scraping of the tender detail page after award is announced.

**Signal:** vendor submitted on 2+ tenders in last 6 months, won 0.

**Expected pool:** 500–2,000, extremely qualified. Treat as a separate manual-reviewed lane.

### Explicit exclusions

- `.com` domains with no SA entity (Paint Nite, Terminal49-style noise)
- Catch-all `info@` emails unless company is <10 people
- Councils, hospitals, universities, government bodies, parastatals (Eskom, Transnet, SA Post)
- Any lead whose email domain is `gmail.com`/`webmail.co.za`/`yahoo.com` AND company is >20 people (that's a staff member's personal, won't make the buying decision)

### The real fix for YES-not-paid

The copy change (post-YES fit-check with countdown + R299-vs-contract-value + "reply walk me through") only helps if the YES is from someone who *could* pay R299/mo. A Paint Nite support agent replying "yes" is noise, not pipeline. **Priority 1 targeting is the fix.**

### Industry benchmarks

- **eTender** (free, government-run) — this is the "free" alternative. BidCheck's wedge is the fit-check, the pack reading, and the briefing dates.
- **GreenBooks**, **Companii** — paid SA tender aggregators at R800–R2,000/mo. We're cheaper and more targeted.
- **Blue-chip pattern:** tender aggregators in SA all push weekly/monthly digests. Our daily-digest email is the engagement moat.

### Measurement / kill rules

- If Priority-1 pool below 1.5% reply AND <5% YES-to-paid after 500 sends, the pricing is wrong, not the copy. Revisit R299.
- `sent_log.jsonl` already tracks `v` (arm). Add a `paid` boolean at Stripe webhook time (future work, not in this commit).

---

## 3. NameMarshal (JP + UAE) — targeting is broken, fix pool before volume

**Owner's handover said 1.4% reply rate.** My own read of the 14-day log said 0. Both can be true: BuyandShip chased twice (that's a lead), most of the other "human" replies were support-desk auto-replies classified as human.

**The real issue: 5 of 14 'namemarshal' replies came from `.nl` (Netherlands) domains.** NL isn't in the target country list. **The pool has drifted off policy.** The scraping agent's first job is enforcing AE + JP.

### Priority 1 — Japan Amazon.com sellers (highest conversion potential)

**Why:** actively selling to US customers, clear revenue signal (Amazon catalogue + reviews), the payments-pain is concrete (JP yen → US $, FX spread, payout to a Japanese bank).

**Source:**
- Amazon.com search for "ships from Japan" + category keywords
- Storefront page → "About the seller" → business address in Japan → owner contact
- Fallback: find the seller's independent Shopify or BASE store via Google

**Signals:**
- ≥50 reviews on at least one listing (= real revenue)
- "Ships from Japan, sold by [vendor name]"
- Own website exists and has a contact email
- Not a famous brand already with US operations (filter: too_big in JEV scoring)

**Expected pool:** 500–2,000 Japan-based Amazon.com sellers that are findable + owner-reachable.

**Use the TinyFish keys for this** — Search (free, 30 qpm) + Fetch (free, 150 rpm) gives 300 qpm aggregate across 10 keys. Enough to scan tens of thousands of Amazon search results in a day.

### Priority 2 — Dubai free-zone new-license directories

**Why:** new companies setting up in DMCC, DIFC, Hub71, in5 are looking at global expansion from day one. The US entity question hits before they launch.

**Source (public):**
- DMCC Member Directory (`dmcc.ae/member-directory`) — public, searchable
- DIFC Public Register — public, limited search
- Hub71 portfolio (`hub71.com/startups`) — public
- in5 startup directory — public
- ADGM Public Register — public

**Signals:**
- Licensed in the last 12 months
- Sector: ecommerce, SaaS, consumer brands, services sold globally (NOT: oil/gas/real-estate/hospitality)
- Founder named on the listing → LinkedIn lookup → direct email via Hunter/TinyFish fetch

**Expected pool:** 1,000–3,000 recently-licensed, US-selling or US-planning companies.

### Priority 3 — Rakuten/STORES/BASE cross-border sellers (Japan)

**Why:** these three platforms are Japan's Shopify equivalents. Sellers who enabled cross-border shipping are telegraphing "we want international revenue."

**Source:**
- Rakuten Global Market seller list
- STORES.jp directory (filter: cross-border shipping enabled)
- BASE.ec directory (filter: international checkout enabled)

**Signals:**
- Active in last 90 days
- English/multi-language store OR confirmed US orders (reviews, press mentions)
- Owner email on the About page

### Priority 4 — Meta Ad Library reverse lookup

**Why:** a UAE or Japan Facebook/Instagram page running ads targeting US audiences is spending money to acquire US customers but not optimising the backend.

**Source:** Meta Ad Library (`facebook.com/ads/library`) — public API; filter by country of advertiser = AE or JP, country of audience = US.

**Signals:**
- Ads active in last 30 days
- Page has website URL
- Not already a Fortune-500 brand

**Expected pool:** harder to size; probably 500–2,000 high-signal leads.

### Priority 5 — JETRO cross-border participants

**Why:** JETRO (Japan External Trade Organization) runs programs specifically for Japanese SMEs selling overseas. Participating = owner-level commitment to international growth.

**Source:** JETRO's program case-study pages (public, in Japanese + English) list participating companies by name.

**Expected pool:** small (50–300) but very warm — pair with priority 1 for a hybrid.

### Explicit exclusions (REINFORCE)

- **Any domain country code outside `.ae`, `.jp`, `.co.jp`, `.com` with verified AE/JP business, `.ne.jp`** — the .nl problem is the whole lesson here.
- Fortune-500 brands (already have US counsel)
- SaaS platforms, agencies, or consultancies (they likely already have US entities)
- Support@/info@/customer-service@ inboxes without a first name
- Any Amazon seller with <20 reviews (not enough revenue to justify formation fees)

### Industry benchmarks

- **Doola** (the partner): charges $297–$1,999 for LLC formation. Takes affiliate commission ~30% (unconfirmed). High-ticket.
- **Firstbase** (competitor): $399 formation. Direct US VC backing.
- **Clerky**: $100–$400, for US founders only — not our ICP.
- **Stripe Atlas**: $500 all-in. The default for YC-backed startups. If a founder is YC, they went Atlas already.

Where we win: non-US founders who don't know they can get an EIN without SSN. That's the wedge, and the subject lines now lead with it.

### Measurement / kill rules

- If Priority-1 pool (JP Amazon) returns <1% positive reply after 300 sends, the Amazon-seller ICP is wrong and we should move all budget to priority 2 (Dubai new licenses).
- Track `arm` + `country` in `arm_log.jsonl` and funnel to Doola checkout via `utm_term=A|B|C` already baked in.

---

## 4. Aged Care Direct (AU) — model is now set, scale with intent

**Why this is unlocked:** the 10% commission model you confirmed today lets us finally answer "what are the terms" pre-emptively (arm C ships with it). Three providers asked verbatim; copy now pre-empts.

**Current reply rate:** ~0.9%.
**Target:** 3–5% once arm C stabilises.

### Priority 1 — NDIS-registered providers accepting new clients

**Why:** NDIS participants have funded plans, providers need pipeline. 10% of a first NDIS Home Care Package month = $150–$600/intro. Real money.

**Source:** NDIS Provider Finder (`ndis.gov.au/participants/working-providers/find-registered-provider`) — public, searchable, filter by:
- Registration group (e.g. 0107 Daily Personal Activities, 0115 Household Tasks)
- Postcode / state
- "Accepting new participants" flag (some providers surface it)

**Signals:**
- Registered + active
- ≥2 service categories (= real multi-service provider, more valuable intro)
- Not a national chain (Bupa, Estia, Uniting Care — they said "remove" historically)
- Website functional, email reachable

**Expected pool:** 5,000–10,000 clean providers.

### Priority 2 — Approved Home Care Package (HCP) providers

**Why:** HCP is government-funded; Package Levels 1–4 mean $9k–$55k/yr per client. 10% of first month = $75–$460/intro.

**Source:** My Aged Care provider finder (`myagedcare.gov.au/find-a-provider`) — public.

**Signals:**
- Approved HCP provider
- Not a hospital, aged-care residential facility (those are different beasts)
- Postcode coverage visible

### Priority 3 — Allied health + therapy under NDIS

**Why:** NDIS plans fund psychology, OT, physio, speech. These providers often have capacity and a referral model mindset.

**Source:** NDIS Provider Finder, filter group `0128 Therapeutic Supports`.

### Priority 4 — Disability support workers via Hireup/Mable (poach)

**Why:** independent support workers on gig platforms want direct relationships, not platform fees. Our 10% is lower than Mable's ~15% + their fees.

**Source:** platform listings (public profiles); need legal review before scraping.

### Explicit exclusions

- Councils, hospitals, universities (already on remove list from past sends)
- Equipment suppliers (the legacy "same-day equipment quotes" pitch is wrong — different campaign, already killed via commit)
- National chains that have replied "remove" historically — keep the suppression list clean

### Industry benchmarks

- **Hireup** — commission model, 30% of first month ongoing fees. **Our 10% is competitive but might be low on first-month-only** (they take ongoing % while platform relationship exists). Owner may want to revisit after 30 days of data.
- **Care For Family**, **BrightCarers**, **Just Better Care** — referral/matching platforms, different fee models.

### Measurement / kill rules

- If arm C (fees-first) under-performs arm A by 2026-11-11 (7 days), owner call: either the fees line scares people, or the commission % is wrong. Both are easy to adjust in `FEES_LINE`.
- Watch: "yes" rate with services+areas filled in (actionable leads) vs "yes" alone (needs follow-up).

---

## Scraping agent — the handover checklist

The scraping agent should produce these JSON files, one per campaign, in `~/projects/outreach-engine/seed/`:

| Campaign | File | Priority order (produce in this order) |
|---|---|---|
| TenderWin | `tw_award_winners.json` | P1 → P2 → P3 → P4 |
| BidCheck | `bc_csd_winners.json` | P1 (CSD+awards) → P2 (CIDB 2-5) → P3 (lost bidders) |
| NameMarshal | `nm_amazon_jp.json` + `nm_dubai_free_zone.json` | P1 → P2 → P3 → P4 → P5 |
| ACD | `acd_ndis_providers.json` + `acd_hcp.json` | P1 → P2 → P3 |

Each row must have:
```json
{
  "email": "owner@domain",
  "domain": "domain.com.au",
  "name": "Company Name",
  "trigger": "award_2026-09-15_$120k",   // or "cidb_grade_4", "dmcc_license_2026-10-01", etc
  "signals": {"revenue_proxy": "...", "reach_proxy": "..."},
  "country": "AU|ZA|JP|AE",
  "source_tag": "auTender_p1_awardwinner",
  "scraped_at": "2026-11-05T00:00:00Z"
}
```

- **Dedupe against `seed/acd_contacted.csv`** (shared contacted list) and against each campaign's own send-log before writing.
- **Prefilter must pass before scoring:** no gmail.com/yahoo.com with > 20-employee companies; no role@ inboxes; MX must resolve.
- **Jev scoring runs over the output** — the scraping agent just produces candidates; the engine scores.

### Rate limits & tooling

- **TinyFish:** 300 qpm aggregate (10 keys × 30 qpm) Search + 1,500 rpm Fetch. Use for public page reads, SERP enrichment.
- **Firecrawl:** for deeper scraping with rendering. Owner has 15+ keys in the pool file.
- **AusTender / eTenders / NDIS feeds:** direct API/CSV; no need for TinyFish.
- **Jev (TypeSafe):** the scoring gate — never skip.

### What the scraping agent should NOT do

- No sending.
- No auto-replies.
- No editing of `engine/*.py` or `bidcheck-deploy/send.py`.
- No touching of `seed/acd_contacted.csv` (the suppression list is sacred).

---

## The money forecast — if the targeting plan lands

Rough math, 30-day horizon, optimistic-but-grounded:

| Campaign | Clean leads / day | Reply rate | Replies / day | Convert-to-paid | Revenue / month |
|---|---|---|---|---|---|
| TenderWin | 150 | 3% | 4.5 | 15% to A$99 Pro | ~A$2,000 |
| BidCheck | 80 | 1.5% | 1.2 | 20% to R299 Starter | ~R2,000 |
| NameMarshal | 100 | 2% | 2 | 10% to Doola $500 LLC (we get 30%) | ~$900 |
| ACD | 50 | 4% | 2 | 10% hired a client, avg 10% of A$1,500 first month | ~A$750 |

**Total ballpark:** US$3,000–5,000/month blended, from here. Scaling assumption: double every 30 days for 3 months as targeting refines, then plateau when the TAM in each niche caps out.

The plan is not "send more". It's "send to the right people, convert the real leads, stop wasting sends on noise." The scraping agent's job is making the pool match this doc.

---

*Last updated 2026-11-04 by the copy-optimization session.*
*Related docs: `reports/cold-email-pack-2026-10-31/COLD-EMAIL-PACK.md` (templates), `project_outreach_engine` memory (operations), `project_tenderwin_posthog` memory (analytics).*
