"""Aged Care Direct: partner-invitation campaign. Everything campaign-specific lives here:
who qualifies, how new leads are found, and the email copy (edit COPY when the wording changes).

Arms (2026-11-04): A = shortlist-no-forms (the live control, best reply-bait at ~0.9%).
                   B = capacity question first (lower-friction opener; lands as a yes/no).
                   C = fees-first (answers the real objection up-front; commission model).
                   D = 3-option reply (name three services and say "reply A/B/C"; speeds the sort).
Arm picked by stable sha1(email) % 100 against ACD_ARM_WEIGHTS (default A=40,B=20,C=30,D=10).
Owner confirmed commercial model 2026-11-04: commission (default 10% of first month, override in code)."""
import csv, hashlib, html, os, re
from util import FREE_MAIL, EMAIL_RX, reg_domain, has_mx, jev

NAME = "acd"
REPLY_HINTS = ("new client introductions", "equipment quotes", "same-day equipment",
               "services:", "areas covered:", "taking new clients", "what are the terms", "what are your terms",
               "any fees", "commission", "how does this work", "add us", "add me")
SEED_DIR = os.environ.get("SEED_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")
SEED_CSV = os.path.join(SEED_DIR, "acd_leads.csv")
SEED_CONTACTED = os.path.join(SEED_DIR, "acd_contacted.csv")
SENDER_NAME = "Sylvester"
BRAND = "Aged Care Direct"
FOOTER_ADDR = "Aged Care Direct, Melbourne VIC, Australia"
SITE = "https://agedcaredirect.com.au"

STATE_NAME = {"NSW": "NSW", "VIC": "Victoria", "QLD": "Queensland", "WA": "Western Australia", "SA": "South Australia",
              "TAS": "Tasmania", "ACT": "the ACT", "NT": "the Northern Territory"}

# ---- copy (v3, 2026-11-04: four arms with fees-answer A/B pass). Plain text, no forms, "Sylvester" sign-off stays.
# Owner-confirmed commercial model: commission. Default phrasing: "10% of the first month if we introduce a paying client."
# Override by editing FEES_LINE in one place.
FEES_LINE = ("No upfront cost. We only earn a small commission (10% of the first month) if we actually "
             "introduce someone who becomes a client, otherwise it's free.")

SUBJECTS = {
    "A": ["shortlist question for {name}", "quick one for {name}", "capacity check, {name}"],
    "B": ["room for new clients, {name}?", "quick yes/no for {name}", "{name} intake"],
    "C": ["about the commission, {name}", "how it works for {name}", "{name} shortlist + fees"],
    "D": ["which of these does {name} cover?", "three options, {name}", "shortlist tick, {name}"],
}
BODY = {
    "A": ("Hi,\n\n"
          "I'm Sylvester at Aged Care Direct. We introduce people who need aged care or disability support directly to providers, "
          "and I'm putting together the shortlist{where} now.\n\n"
          "If {name} has room for new clients, reply with what you cover (services + areas) and I'll add you. That's it, no forms.\n\n"
          + FEES_LINE + "\n\n"
          "Reply \"remove\" and you won't hear from me again.\n\n"
          "Sylvester\nAged Care Direct\n{site}\n{addr}"),
    "B": ("Hi,\n\n"
          "Quick one: does {name} have room for new clients this month?\n\n"
          "I'm Sylvester at Aged Care Direct. We introduce people who need aged care or disability support to providers, "
          "and I'm sorting the shortlist{where}. One line back is enough: yes/no, plus the services and areas you cover.\n\n"
          + FEES_LINE + "\n\n"
          "Reply \"remove\" if it's not for you.\n\n"
          "Sylvester\nAged Care Direct\n{site}\n{addr}"),
    "C": ("Hi,\n\n"
          "Before you ask (three providers did this week): " + FEES_LINE + "\n\n"
          "I'm Sylvester at Aged Care Direct. We introduce people needing aged care or disability support directly to providers, "
          "and I'm putting together the shortlist{where} now.\n\n"
          "If {name} takes new clients, reply with what you cover (services + areas) and I'll add you. No forms.\n\n"
          "Reply \"remove\" and you won't hear from me again.\n\n"
          "Sylvester\nAged Care Direct\n{site}\n{addr}"),
    "D": ("Hi,\n\n"
          "I'm Sylvester at Aged Care Direct. We introduce people who need aged care or disability support directly to providers. "
          "Putting together the shortlist{where} now.\n\n"
          "To make this quick, does {name} cover any of these?\n"
          "  A. In-home aged care / Home Care Package\n"
          "  B. NDIS / disability support\n"
          "  C. Support at Home\n\n"
          "Reply with the letters that fit plus the suburbs or regions you cover, and I'll add you.\n\n"
          + FEES_LINE + "\n\n"
          "Reply \"remove\" if it's not for you.\n\n"
          "Sylvester\nAged Care Direct\n{site}\n{addr}"),
}

# Arm weights: percent chance per lead. Must sum to 100. Override via ACD_ARM_WEIGHTS="A:40,B:20,C:30,D:10".
_DEFAULT_ARM_WEIGHTS = {"A": 40, "B": 20, "C": 30, "D": 10}


def _arm_weights():
    raw = os.environ.get("ACD_ARM_WEIGHTS", "")
    if not raw:
        return _DEFAULT_ARM_WEIGHTS
    out = {}
    for piece in raw.split(","):
        k, _, v = piece.strip().partition(":")
        if k in "ABCD" and v.isdigit():
            out[k] = int(v)
    if sum(out.values()) != 100 or set(out) != set("ABCD"):
        return _DEFAULT_ARM_WEIGHTS
    return out


def _arm_for(email):
    """Stable arm per address per the configured weights."""
    bucket = int(hashlib.sha1((email or "").lower().encode()).hexdigest()[:8], 16) % 100
    cum = 0
    for arm in "ABCD":
        cum += _arm_weights()[arm]
        if bucket < cum:
            return arm
    return "A"


def _subject(arm, name, email):
    """Rotate through the arm's subjects deterministically so measurement isolates subject from body."""
    subs = SUBJECTS[arm]
    idx = int(hashlib.sha1(("subj|" + (email or "")).lower().encode()).hexdigest()[:8], 16) % len(subs)
    return subs[idx].format(name=name)


def render(lead):
    where = " for " + STATE_NAME[lead["state"]] if lead.get("state") in STATE_NAME else ""
    name = html.unescape(lead["name"])
    arm = _arm_for(lead.get("email") or "")
    subj = _subject(arm, name, lead.get("email") or "")
    body = BODY[arm].format(name=name, where=where, site=SITE, addr=FOOTER_ADDR)
    lead["_arm"] = arm  # run.py picks this up for the arm-log
    return subj, body


# ---- qualification ----
ROLE_BAD = ("recruit", "careers", "jobs", "hr@", "accounts@", "accounting@", "billing@", "payroll", "noreply", "no-reply",
            "privacy@", "complaints@", "feedback@", "media@", "press@", "invoices@", "donotreply")
BIG_RX = re.compile(r"\b(council|city of|shire|hospital|university|department|health network|local health|tafe|school|library)\b", re.I)
JEV_Q = {
    "takes_clients": {"type": "noul", "instructions": "This organisation directly delivers in-home aged care, home care package services, or disability / NDIS support to clients in Australia and could accept new client introductions. Score LOW for staffing or nursing recruitment agencies, equipment suppliers, clinics, dentists, trades, councils and government bodies, peak bodies and charities that do not deliver services."},
    "owner_reads": {"type": "noul", "instructions": "This email address likely reaches the owner, manager or intake team who decides whether to take new clients."},
}
MIN_TAKES, MIN_READS = 0.65, 0.5


def clean_name(c):
    c = html.unescape(c or "")
    c = re.sub(r"\s+[-–|]\s+.*$", "", c or "").strip().rstrip(".,")
    return re.sub(r"\s+", " ", c)[:48]


def prefilter(lead):
    e = lead["email"].lower()
    dom = e.split("@")[-1]
    if dom in FREE_MAIL or dom.endswith(".gov.au") or ".health.wa" in dom or dom.endswith(".edu.au"):
        return False
    if any(b in e for b in ROLE_BAD) or BIG_RX.search(lead.get("company", "")):
        return False
    return has_mx(dom)


def score(lead):
    st = (f"Australian business listing: company='{lead.get('company')}', email='{lead['email']}', city='{lead.get('city','')}', "
          f"state='{lead.get('state','')}', directory_source='{lead.get('source','')}'.")
    s = jev(st, JEV_Q)
    if not s:
        return None
    s["score"] = round(s["takes_clients"] * s["owner_reads"], 3)
    s["ok"] = s["takes_clients"] >= MIN_TAKES and s["owner_reads"] >= MIN_READS
    return s


def seed_rows():
    """Backlog from the scraped directories (private seed, shipped in the image build context)."""
    pri = {"hcp_providers": 0, "disability_providers": 1, "support_agencies": 2}
    try:
        rows = list(csv.DictReader(open(SEED_CSV)))
    except Exception:
        return []
    rows = [r for r in rows if r.get("campaign") in pri and "@" in (r.get("email") or "")]
    # 2026-11-05: live feed from the lead-mint bridge (Jev-ranked rows only reach here).
    # URL feed first (live, no redeploy), then the image-baked copy as fallback.
    import json as _json, os as _os
    for _src in (_os.environ.get("LEAD_FEED_URL", "").strip(), _os.path.join(SEED_DIR, "seed_acd_feed.json")):
        if not _src:
            continue
        try:
            if _src.startswith("http"):
                import urllib.request as _ur
                _feed = _json.loads(_ur.urlopen(_ur.Request(_src, headers={"User-Agent": "acd-feed/1.0"}), timeout=15).read())
            else:
                if not _os.path.exists(_src):
                    continue
                _feed = _json.load(open(_src))
            rows = rows + [dict(r, campaign=r.get("campaign") or "disability_providers") for r in _feed if "@" in str(r.get("email") or "")]
        except Exception as _e:
            print("WARN acd feed:", str(_e)[:100])
    rows.sort(key=lambda r: pri[r["campaign"]])
    return [{"email": r["email"].strip().lower(), "company": r["company"], "name": clean_name(r["company"]),
             "city": r.get("city", ""), "state": r.get("state", ""), "source": r.get("source", "seed")} for r in rows]


def seed_contacted():
    try:
        return {r["email"].strip().lower() for r in csv.DictReader(open(SEED_CONTACTED))}
    except Exception:
        return set()


# ---- automatic lead harvesting (Firecrawl search) ----
SERVICES = ["NDIS registered provider", "in-home aged care provider", "home care package provider",
            "disability support services provider", "Support at Home provider"]
PLACES = [("Sydney", "NSW"), ("Melbourne", "VIC"), ("Brisbane", "QLD"), ("Perth", "WA"), ("Adelaide", "SA"),
          ("Canberra", "ACT"), ("Hobart", "TAS"), ("Darwin", "NT"), ("Newcastle", "NSW"), ("Gold Coast", "QLD"),
          ("Wollongong", "NSW"), ("Geelong", "VIC"), ("Townsville", "QLD"), ("Cairns", "QLD"), ("Toowoomba", "QLD"),
          ("Ballarat", "VIC"), ("Bendigo", "VIC"), ("Launceston", "TAS"), ("Sunshine Coast", "QLD"), ("Central Coast", "NSW"),
          ("Penrith", "NSW"), ("Frankston", "VIC"), ("Ipswich", "QLD"), ("Mandurah", "WA"), ("Mount Gambier", "SA")]


def harvest_queries():
    return [(f"{svc} {city} contact email", city, st) for city, st in PLACES for svc in SERVICES]


def leads_from_results(results, city, state):
    out = []
    for r in results or []:
        url = r.get("url") or ""
        host = re.sub(r"^https?://", "", url).split("/")[0]
        dom = reg_domain(host)
        if not dom.endswith(".au") and not dom.endswith((".com", ".org", ".net")):
            continue
        md = r.get("markdown") or ""
        # only the provider's own address: the email domain must match the site it was found on
        own = sorted({e.lower().strip(".") for e in EMAIL_RX.findall(md) if reg_domain(e.split("@")[1]) == dom})
        if not own:
            continue
        title = (r.get("title") or (r.get("metadata") or {}).get("title") or dom.split(".")[0]).strip()
        out.append({"email": own[0], "company": title, "name": clean_name(title), "city": city, "state": state, "source": "firecrawl:" + dom})
    return out
