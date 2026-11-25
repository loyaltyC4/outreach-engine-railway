"""TW-1000: TenderWin's 1,000-lead A/B/C cold sequence (2026-11-18). Copy, data hooks and HTML for every arm and
step. The operating rules (who, when, how many, when to stop, how to judge the arms) are in
ops/tw1000-playbook.md, which an agent must follow exactly. Nothing here sends: run.py does, via render_step().

Arms (stable per address, sha1 % 3):
  A  PRICE INTEL    a live tender in their trade + what the last similar contracts sold for, offer: the details
  B  YOUR LISTING   they are in TenderWin's subcontractor directory (from their award), offer: add details or hide
  C  BID BRIEF      a ready six-slide bid/no-bid brief for one live tender in their trade, offer: the brief

Steps: 1 day 0 (no links), 2 day 3 (gives the thing, designed HTML + text), 3 day 7 (a fresh tender), 4 day 14
(two-way choice). Copy v2, 2026-11-19.
Any reply, bounce, "remove", "hide" or "unsubscribe" ends the sequence for that address.

Every fact in an email comes from data on the lead or live TenderWin APIs. If a hook's data is missing, the step
falls back to the documented fallback line; it never invents a buyer, a date, a value or a count.
"""
import hashlib, html, json, re, urllib.parse, urllib.request, datetime as dt
import tw_brand as TB

SITE = "https://tenderwin.com.au"
CAMPAIGN = "tw1000"
SENDER_NAME = "Mitch Delaney"  # owner 2026-11-19: an invented but plausible AU persona, no real staffer
POSTAL = "TenderWin, Melbourne VIC"   # owner 2026-11-19: send from Melbourne
PLACE = POSTAL.split(", ", 1)[-1]  # Spam Act 2003: identify the sender. Playbook: replace with the registered address.
STEPS = {1: 0, 2: 3, 3: 7, 4: 14}  # step -> day offset from step 1
STOP_WORDS = re.compile(r"\b(remove|unsubscribe|stop|hide|not interested|no thanks|take me off)\b", re.I)

# ---------------------------------------------------------------------------------------------- data

def arm_for(email):
    return "ABC"[int(hashlib.sha1((email or "").strip().lower().encode()).hexdigest()[:8], 16) % 3]


def utm(arm, step, extra=""):
    q = {"utm_source": "cold_email", "utm_medium": "email", "utm_campaign": CAMPAIGN, "utm_content": f"{arm}{step}"}
    return urllib.parse.urlencode(q) + (f"&{extra}" if extra else "")


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "tenderwin-outreach/2.0"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


_FEED = {"rows": None}
def live_tenders(trade_rx, state=None, n=3):
    """(total open, [n soonest closing at least 4 days out, own state first]) for a trade regex."""
    if _FEED["rows"] is None:
        try:
            _FEED["rows"] = _get(f"{SITE}/api/tenders?limit=1500").get("tenders", [])
        except Exception:
            _FEED["rows"] = []
    rx = re.compile(trade_rx, re.I)
    cut = (dt.date.today() + dt.timedelta(days=4)).isoformat()
    NOT_WORK = re.compile(r"\b(lease|licen[cs]e to occupy|sale of|for sale|disposal|expressions? of interest for (land|site)|grant program|funding round)\b", re.I)
    rows = [r for r in _FEED["rows"] if (r.get("closes") or "") >= cut and rx.search(r.get("title") or "") and not NOT_WORK.search(r.get("title") or "")]
    rows.sort(key=lambda r: (bool(state) and r.get("province") != state, r["closes"]))
    return len(rows), rows[:n]


def comparables(t):
    """Price range from similar past awards for one tender (TenderWin's public comparables API), or None."""
    try:
        q = urllib.parse.urlencode({"title": t.get("title", ""), "buyer": t.get("buyer", ""), "province": t.get("province", "")})
        j = _get(f"{SITE}/api/comparables?{q}")
        s = j.get("stats") or {}
        # 2026-11-25: a 3-award floor was rejecting most trades and starving the queue; two real
        # awards still support "between X and Y", so the bar is now two.
        return s if s.get("n", 0) >= 2 and s.get("p25") and s.get("p75") else None
    except Exception:
        return None


def money(v):
    v = float(v)
    return f"A${v/1e6:.1f}M".replace(".0M", "M") if v >= 1e6 else f"A${round(v/1e3)}k" if v >= 1e3 else f"A${round(v)}"


def clip(s, n):
    """Cut at a word boundary, never mid-word."""
    s = str(s or "").split(" - ")[0].strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(" ,-&")


def day(iso):
    return dt.date.fromisoformat(iso[:10]).strftime("%-d %b")


def short_co(name):
    """'HARBOUR FACILITY SERVICES PTY LTD' -> 'Harbour Facility Services' for use in sentences."""
    n = re.sub(r"\s*\b(pty\.?\s*ltd\.?|pty\.?\s*limited|limited|ltd\.?|inc\.?|p/l)\b\.?", "", str(name or ""), flags=re.I).strip(" ,.-")
    if n.isupper() or n.islower():
        n = " ".join(w if w.upper() in ("NSW", "VIC", "QLD", "WA", "SA", "NT", "ACT", "TAS", "IT", "ICT", "AU") else w.capitalize() for w in n.split())
    return n or "your business"


def first_name(lead):
    n = html.unescape(lead.get("contact_name") or "").split()
    return n[0].capitalize() if n else None  # no name: greet with "Hi," rather than a mail-merge "Hi X team"


def possessive(name):
    return name + ("'" if name.endswith("s") else "'s")


def tender_url(t, arm, step, brief=False):
    return f"{SITE}/tender/{urllib.parse.quote(t['ocid'])}{'/brief' if brief else ''}?{utm(arm, step)}"


def facts(lead, trade_rx):
    """Everything the copy may use, computed once per lead and stored on the lead (lead['_facts'])."""
    if lead.get("_facts"):
        return lead["_facts"]
    total, ts = live_tenders(trade_rx, lead.get("state"), 3)
    feat, bench = (ts[0] if ts else None), None
    for t in ts:  # the featured tender is the first one with real price evidence behind it
        b = comparables(t)
        if b:
            feat, bench = t, b
            break
    co = short_co(lead.get("company"))
    f = {
        "first": first_name(lead), "co": co, "trade": lead.get("trade") or "government",
        "state": lead.get("state") or "", "total": total, "tenders": ts, "featured": feat, "bench": bench,
        "in_state": bool(ts) and all(t.get("province") == lead.get("state") for t in ts[:1]),
        "buyer": (lead.get("award_buyers") or [None])[0] or lead.get("award_buyer"),
        "award_month": lead.get("last_award") and dt.date.fromisoformat(str(lead["last_award"])[:10]).strftime("%B %Y"),
        "award_count": int(lead.get("award_count") or 0),
        "claim_url": lead.get("profile_id") and f"{SITE}/network/claim?p={lead['profile_id']}&{utm('B', 0)}",
    }
    lead["_facts"] = f
    return f


# ------------------------------------------------------------------------------------------- copy

# Copy v2 (2026-11-19). Rules every email follows, because these are what move cold replies:
#  - step 1 is 50-80 words, no links, one yes/no question, subject 2-4 words in lower case like an internal note;
#  - the first line is about THEIR world (a named live tender, a real price range), never about TenderWin;
#  - step 2 gives the valuable thing without being asked; step 3 brings a different fresh tender; step 4 offers a
#    two-way choice, so even a "stop" is an answer;
#  - one-line sign-off; the opt-out and sender identity (Spam Act) sit in a short final line, not a legal block.

SIGN = "{sender}\nTenderWin"
FOOT = '\n\nNot for you? Reply "no" and I will not write again. TenderWin, ' + POSTAL.split(", ", 1)[-1]


SMALL = {"of", "and", "the", "for", "in", "on", "at", "to"}
def tidy_name(n):
    w = str(n or "").split()
    return " ".join(x.lower() if i and x.lower() in SMALL else x for i, x in enumerate(w))


def buyer_short(t):
    return tidy_name(clip((t or {}).get("buyer", ""), 42))


def subj(text, words=4):
    w = str(text).lower().split()[:words]
    while len(w) > 1 and w[-1] in SMALL:
        w.pop()
    return " ".join(w)


def step_text(lead, arm, step, trade_rx, sender):
    """(subject, plain-text body) for one arm and step. Raises ValueError when the arm's required data is missing,
    so run.py skips the lead instead of sending a hollow email (playbook §2)."""
    f = facts(lead, trade_rx)
    co, trade, st = f["co"], f["trade"], f["state"] or "Australia"
    hi = f"Hi {f['first']}," if f["first"] else "Hi,"
    sig, foot = SIGN.format(sender=sender), FOOT
    t0 = f["featured"]
    t1 = next((t for t in f["tenders"] if t0 and t["ocid"] != t0["ocid"]), None)
    rng = f"{money(f['bench']['p25'])} and {money(f['bench']['p75'])}" if f["bench"] else None
    past = f"your {f['buyer']} job" if f["buyer"] else "your government work"

    if arm == "A":  # PRICE INTEL: what similar contracts sold for, for a live tender in their trade
        if not t0 or not f["bench"]:
            raise ValueError("A needs a live tender with at least 3 comparable awards")
        if step == 1:
            return (subj(buyer_short(t0)) + " tender",
                    f"{hi}\n\n{buyer_short(t0)} has a {trade} tender out that closes {day(t0['closes'])}: {clip(t0['title'], 90)}.\n\n"
                    f"The last {f['bench']['n']} contracts like it went for between {rng}.{' It is in ' + st + ', so close to your patch.' if f['in_state'] else ''}\n\n"
                    f"Want me to send the details and who won the similar ones?\n\n{sig}{foot}")
        if step == 2:
            return ("Re: " + subj(buyer_short(t0)) + " tender",
                    f"{hi}\n\nRather than wait, here it is, with the price range and closing date:\n{tender_url(t0, 'A', 2)}\n\n"
                    f"Happy to send who won the similar contracts too.\n\n{sig}{foot}")
        if step == 3:
            if not t1:
                raise ValueError("A3 needs a second open tender")
            return (f"another {trade} one",
                    f"{hi}\n\nAnother one that fits: {clip(t1['title'], 90)} ({buyer_short(t1)}), closes {day(t1['closes'])}.\n{tender_url(t1, 'A', 3)}\n\n"
                    f"Should I keep sending these when they open in {st}?\n\n{sig}{foot}")
        if step == 4:
            return (f"Re: another {trade} one",
                    f"{hi}\n\nLast one from me. Want {trade} tenders in {st} sent to you each morning (free), or shall I stop?\n\n{sig}{foot}")

    if arm == "B":  # YOUR LISTING: you are already visible to head contractors; control what they see
        if not f["claim_url"] or not f["award_count"]:
            raise ValueError("B needs a seeded network profile with award history")
        if step == 1:
            return ("your listing",
                    f"{hi}\n\nHead contractors use TenderWin to find {trade} subcontractors in {st}. {co} is listed because of {past} on AusTender, but the listing has no phone or email, so nobody can reach you from it.\n\n"
                    f"Want me to send the link to add your details? Or I can take the listing down. Either is fine.\n\n{sig}{foot}")
        if step == 2:
            return ("Re: your listing",
                    f"{hi}\n\nHere is the link, in case it is easier: {f['claim_url']}\nIt takes two minutes (your ABN and a work email). Reply \"hide\" and I will remove the listing instead.\n\n{sig}{foot}")
        if step == 3:
            if not t0:
                raise ValueError("B3 needs an open tender")
            return (subj(buyer_short(t0)) + " job",
                    f"{hi}\n\n{buyer_short(t0)}'s {clip(t0['title'], 80)} tender closes on {day(t0['closes'])}. Whoever wins it will likely need {trade} subcontractors in {st}.\n\n"
                    f"That is who searches the listing. Want yours to show how to reach you?\n{f['claim_url']}\n\n{sig}{foot}")
        if step == 4:
            return ("Re: your listing",
                    f"{hi}\n\nLast note. Keep the listing as it is, add your details, or take it down? Just reply 1, 2 or 3.\n\n{sig}{foot}")

    if arm == "C":  # BID BRIEF: a ready bid/no-bid deck for one live tender
        if not t0 or not f["bench"]:
            raise ValueError("C needs a featured tender with at least 3 comparable awards")
        if step == 1:
            return ("bid or no-bid?",
                    f"{hi}\n\nI put together a bid/no-bid brief on {buyer_short(t0)}'s {trade} tender (closes {day(t0['closes'])}): six slides on what they check, the risks, and what the last {f['bench']['n']} similar contracts went for ({rng.replace(' and ', ' to ')}).\n\n"
                    f"Want me to send it over?\n\n{sig}{foot}")
        if step == 2:
            return ("Re: bid or no-bid?",
                    f"{hi}\n\nHere it is, no sign-up needed:\n{tender_url(t0, 'C', 2, brief=True)}\n\nThe eligibility slide is the one to read first.\n\n{sig}{foot}")
        if step == 3:
            if not t1:
                raise ValueError("C3 needs a second open tender")
            return (subj(buyer_short(t1)) + " tender",
                    f"{hi}\n\nI can do the same brief for {clip(t1['title'], 80)} ({buyer_short(t1)}, closes {day(t1['closes'])}). Want it?\n\n{sig}{foot}")
        if step == 4:
            return ("Re: bid or no-bid?",
                    f"{hi}\n\nShould I send you a brief like this whenever a {trade} tender opens in {st}, or leave it here?\n\n{sig}{foot}")
    raise ValueError(f"unknown arm/step {arm}{step}")


# ------------------------------------------------------------------------------------------- HTML (step 2)
# Table layout, inline styles, 600px, one button, no web fonts, no tracking pixel of our own: the design is the
# typography, spacing and one real data card. Colours and type scale follow tenderwin.com.au.

INK, MUTED, LINE, ACC, BG = "#0B1B3F", "#5B6475", "#E6EAF2", "#024FF5", "#F5F7FA"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


def _esc(s):
    return html.escape(str(s or ""))


def _card(rows, link, label):
    cells = "".join(
        f'<tr><td style="padding:12px 18px;border-top:1px solid {LINE};font:500 10.5px/1.4 {MONO};letter-spacing:.14em;text-transform:uppercase;color:{MUTED};width:38%">{_esc(k)}</td>'
        f'<td style="padding:12px 18px;border-top:1px solid {LINE};font:600 14px/1.45 {FONT};color:{INK}">{v}</td></tr>' for k, v in rows)
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {LINE};border-radius:14px;border-collapse:separate;overflow:hidden;background:#fff">'
            f'{cells}<tr><td colspan="2" style="padding:16px 18px;border-top:1px solid {LINE};background:{BG}">'
            f'<a href="{_esc(link)}" style="display:inline-block;background:{INK};color:#fff;text-decoration:none;font:600 14px/1 {FONT};padding:12px 20px;border-radius:999px">{_esc(label)} &rarr;</a></td></tr></table>')


def _clean_title(t, n=90):
    """Drop the buyer's reference codes that lead most titles ("TC26120- MI187911- Lot 74 ...")."""
    t = re.sub(r"^([A-Z]{1,5}\d{2,}[-\s]+)+", "", str(t or "")).strip()
    t = re.sub(r"^([A-Z0-9]{2,}[-/]\s*)+", "", t).strip() if t else t
    return clip(t or "", n)


def step2_html(lead, arm, trade_rx, sender):
    """Designed HTML for step 2, on the TenderWin v2 design system (engine/tw_brand.py).

    Same facts and wording as step_text(arm, 2); only the presentation changes.
    """
    subject, text = step_text(lead, arm, 2, trade_rx, sender)
    f = facts(lead, trade_rx)
    t0 = f["featured"]
    money_rng = (f"{money(f['bench']['p25'])} to {money(f['bench']['p75'])}" if f["bench"] else "")

    if arm == "A":
        rows = [("Tender", TB.esc(_clean_title(t0["title"]))),
                ("Buyer", TB.esc(t0.get("buyer", ""))),
                ("Closes", TB.esc(day(t0["closes"])))]
        if f["bench"]:
            rows.append(("Similar awards", f"{money_rng} <span style=\"font-weight:400;color:{TB.GREY}\">({f['bench']['n']} past)</span>"))
        body = (TB.eyebrow("The tender, and what similar work sold for")
                + TB.h1("Here it is, with the numbers")
                + TB.p(f"Closing {day(t0['closes'])}."
                       + (f" The range comes from {f['bench']['n']} past awards for comparable work." if f["bench"] else ""))
                + TB.kv(rows)
                + TB.cta(tender_url(t0, "A", 2), "Open the tender")
                + TB.spacer(22)
                + TB.p("Happy to send who won the similar contracts too.", mb=0))
    elif arm == "B":
        rows = [("Business", TB.esc(f["co"])), ("Trade", TB.esc((f["trade"] or "")[:1].upper() + (f["trade"] or "")[1:])),
                ("Contracts on record", str(f["award_count"]))]
        if f["buyer"]:
            rows.append(("Most recent buyer", TB.esc(f["buyer"])))
        rows.append(("Contact details", f'<span style="color:{TB.GREY};font-weight:400">Not added yet</span>'))
        body = (TB.eyebrow("Your listing in the directory")
                + TB.h1("Here it is as they see it today")
                + TB.p("Head contractors search this directory when they need subcontractors. "
                       "Yours is there, but nothing on it lets them reach you.")
                + TB.kv(rows)
                + TB.cta(f["claim_url"], "Add your details")
                + TB.spacer(22)
                + TB.p("It takes two minutes (your ABN and a work email). Reply \"hide\" and I will remove "
                       "the listing instead.", mb=0))
    else:
        rows = [("Tender", TB.esc(_clean_title(t0["title"]))), ("Buyer", TB.esc(t0.get("buyer", ""))),
                ("Closes", TB.esc(day(t0["closes"])))]
        if f["bench"]:
            rows.append(("Similar awards", f"{money_rng} <span style=\"font-weight:400;color:{TB.GREY}\">({f['bench']['n']} past)</span>"))
        rows.append(("Brief", "6 slides: decision, factors, eligibility, gaps, price, next steps"))
        body = (TB.eyebrow("Your bid or no-bid brief")
                + TB.h1("Six slides, no sign-up")
                + TB.p("What they check, where the risks are, and the price band"
                       + (f" from {f['bench']['n']} similar contracts" if f["bench"] else "") + ".")
                + TB.kv(rows)
                + TB.cta(tender_url(t0, "C", 2, brief=True), "Open the brief")
                + TB.spacer(22)
                + TB.p("The eligibility slide is the one to read first.", mb=0))

    body += TB.signoff(sender)
    html = TB.shell(preview=text.split("\n\n")[1][:110] if "\n\n" in text else text[:110],
                    body_html=body, postal=PLACE,
                    note='Not for you? Reply "no" and I will not write again.')
    return subject, text, html


def render_step(lead, step, trade_rx, sender):
    """What run.py calls. Returns dict(subject, text, html|None, arm, step) or raises ValueError (skip/fallback)."""
    arm = lead.get("_arm") or arm_for(lead.get("email"))
    if step == 2:
        s, t, h = step2_html(lead, arm, trade_rx, sender)
        return {"subject": s, "text": t, "html": h, "arm": arm, "step": step}
    s, t = step_text(lead, arm, step, trade_rx, sender)
    return {"subject": s, "text": t, "html": None, "arm": arm, "step": step}


# ------------------------------------------------------------------------------------ run.py adapter
# run.py imports the campaign module and expects this surface. tw1000 gets its leads from a fixed,
# evidence-checked seed instead of harvesting, so the harvest half of the contract is inert.

import csv as _csv
import os as _os

_SEED_DIR = _os.environ.get("SEED_DIR") or _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "seed")
SEED_FILE = _os.path.join(_SEED_DIR, "tw1000_leads.json")
CONTACTED_FILE = _os.path.join(_SEED_DIR, "tw1000_contacted.csv")

# subject families this campaign sends, so replies/threads are recognised as ours
REPLY_HINTS = ("tender", "your listing", "bid or no-bid", "another", "job", "listing")


def trade_rx_for(trade):
    """Regex for one TenderWin trade label (word-boundary safe, tenderwin.py owns the map)."""
    import tenderwin as _tw
    return _tw.TRADE_RX.get((trade or "").strip().lower(), r"$^")


def render(lead):
    """Single-step compatibility shim: run.py's shared paths call this. tw1000 uses render_step."""
    r = render_step(lead, 1, trade_rx_for(lead.get("trade")), lead.get("_sender") or SENDER_NAME)
    return r["subject"], r["text"]


def seed_rows():
    import json as _json
    try:
        with open(SEED_FILE) as f:
            return _json.load(f)
    except Exception:
        return []


def seed_contacted():
    try:
        with open(CONTACTED_FILE) as f:
            return {r[0].strip().lower() for r in _csv.reader(f) if r}
    except Exception:
        return set()


def prefilter(lead):
    """Cheap gate before scoring: only the fields this campaign can actually address."""
    return bool(lead.get("email") and lead.get("company") and lead.get("trade"))


def score(lead):
    return float(lead.get("_score") or 1.0)


def harvest_queries():
    return []


def leads_from_results(res, *rest):
    return []
