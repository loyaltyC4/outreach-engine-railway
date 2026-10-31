# BidCheck mailbox capacity, 29 October 2026

Source: live AgentMail API (organisation and inbox endpoints, plus each inbox's sent messages), run from the 34 AgentMail keys that `bidcheck-sender` loads. Age is taken from each mailbox's first sent message. Per-mailbox rows are in `bidcheck-mailbox-capacity-2026-10-29.csv` in this folder.

## Bottom line

- **Real maximum today: 1,913 sends a day** across 84 mailboxes in 32 organisations, once every mailbox is at its age tier and no organisation is above its daily limit.
- **Sent so far today per AgentMail: 15.** The sender's own log reports 71. The two numbers don't match yet (see open items).
- The per-mailbox ceiling is 73 mailboxes at 25/day (mature), 11 at 8/day (under a week old). The mailbox age, not the 2,200 `DAILY_MAX` setting, is the binding limit.
- **6 organisations are unverified** and capped at 10 sends a day for the whole organisation, not per mailbox. Their mailboxes add 10 a day in total until the organisations are verified.

## Rules that set capacity

| Rule | Limit | Where it comes from |
|---|---|---|
| Per-mailbox age tier | 8/day under 7 days, 15/day for 7 to 13 days, 25/day from 14 days | `daily_cap()` in `send.py`, age from first send |
| Per-organisation daily limit | 100/day (verified or free plan); 10/day (unverified) | AgentMail `daily_send_limit`; AgentMail docs say unverified agents get 10 sends a day |
| Sender's own organisation cap | 99/day | `ORG_DAILY_CAP` in `send.py` |
| New-recipient limits | first hour, day and week limits per organisation | AgentMail `first_*_recipient_limit`; apply after verification |
| Pacing | 48 to 80 seconds between sends | `send.py` |
| Cold-send cutoff | runs starting at or after 14:00 UTC send replies only | `SEND_UNTIL_UTC_HOUR` |

A mailbox's real maximum is the smaller of its age tier and its share of the organisation limit. An organisation's real maximum is the smaller of its daily limit and the sum of its mailboxes' tiers.

## Per organisation

| Key | Organisation | Daily limit | Mailboxes | Tier sum | Real max/day | Sent today | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Bidcheck organization | 100 | 3 | 75 | 75 | 2 |  |
| 2 | Bidcheck | 100 | 3 | 75 | 75 | 3 |  |
| 3 | Bidcheck Org | 100 | 3 | 75 | 75 | 2 |  |
| 4 | Bidcheck Pty | 100 | 3 | 75 | 75 | 3 |  |
| 5 | None | 100 | 3 | 75 | 75 | 3 |  |
| 6 | None | 100 | 3 | 75 | 75 | 2 |  |
| 7 | None | 100 | 3 | 75 | 75 | 0 |  |
| 8 | None | 100 | 3 | 75 | 75 | 0 |  |
| 9 | None | 100 | 3 | 75 | 75 | 0 |  |
| 10 | None | 100 | 3 | 75 | 75 | 0 |  |
| 11 | None | 100 | 3 | 75 | 75 | 0 |  |
| 12 | None | 100 | 3 | 75 | 75 | 0 |  |
| 13 | None | 100 | 3 | 75 | 75 | 0 |  |
| 14 | None | 100 | 3 | 75 | 75 | 0 |  |
| 15 | None | 100 | 3 | 75 | 75 | 0 |  |
| 18 | David’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 19 | Gareth’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 20 | Kagiso’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 21 | Lizele’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 22 | Nadia’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 23 | None | 10 | 1 | 8 | 8 | 0 | unverified: 10/day total |
| 24 | None | 10 | 1 | 8 | 8 | 0 | unverified: 10/day total |
| 25 | None | 10 | 1 | 8 | 8 | 0 | unverified: 10/day total |
| 26 | None | 10 | 1 | 8 | 8 | 0 | unverified: 10/day total |
| 27 | None | 10 | 1 | 8 | 8 | 0 | unverified: 10/day total |
| 28 | None | 10 | 1 | 8 | 8 | 0 | unverified: 10/day total |
| 29 | Chikondi’s organization | 100 | 3 | 41 | 41 | 0 |  |
| 30 | Devan’s organization | 100 | 3 | 24 | 24 | 0 |  |
| 31 | David’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 32 | Gareth’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 33 | Nadia’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 34 | Kagiso’s organization | 100 | 3 | 75 | 75 | 0 |  |
| 16, 17 | inbox-scoped keys | not measured | not measured | not measured | not measured | not measured | the organisation endpoint returns 403 |

## Per mailbox

| Key | Mailbox | Created | First sent | Age (days) | Tier/day | Sent today | Organisation limit |
|---|---|---|---|---|---|---|---|
| 1 | david.bidcheck@agentmail.to | 2026-10-04 | 2026-10-07 | 22 | 25 | 1 | 100 |
| 1 | gareth.bidcheck@agentmail.to | 2026-10-04 | 2026-10-05 | 24 | 25 | 0 | 100 |
| 1 | nadia.bidcheck@agentmail.to | 2026-10-04 | 2026-10-07 | 22 | 25 | 1 | 100 |
| 2 | devan.bidcheck@agentmail.to | 2026-10-04 | 2026-10-06 | 23 | 25 | 1 | 100 |
| 2 | grant.bidcheck@agentmail.to | 2026-10-04 | 2026-10-06 | 23 | 25 | 1 | 100 |
| 2 | jason.bidcheck@agentmail.to | 2026-10-04 | 2026-10-05 | 24 | 25 | 1 | 100 |
| 3 | kyle.bidcheck@agentmail.to | 2026-10-04 | 2026-10-05 | 24 | 25 | 1 | 100 |
| 3 | luka.bidcheck@agentmail.to | 2026-10-04 | 2026-10-07 | 22 | 25 | 0 | 100 |
| 3 | trybidcheck@agentmail.to | 2026-10-03 | 2026-10-07 | 22 | 25 | 1 | 100 |
| 4 | brad.bidcheck@agentmail.to | 2026-10-04 | 2026-10-05 | 24 | 25 | 1 | 100 |
| 4 | gobidcheck@agentmail.to | 2026-10-03 | 2026-10-07 | 22 | 25 | 1 | 100 |
| 4 | liam.bidcheck@agentmail.to | 2026-10-04 | 2026-10-05 | 24 | 25 | 1 | 100 |
| 5 | unathi.bidcheck31@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 1 | 100 |
| 5 | vusi.bidcheck31@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 1 | 100 |
| 5 | willem.bidcheck31@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 1 | 100 |
| 6 | ayanda.bidcheck33@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 1 | 100 |
| 6 | brian.bidcheck33@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 6 | karabo.bidcheck33@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 1 | 100 |
| 7 | neo.bidcheck34@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 7 | palesa.bidcheck34@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 7 | tumi.bidcheck34@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 8 | refiloe.bidcheck35@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 8 | sello.bidcheck35@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 8 | zane.bidcheck35@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 9 | fatima.bidcheck36@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 9 | james.bidcheck36@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 9 | pieter.bidcheck36@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 10 | amogelang.bidcheck37@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 10 | andile.bidcheck37@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 10 | nolwazi.bidcheck37@agentmail.to | 2026-10-06 | 2026-10-08 | 21 | 25 | 0 | 100 |
| 11 | siya.bidcheck40@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 11 | thandi.bidcheck40@agentmail.to | 2026-10-06 | 2026-10-08 | 21 | 25 | 0 | 100 |
| 11 | vusi.bidcheck40@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 12 | rudo.bidcheck5426@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 12 | siya.bidcheck54x029@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 12 | thandi.bidcheck54x188@agentmail.to | 2026-10-06 | 2026-10-14 | 15 | 25 | 0 | 100 |
| 13 | amina.bidcheck57x132@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 13 | franco.bidcheck57x094@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 13 | jade.bidcheck5722@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 14 | palesa2.bidcheck2155@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 14 | thando.bidcheck9153@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 14 | zane2.bidcheck3523@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 15 | lerato2.bidcheck8375@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 15 | palesa2.bidcheck7053@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 15 | zane2.bidcheck5841@agentmail.to | 2026-10-06 | 2026-10-08 | 21 | 25 | 0 | 100 |
| 18 | lerato.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 18 | sipho.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 18 | thabo.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 19 | bongani.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 19 | nomvula.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 19 | sibusiso.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 20 | mandla.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 20 | themba.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 20 | zanele.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 21 | jabulani.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 21 | nokuthula.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 21 | philani.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 22 | lindiwe.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 22 | simphiwe.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 22 | tebogo.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 23 | lwandle.bidcheck5017@agentmail.to | 2026-10-06 | none yet | - | 8 | 0 | 10 |
| 24 | hope.bidcheck5134@agentmail.to | 2026-10-06 | none yet | - | 8 | 0 | 10 |
| 25 | amina.bidcheck5362@agentmail.to | 2026-10-06 | none yet | - | 8 | 0 | 10 |
| 26 | vusi.bidcheck5523@agentmail.to | 2026-10-06 | none yet | - | 8 | 0 | 10 |
| 27 | mina.bidcheck5613@agentmail.to | 2026-10-06 | none yet | - | 8 | 0 | 10 |
| 28 | nomsa.bidcheck1187@agentmail.to | 2026-10-06 | none yet | - | 8 | 0 | 10 |
| 29 | bidcheck@agentmail.to | 2026-10-02 | 2026-10-03 | 26 | 25 | 0 | 100 |
| 29 | mia.hartley@agentmail.to | 2026-10-23 | 2026-10-23 | 6 | 8 | 0 | 100 |
| 29 | ollie.marsh@agentmail.to | 2026-10-23 | 2026-10-25 | 4 | 8 | 0 | 100 |
| 30 | helplessfarmer615@agentmail.to | 2026-10-26 | none yet | - | 8 | 0 | 100 |
| 30 | selfishaspect334@agentmail.to | 2026-10-26 | 2026-10-26 | 3 | 8 | 0 | 100 |
| 30 | tumelomahlangu.bidcheck@agentmail.to | 2026-10-06 | none yet | - | 8 | 0 | 100 |
| 31 | lerato.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 31 | sipho.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 31 | thabo.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 32 | bongani.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 32 | nomvula.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 32 | sibusiso.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 33 | lindiwe.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 33 | simphiwe.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 33 | tebogo.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 34 | mandla.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 34 | themba.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |
| 34 | zanele.bidcheck@agentmail.to | 2026-10-06 | 2026-10-06 | 23 | 25 | 0 | 100 |

## Open items

1. **The sender's age data may differ from AgentMail's.** The local copy of the sender's state file records 68 mailboxes with first send on 22 October. AgentMail shows 58 of them first sent on 6 October. The sender uses its own state to set caps, so if that state holds 22 October, those mailboxes are at 15/day, not 25. I can't read the Railway volume from here to confirm.
2. **Sends today don't reconcile.** AgentMail shows 15 sent today across these mailboxes. The sender's log shows 71. I haven't found the cause.
3. **`status_until` is set on 80 of 86 mailboxes**, with dates from 27 to 28 November. The AgentMail docs I found don't define this field, so I can't say what it does. It needs confirming with AgentMail before we rely on the capacity figures.
4. **Keys 16 and 17 are inbox-scoped**, so their organisation limits and mailboxes weren't measured.
5. **Google Workspace mailboxes (7)** aren't in this model. The sender shows 0 Workspace sends allocated today.
6. **Six unverified organisations** (keys 23 to 28) are each capped at 10 a day. Verifying them would lift each to the 100 a day that the others have.

## Sources

- AgentMail rate limits: https://docs.agentmail.to/knowledge-base/rate-limits
- AgentMail agent sign-up limits: https://www.agentmail.to/docs/knowledge-base/agent-sign-up-limits
- Sender logic: `bidcheck-deploy/send.py` (`daily_cap`, `ORG_DAILY_CAP`, `SEND_UNTIL_UTC_HOUR`)
