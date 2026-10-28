"""Aged Care Direct: partner-invitation campaign. Everything campaign-specific lives here:
who qualifies, how new leads are found, and the email copy (edit COPY when the wording changes)."""
import csv, html, os, re
from util import FREE_MAIL, EMAIL_RX, reg_domain, has_mx, jev

NAME = "acd"
REPLY_HINTS = ("new client introductions", "equipment quotes", "same-day equipment")
SEED_DIR = os.environ.get("SEED_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")
SEED_CSV = os.path.join(SEED_DIR, "acd_leads.csv")
SEED_CONTACTED = os.path.join(SEED_DIR, "acd_contacted.csv")
SENDER_NAME = "Sylvester"
BRAND = "Aged Care Direct"
FOOTER_ADDR = "Aged Care Direct, Melbourne VIC, Australia"
SITE = "https://agedcaredirect.com.au"

STATE_NAME = {"NSW": "NSW", "VIC": "Victoria", "QLD": "Queensland", "WA": "Western Australia", "SA": "South Australia",
              "TAS": "Tasmania", "ACT": "the ACT", "NT": "the Northern Territory"}

# ---- copy (v1). Subject and body are plain text on purpose: best deliverability for a cold first touch. ----
COPY = {
    "subject": "new client introductions for {name}",
    "body": (
        "Hi,\n\n"
        "I'm Sylvester at Aged Care Direct. We connect Australians who need aged care and disability support with providers, "
        "and we're building a short list of local providers{where} that we can introduce new clients to.\n\n"
        "If {name} has capacity for new clients, reply with the areas you cover and the services you offer, and I'll add you to the list. "
        "Introductions depend on fit and location.\n\n"
        "If this isn't relevant, reply \"remove\" and you won't hear from me again.\n\n"
        "Sylvester\nAged Care Direct\n{site}\n{addr}"
    ),
}


def render(lead):
    where = " in " + STATE_NAME[lead["state"]] if lead.get("state") in STATE_NAME else ""
    name = html.unescape(lead["name"])
    return (COPY["subject"].format(name=name),
            COPY["body"].format(name=name, where=where, site=SITE, addr=FOOTER_ADDR))


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
