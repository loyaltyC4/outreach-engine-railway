"""TenderWin (AU): government-work outreach. Everything campaign-specific lives here: who qualifies, how new
leads are found, and the email copy. Step 1 only: plain text, one recipient-specific hook, one ask (the legacy
follow-ups were never enabled)."""
import csv, hashlib, html, json, os, re, time, datetime as dt, urllib.request
from util import EMAIL_RX, reg_domain, has_mx, jev

NAME = "tenderwin"
REPLY_HINTS = ("tender", "bid", "government", "send them", "yes")
SEED_DIR = os.environ.get("SEED_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")
SEED_JSON = os.path.join(SEED_DIR, "tenderwin_leads.json")
# Shared exclusion list: every address the legacy ACD and TenderWin senders already touched.
SEED_CONTACTED = os.path.join(SEED_DIR, "acd_contacted.csv")
TW_SITE = "https://tenderwin.com.au"
UTM = "utm_source=cold_email&utm_medium=email&utm_campaign=tw_engine"

TRADE_RX = {"cleaning": r"clean|janitor|hygiene|laundry",
            "construction": r"construct|build|civil|refurb|maintenance|repair|electrical|plumb|roof|paint|fenc|landscap",
            "ICT": r"software|\bict\b|cyber|cloud|digital|licen[cs]e|it support|network|web|telecom",
            "security": r"(?<!cyber )security|guard|surveillance|patrol",
            "catering": r"cater|food|meal|kitchen",
            "professional services": r"consult|advis|review|audit|training|research|legal|recruit|project manage|evaluation",
            "supplies": r"suppl|equipment|vehicle|furniture|uniform|stationery|print|medical|goods|purchase",
            "electrical": r"electric|lighting|switchboard|solar|test and tag",
            "plumbing": r"plumb|hydraulic|drain|sewer|water main",
            "landscaping": r"landscap|grounds|mowing|tree|garden|vegetation|park",
            "facilities": r"facilit|maintenance|repair|property services",
            "pest control": r"pest|termite|vermin", "HVAC": r"hvac|air.?condition|mechanical services|ventilat|refrigerat",
            "painting": r"paint|coating|graffiti", "waste": r"waste|recycl|rubbish|bin|collection",
            "traffic management": r"traffic|road ?works|signage"}
TRADES = list(TRADE_RX)
STATES = ["NSW", "VIC", "QLD", "WA", "SA", "ACT", "TAS", "NT"]
_TENDERS = {"rows": None}


def _all_tenders():
    if _TENDERS["rows"] is None:
        try:
            req = urllib.request.Request(f"{TW_SITE}/api/tenders?limit=1000", headers={"User-Agent": "tenderwin-outreach/1.0"})
            _TENDERS["rows"] = json.load(urllib.request.urlopen(req, timeout=30)).get("tenders", [])
        except Exception:
            _TENDERS["rows"] = []
    return _TENDERS["rows"]


def live_for(trade, n=3, state=None):
    """(total open, [n soonest-closing, at least 4 days out]) for a trade bucket, the lead's own state first."""
    rx = re.compile(TRADE_RX.get(trade or "", r"$^"), re.I)
    cut = (dt.date.today() + dt.timedelta(days=4)).isoformat()
    rows = [r for r in _all_tenders() if (r.get("closes") or "") >= cut and rx.search(r.get("title") or "")]
    rows.sort(key=lambda r: (bool(state) and r.get("province") != state, r["closes"]))
    out = []
    for r in rows[:n]:
        d = dt.date.fromisoformat(r["closes"][:10]).strftime("%-d %b")
        out.append({"title": (r.get("title") or "")[:80].rstrip(" ,-"), "buyer": r.get("buyer", ""), "closes": d,
                    "state": r.get("province", ""), "url": f"{TW_SITE}/tender/{r['ocid']}?{UTM}"})
    return len(rows), out


def variant_for(lead):
    """Stable arm per address: the same lead always gets the same copy."""
    return "ABC"[int(hashlib.sha1((lead.get("email") or "").lower().encode()).hexdigest()[:8], 16) % 3]


def _first(lead):
    n = html.unescape(lead.get("contact_name") or "").split()
    return n[0].capitalize() if n else ((lead.get("company") or "").strip() + " team" if lead.get("company") else "there")


OPT = 'P.S. Not relevant? Reply "remove" and you will not hear from me again.'
SIGN = "The TenderWin team\ntenderwin.com.au"


def _award_line(lead):
    b, m = lead.get("award_buyer"), lead.get("award_month")
    co = lead.get("company") or "your business"
    if b and m:
        return f"Saw {co} won work from {b} ({m}) on AusTender. Nice."
    return f"Came across {co} while looking at who wins {lead.get('trade') or 'government'} work in Australia."


def render(lead):
    f, trade, co = _first(lead), lead.get("trade") or "your trade", lead.get("company") or "your business"
    total, tenders = live_for(lead.get("trade"), 3, lead.get("state"))
    v = variant_for(lead)
    if v == "C" and total:
        body = (f"{_award_line(lead)}\n\n{total} {trade} tenders are open across Australia right now. "
                f"I can send you the three that fit {co} before the day is out. Want them?\n\nJust reply \"yes\".")
        return f"{co}: next contract", f"Hi {f},\n\n{body}\n\n{OPT}\n\n{SIGN}"
    if v == "B" or not tenders:
        n = f"{total} {trade} tenders are open" if total else f"{trade} tenders open every week"
        body = (f"{_award_line(lead)}\n\nQuick question: who on your team watches for the next one?\n\n"
                f"Right now {n} across AusTender and the state portals. TenderWin emails the ones that fit your ABN "
                f"each morning, free.\n\nWant me to switch it on for {co}? Reply \"yes\" and I'll set it up.")
        return f"{co} + government work", f"Hi {f},\n\n{body}\n\n{OPT}\n\n{SIGN}"
    lines = "\n".join(f"- {x['title'][:70]} ({x['buyer'].split(' - ')[0][:35]}{', ' + x['state'] if x['state'] else ''}), closes {x['closes']}\n  {x['url']}" for x in tenders)
    body = (f"{_award_line(lead)}\n\n{total} {trade} tenders are open right now. These close soonest:\n\n{lines}\n\n"
            f"Want me to check these three against {co}{chr(39) if co.endswith('s') else chr(39) + 's'} ABN, GST and insurance? Reply \"yes\".")
    return f"{trade} tenders closing soon", f"Hi {f},\n\n{body}\n\n{OPT}\n\n{SIGN}"


# ---- qualification ----
JEV_Q = {
    "bids_gov": {"type": "noul", "instructions": "This is an Australian business in a trade that bids on or wins public government contracts (cleaning, construction, electrical, ICT, security, facilities, professional services or supplies). Score LOW for consumer retail, hospitality venues, government bodies, schools, councils and large listed companies."},
    "owner_reads": {"type": "noul", "instructions": "This email address likely reaches the owner, manager or tender/bids person of a small or mid-sized business."},
}
MIN_BIDS, MIN_READS = 0.6, 0.5


def prefilter(lead):
    return has_mx(lead["email"].split("@")[1])


def score(lead):
    st = (f"Australian business: company='{lead.get('company')}', trade='{lead.get('trade','')}', state='{lead.get('state','')}', "
          f"email='{lead['email']}', award_buyer='{lead.get('award_buyer','')}', source='{lead.get('source','')}'.")
    s = jev(st, JEV_Q)
    if not s:
        return None
    s["score"] = round(s["bids_gov"] * s["owner_reads"], 3)
    s["ok"] = s["bids_gov"] >= MIN_BIDS and s["owner_reads"] >= MIN_READS
    return s


def seed_rows():
    try:
        rows = json.load(open(SEED_JSON))
    except Exception:
        return []
    return [{**r, "email": re.sub(r"^(?:%[0-9a-fA-F]{2})+", "", r["email"]).strip().lower(), "source": r.get("source", "seed")}
            for r in rows if "@" in (r.get("email") or "")]


def seed_contacted():
    try:
        return {r["email"].strip().lower() for r in csv.DictReader(open(SEED_CONTACTED))}
    except Exception:
        return set()


# ---- automatic lead harvesting (Firecrawl search): AU businesses that win or bid on government work ----
TRADE_LABELS = {"cleaning": "cleaning services", "construction": "building contractor", "ICT": "IT services",
                 "security": "security services", "catering": "catering services", "professional services": "management consultancy",
                 "supplies": "office supplies", "electrical": "electrical contractor", "plumbing": "plumbing services",
                 "landscaping": "landscaping", "facilities": "facilities maintenance", "pest control": "pest control",
                 "HVAC": "air conditioning", "painting": "painting services", "waste": "waste management",
                 "traffic management": "traffic control"}

def harvest_queries():
    # 2026-10-29: old "won government tender contract ... contact email" template yielded 0 leads across
    # 573 credits. These patterns were live-tested: 59/68 queries produced usable on-domain contact addresses.
    qs = [(f"{TRADE_LABELS.get(t, t)} \"{s}\" Australia contact email enquiry", t, s)
          for t in TRADES for s in STATES]
    qs += [("australian security association member directory contact", "security", ""),
           ("master cleaners association members contact email", "cleaning", ""),
           ("electrical contractors association NSW members contact", "electrical", "NSW"),
           ("plumbing association Australia members directory email", "plumbing", "")]
    return qs


def leads_from_results(results, trade, state):
    out = []
    for r in results or []:
        url = r.get("url") or ""
        host = re.sub(r"^https?://", "", url).split("/")[0]
        dom = reg_domain(host)
        if not dom.endswith(".au") and not dom.endswith((".com", ".org", ".net")):
            continue
        md = r.get("markdown") or ""
        own = sorted({e.lower().strip(".") for e in EMAIL_RX.findall(md) if reg_domain(e.split("@")[1]) == dom})
        if not own:
            continue
        title = (r.get("title") or (r.get("metadata") or {}).get("title") or dom.split(".")[0]).strip()
        company = re.sub(r"\s*[|\-:–—].*$", "", title).strip()[:60] or dom
        out.append({"email": own[0], "company": company, "contact_name": "", "trade": trade, "state": state,
                    "source": "firecrawl:" + dom})
    return out
