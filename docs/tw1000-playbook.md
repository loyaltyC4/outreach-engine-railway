# TW-1000 playbook: TenderWin cold outreach, 1,000 leads, three arms, four steps

Written 2026-11-18. **The agent running this campaign follows this document exactly.** Where it says MUST, there is
no judgement call. Where something is not covered, stop and ask the owner; do not improvise copy, claims, volumes or
targets.

Copy, data hooks and HTML live in `engine/tw1000.py` (`render_step(lead, step, trade_rx, sender)`). This document is
the operating manual: who gets emailed, from where, when, how many, what counts as a result, and when to stop.

---

## 1. Goal and the one number that decides it

Find out which of three offers turns Australian SMEs that already win government work into TenderWin users, at a
volume (1,000 leads) that gives a usable answer, without damaging the sending domain.

**Primary metric: activated signups per 100 leads emailed**, by arm. A signup is "activated" when the account
completes onboarding (PostHog `onboarding_profile_saved`) within 14 days of that lead's step 1.

Secondary (in order): trial starts per 100, positive replies per 100, clicks per 100. Opens are NOT measured and MUST
NOT be used for any decision (Apple Mail Privacy Protection makes them meaningless).

---

## 2. The three arms

Arm is assigned by `arm_for(email)` (sha1 of the lowercased address, mod 3). It is stable: a lead never changes arm.
Never assign arms by hand and never rebalance.

| Arm | Name | The offer | Needs on the lead | If missing |
|---|---|---|---|---|
| A | Price intel | A live tender in their trade + what the last similar contracts sold for. "Want the details and who won the similar ones?" | an open tender in the trade with ≥ 3 comparable awards | skip lead (log `skip:A-no-evidence`) |
| B | Your listing | They are in TenderWin's subcontractor directory from their award, with no contact details. "Want the link to add your details, or shall I take it down?" | `profile_id` (vula_sub_profiles.id), award_count ≥ 1 | skip lead (log `skip:B-no-profile`) |
| C | Bid brief | A ready six-slide bid/no-bid brief for one live tender in their trade, with the price range of similar awards | an open tender in the trade with ≥ 3 comparable awards | skip lead (log `skip:C-no-evidence`) |

**Copy rules (v2, 2026-11-19), which the agent must not break:** step 1 is 50–80 words with no links and one yes/no
question; subjects are 2–4 lower-case words; the first line is about their world, not TenderWin; step 2 gives the
promised thing without waiting for a reply; step 3 brings a different, fresh tender; step 4 offers a choice.

Skipped leads are NOT moved to another arm (that would bias the test). They go back to the pool and are reported.

### Why these three
- A tests **price intelligence**: what similar contracts sold for is the number bidders cannot easily get.
- B tests **identity/ownership**: "you already have a listing; control it". It is also the only arm that grows the
  subcontractor network, so it has value even if it converts to paid less.
- C tests **a concrete free deliverable**: the six-slide brief, which is TenderWin's most visible paid output.

---

## 3. Sequence

| Step | Day | Format | Purpose |
|---|---|---|---|
| 1 | 0 | plain text, no links | the offer, ending in a yes/no question |
| 2 | 3 | designed HTML card + plain-text alternative, threaded (`Re:`) | gives the promised thing without waiting |
| 3 | 7 | plain text, new subject | a different, fresh tender (relevance again) |
| 4 | 14 | plain text, threaded | a two-way choice: keep sending, or stop |

Rules:
- A lead gets step N+1 only if, since step N: no reply of any kind, no bounce, no complaint, no click on a
  `/login` link that turned into a signup, and the step's day offset has passed.
- **Any reply stops the sequence for that address.** Positive replies go to §8. "remove", "unsubscribe", "stop",
  "hide", "not interested" (regex `STOP_WORDS` in tw1000.py) → suppress the address forever and, for "hide", set the
  lead's `vula_sub_profiles.status = 'hidden'` the same day.
- Steps whose subject starts with `Re:` MUST be sent in the same thread as the step they reply to (AgentMail
  reply-to that message id), from the same inbox. Step 3 starts a new thread on purpose.
- Step 2 sends `html` + `text` together (multipart). Never send HTML without the text part.

---

## 4. Who gets emailed (list build)

Source of truth: `vula_sub_profiles` in the TenderWin Supabase project `lwwahygviakbccwoqvfo` (9,519 seeded
businesses with an ABN from AusTender contract notices since 2023-01-01, award ≥ A$50,000).

### 4.1 Before building the list (MUST be done first)
1. **Map trades.** Many rows carry raw UNSPSC labels ("unspsc 81 engineering and"). Map them to TenderWin trades
   (`TRADE_RX` keys in tenderwin.py) and discard rows whose only labels cannot be mapped.
2. **Add state.** Rows have no `state` (the ABN Register lookup ran without a GUID). Fill `state` from the ABR (ask
   the owner to set `ABR_GUID` in your shell; never read it from Vercel) or, failing that, from the province of the
   lead's own award records in `vula_awards`. A lead with no state is excluded.
3. **Verify the ABN** on the ABR (active, entity name matches). Inactive or mismatched → excluded.

### 4.2 Who is in
All of:
- Trade maps to one of: cleaning, construction, security, facilities, electrical, plumbing, landscaping, ICT,
  professional services, catering, traffic management, waste, HVAC, painting, pest control.
- SME signals: `award_total` < A$20M and `award_count` between 1 and 25.
- Jev `bids_gov` ≥ 0.6 and `owner_reads` ≥ 0.5 (existing `JEV_Q` in tenderwin.py).

### 4.3 Who is out (MUST exclude)
- Listed companies (ASX), multinationals, universities, government bodies, councils, trustees, family trusts,
  hospitals, and any name with "Department", "Council", "University", "Trustee", "Pty Ltd as trustee".
- Defence primes and their subsidiaries (Hanwha, BAE, Thales, Lockheed, Raytheon, Boeing, Leidos, Babcock, Saab,
  Rheinmetall, Kongsberg, Naval Group, CEA, Nova Systems' parent, etc.). If unsure whether a business is a large
  company, exclude it.
- Anyone in `seed/acd_contacted.csv`, anyone in the engine's sent ground truth, any suppressed address or domain.

### 4.4 Finding the email (Spam Act 2003 — read this)
TenderWin may only email an address under **inferred consent**: the address is conspicuously published by the
business (its own website contact page, footer, or an industry directory listing it published), the message relates
to the recipient's business role, and the publication is not accompanied by a statement that the business does not
want unsolicited commercial email.

For each lead:
1. Find the business website: Firecrawl search `"<business name>" <state> <trade>`; accept a domain only when the
   page shows the same business name or ABN.
2. On that site, take the published address from the contact page or footer. Prefer a named person in a bid,
   tender, estimating, business development or owner role; otherwise `info@`/`admin@`/`enquiries@`.
3. **Record the evidence**: `consent_source_url` and `consent_seen_at` on the lead. No evidence → no email.
4. Reject: personal webmail (gmail/outlook/bigpond) unless it is the only published address on the business's own
   site; any page saying "no unsolicited" or similar; addresses found only in data brokers, LinkedIn scrapes or
   guessed patterns (`firstname@domain`). **Never guess an address.**
5. Check MX (`has_mx`). No MX → reject.

### 4.5 The 1,000
Take the first 1,000 qualified leads by Jev `score`, then check the arm split (`arm_for`): each arm MUST have
300–370 leads. If not, the hash is broken; stop and report.

Store as `seed/tw1000_leads.json` with fields: `email, company, contact_name, trade, state, profile_id, abn,
award_buyers, last_award, award_count, award_total, consent_source_url, consent_seen_at, arm`.

---

## 5. Sending

- Service: Railway project `outreach`, service `tenderwin-sender` (currently `DRY_RUN=1`). Campaign module: wire
  `CAMPAIGN=tw1000` to call `tw1000.render_step` (see §10).
- Inboxes: **every live AgentMail inbox** (owner decision 2026-11-19), currently 20 across 9 orgs, all with the
  display name `Mitch Delaney | TenderWin` so the fleet reads as one brand. The OTP sink is denied by regex.
- From name: **`Mitch Delaney`** (owner decision 2026-11-19: an invented but plausible Australian persona; nobody
  at TenderWin answers replies). Set via `SENDER_NAME`; signature carries it, footer identifies Melbourne VIC.
- Window: Tuesday to Thursday, 07:30–10:30 in the lead's own state time zone (QLD has no daylight saving). No sends
  Friday to Monday or on that state's public holidays.
- Volume ramp (step 1 sends per day, across all inboxes, follow-ups on top):

| Days | Step-1 per day | Per inbox per day (all steps) |
|---|---|---|
| 1–3 | 45 | ≤ 4 |
| 4–6 | 90 | ≤ 7 |
| 7 onward | 120 | ≤ 8 (`INBOX_DAILY_CAP=8`) |

  At 120 a day, all 1,000 step-1 sends finish in about 11 sending days; the whole sequence finishes about 14 days
  after the last step 1.
- Interleave arms inside every batch (sort the day's batch by `sha1(email)`), so no arm gets a better day or inbox.
- Every link carries `utm_source=cold_email&utm_medium=email&utm_campaign=tw1000&utm_content=<arm><step>`. Never
  strip or change UTMs.

---

## 6. Guards (automatic stops — MUST stay on)

| Signal | Threshold | Action |
|---|---|---|
| Hard bounces | > 3% of sends in any 48 h (min 40 sends) | pause all sending (existing `BOUNCE_PAUSE`), report, do not resume without the owner |
| Spam complaints | any single complaint | pause the inbox that sent it for 7 days; ≥ 2 in a week → pause the campaign |
| "remove"/negative replies | > 5% of step-1 sends for one arm | pause that arm's step 2–4, report |
| Inbox placement | seed-test shows Spam for > 1 of 4 providers | pause, report |
| Data error | any email rendered with a missing fact, wrong buyer, wrong date or a closed tender | pause, fix, report every affected address |

Before every daily batch: re-render 5 random queued emails and read them. If any fact is wrong, stop.

---

## 7. Measurement

Per arm, record per lead: step sends (timestamps, message ids), replies (classified), clicks (from UTM landing),
signup (PostHog `sign_up_client` with `utm_content` first-touch), activation (`onboarding_profile_saved`), trial
start (`trial_started`), paid (Stripe subscription on the account).

**Attribution:** a conversion counts for the arm if the account's first-touch `utm_campaign=tw1000` OR the account
email's domain equals the lead's email domain, within 14 days of the lead's step 1.

### Decision rule
After every lead has had 14 days since step 1 (about day 25 of the campaign):

1. For each pair of arms compute the two-proportion z-test on activated signups (pooled proportion,
   z = (p1 − p2) / sqrt(p(1−p)(1/n1 + 1/n2))).
2. **Winner** = the arm with the highest activation rate whose difference against each other arm has z ≥ 1.64
   (one-sided 95%). If there is a winner, the next 1,000 leads all go to the winner, with a new challenger arm
   written by the owner.
3. **No clear winner** (expected if all rates are below about 2% at n ≈ 333 per arm): keep all three for the next
   1,000 and pool the results. Do not declare a winner on positive replies alone unless activations total fewer
   than 10 across all arms; then use positive replies with the same test and say so in the report.
4. An arm with zero activations and positive-reply rate under 1% after 300 step-1 sends is stopped early.

Honest expectation for the report: cold email to this audience typically yields low single-digit positive reply
rates. At 333 leads per arm, only differences of roughly 3 to 4 percentage points are detectable. Report effect
sizes with 90% confidence intervals, not just "won/lost".

### Weekly report (every Friday, to the owner)
Per arm and step: sent, bounced, replied (positive / neutral / negative / remove), clicked, signed up, activated,
trial, paid; guards triggered; 5 example replies per arm (anonymised); list-build counts (found, rejected by reason).

---

## 8. Replies

Classify every reply within one business hour during AU business days:

| Class | Example | Action (same day) |
|---|---|---|
| Positive A | "yes", "check them" | Run the eligibility check on the three tenders for their ABN (TenderWin eligibility + ABR), reply with results + sign-in link. Use `templates/tw1000_replies.md` A-yes. |
| Positive B | "claimed", "how do I add contacts" | Reply with the claim link again + the two steps. |
| Positive C | "yes send it" | Reply with the brief link `/tender/<ocid>/brief` and one line on what to look at first. |
| Question | "how much", "who are you" | Answer plainly: Starter A$49/month after a 14-day free trial (check `lib/plans.js` for current prices before quoting); TenderWin is an Australian tender search and bid tool. |
| Not now / wrong person | | Thank them; if they name the right person and that person's address is published on the business website, you may email them once, as step 1 of the same arm, citing who referred you. |
| Remove / hide / angry | | Suppress immediately. "hide" also hides their directory listing. Reply once only if they asked a question; otherwise no reply. |

Never argue, never send a second pitch to a "no", never forward a lead to anyone outside TenderWin.

---

## 9. What the agent MUST NOT do

- Change any copy, subject, claim, price or offer in tw1000.py without the owner's written approval.
- Send without `consent_source_url` evidence, to a guessed address, or to anyone in §4.3.
- Exceed the ramp, inbox caps or send window, or send from inboxes outside TW1–TW5.
- Turn off the guards, resume after a guard pause, or clear bounce state without the owner.
- Mention competitors, invent urgency ("only 3 spots"), or claim results TenderWin has not measured.
- Use tracking pixels or link shorteners.
- Declare a winner before the §7 decision point.

---

## 10. Engineering checklist (do before step 1 goes out)

1. `engine/run.py`: add multi-step support for `CAMPAIGN=tw1000`:
   - per-lead state: `{arm, steps: {1: {ts, inbox, message_id}, ...}, stopped: reason|null}` in the data volume;
   - due-step selection: next step whose day offset has passed and lead not stopped;
   - threading: steps 3–4 reply to the step-1 message id (AgentMail reply endpoint);
   - send `html` + `text` when `render_step` returns html;
   - log every send to `state/tw1000_sends.jsonl` with arm, step, subject, message id.
2. Inbound: route replies through the existing classifier; add `STOP_WORDS` handling and the "hide" action
   (Supabase update of `vula_sub_profiles.status`).
3. `tenderwin.py` `TRADE_RX`: keep the 2026-11-18 word-boundary fix for security.
4. Dry run: render all 1,000 leads × 4 steps to `reports/tw1000_dryrun/` and have the owner read 30 random ones.
5. Seed test: send step 1 and step 2 of each arm to a Gmail, Outlook, Yahoo and iCloud test inbox; record placement.
6. Owner sign-off, then set `DRY_RUN=0`.

---

## 11. Files

- `engine/tw1000.py` — copy, facts, HTML, `render_step`.
- `docs/tw1000-playbook.md` — this document.
- `templates/tw1000_replies.md` — reply templates for §8 (to be written from the examples above and approved).
- Previews of every arm and step for a sample lead: `reports/tw1000_preview/` (generated by the dry run).
