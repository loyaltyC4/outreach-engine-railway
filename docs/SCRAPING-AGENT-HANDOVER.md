# Scraping agent handover — read this first

**From:** the copy/targeting session, 2026-11-04. **To:** the scraping agent.
**Your job:** find the right people to email, and only those. You do not send email. You do not change sending code.

---

## 1. Read these, in order

1. This file.
2. `SURGICAL-SCRAPE-SPEC.md` (same folder). It holds the hard rules, the per-campaign sources, the filters and the output schema. Every rule in it is a constraint.
3. `TARGETING-PLAN.md` (same folder). It ranks the priority order per campaign.

If anything is unclear, **skip the lead and log it**. A missing lead costs nothing. A wrong email costs deliverability for every campaign.

---

## 2. What you produce

One JSON file per campaign, written to `~/projects/outreach-engine/seed/` (exact names are in the spec):

| Campaign | Output file |
|---|---|
| TenderWin (AU) | `tw_award_winners.json`, then `tw_prequal.json`, `tw_supply_nation.json` |
| BidCheck (SA) | `bc_csd_winners.json`, then `bc_cidb.json` |
| NameMarshal (JP/AE) | `nm_amazon_jp.json`, then `nm_dubai_free_zone.json`, `nm_rakuten_base.json` |
| ACD (AU) | `acd_ndis_providers.json`, then `acd_hcp.json` |

Each row uses the schema in spec Rule 7: `email`, `domain`, `name`, `country`, `trade`, `state`, `trigger`, `signals`, `source_tag`, `scraped_at`. Leave `jev_score` and `jev_ok` null. The engine fills them.

**Priority order:** do the P1 source for each campaign first. Move to P2 only when P1 is done.

---

## 3. Gates (apply in this order, drop on the first failure)

1. **Role inbox:** local-part matches the reject regex in spec Rule 1. Drop.
2. **Government or education domain:** spec Rule 2. Drop.
3. **Trigger:** needs a dated trigger in the last 90 days (12 months for award and prequal). No trigger, drop and log to `candidates_no_trigger.jsonl`.
4. **Owner confidence:** `low` goes to `candidates_lowconfidence.jsonl` and never enters a seed.
5. **Country check (NameMarshal only):** two signals must agree (address and domain/WHOIS). Otherwise drop and log.
6. **Dedupe:** against `seed/acd_contacted.csv` and each campaign's existing seed. Never add a duplicate address, and never more than 2 addresses per domain.
7. **Jev:** score every survivor through the engine's `jev()` call. Jev must return `ok=true`. If Jev is down, queue in `pending_jev.jsonl`. Do not drop.

Logs for every drop go to `discards.jsonl` with a reason.

---

## 4. Limits

- Max **300 new leads per campaign per day** into a seed.
- Max **2 scrape jobs per source per day**. Don't hammer public registries.
- Honour `robots.txt` and any rate limit a site returns.

---

## 5. Keys (never print them, never commit them, never paste them into a file)

- Jev: environment variable `TYPESAFE_API_KEYS` (comma-separated pool). It lives in `~/AutoClaw/Shared/.secrets/keys.env`. Load it with `set -a; . ~/AutoClaw/Shared/.secrets/keys.env; set +a`. The engine's `jev()` in `engine/util.py` rotates through the pool.
- Firecrawl: `FIRECRAWL_KEYS` in the same file.
- TinyFish: the pool file is at `~/Downloads/TINYFISH_KEYS_POOL_NOV01.txt`. The owner should move it into `keys.env` as `TINYFISH_KEYS`. Until then, do not use TinyFish.
- Google service account: **do not use it.** The owner is rotating it.

If a key returns 401 or 403, stop using that key. Do not retry it in a loop.

---

## 6. Do NOT

- Send any email, or call any AgentMail endpoint for sending.
- Edit `engine/*.py`, `bidcheck-deploy/send.py`, or any copy file.
- Touch `seed/acd_contacted.csv`. It is the suppression list.
- Write any key value into a file, a log, a commit or a chat message.
- Scrape the government or enterprise lists in the exclusion sections of the spec.

---

## 7. Daily report

End each run with a short summary:

```
scraped:            {campaign: N}
passed_gates:       {campaign: N}
jev_ok:             {campaign: N}
discarded_by_reason: {role_inbox: N, no_trigger: N, country_mismatch: N, jev_fail: N, ...}
added_to_seed:      {campaign: N}
```

If any source returns errors on more than half its requests, stop that source and report it.

---

## 8. Open items for the owner (the agent cannot do these)

- Run the one Railway command that sets `TYPESAFE_API_KEYS` on the four services. It is in `SURGICAL-SCRAPE-SPEC.md`, under "Deploy checklist for Jev key-pool". Until that runs, the sending services only use the single legacy Jev key.
- Move the TinyFish keys into `keys.env`.
- Rotate the Google service-account key.
- Rotate the Jev keys. They were pasted into chat.

---

*Written 2026-11-04. Source of truth: `SURGICAL-SCRAPE-SPEC.md`. If this file and the spec disagree, the spec wins.*
