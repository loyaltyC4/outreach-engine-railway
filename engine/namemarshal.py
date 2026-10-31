"""NameMarshal: US-company-formation call booking. Targeting restricted to UAE, Canada, UK only
(the owner's call: wealthier markets with real USD/payment friction and the ability to pay doola's fees).
Qualification = sells to the US + no visible US entity + real revenue signal (reviews/catalogue/pricing)."""
import hashlib, html, json, os, re
from util import EMAIL_RX, reg_domain, has_mx, jev

NAME = "namemarshal"
SEED_DIR = os.environ.get("SEED_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")
SEED_JSON = os.path.join(SEED_DIR, "nm_seed_aecagb.json")
REPLY_HINTS = ("us customers", "and us customers", "us company", "llc")
SITE = "https://namemarshal.com/doola"
COUNTRY_NAME = {"AE": "the UAE", "JP": "Japan"}
PAIN = {
    "AE": "a UAE biller means shakier Stripe/PayPal payouts in USD, and shoppers notice the extra step at checkout",
    "CA": "US buyers often stall at checkout once they see a non-US biller, or you're quietly eating the FX spread on every sale",
    "GB": "a UK biller adds an FX step, and US cards get declined more than people realise",
    "JP": "Japanese card processing settles in JPY, so every US order carries an FX step and the payout account gets flagged more often",
}

# ---- copy (v2, 2026-10-28: cold-email + marketing-psychology pass — peer tone, one CTA, loss-aversion framing) ----
SUBJECTS = ["quick one on {store}'s US orders", "{store} -> US customers", "US side of {store}"]
BODY = (
    "Hi,\n\n"
    "{store} ships to the US, but running it from {country} usually means {pain}.\n\n"
    "The fix is a US LLC with an EIN and a US bank account, it's what lets US shoppers pay you like a local store, "
    "no middleman taking a cut of your margin.\n\n"
    "Worth 15 minutes to see if it's worth it for {store}? No-cost call, no pitch either way:\n{site}\n\n"
    "Reply \"remove\" and I'll leave it there.\n\n"
    "NameMarshal\nhttps://namemarshal.com"
)


# ---- copy (v3, 2026-10-28: research-grounded A/B arm against v2) ----
# Verified via live web research before writing this (sources in project_outreach_engine memory): Stripe's
# requirement is the clean, stable one (US entity + EIN + US bank account for payouts); Shopify Payments has
# gotten stricter and increasingly wants proof of physical US operations beyond LLC+EIN+bank, so v2/v3 both
# lean on the Stripe-payout angle rather than promising to fully fix Shopify Payments, which we can't guarantee.
# Two real, specific, truthful details added: non-residents can get an EIN without an SSN (kills a live
# objection), and Stripe/Shopify flag non-bank payout accounts (Wise/Payoneer/Revolut-style) more than a real
# US bank account (gives the "why" instead of just asserting a fix).
SUBJECTS_V3 = ["{store}'s Stripe payouts", "quick Stripe/EIN question", "about {store}'s US payouts"]
PAIN_V3 = {
    "AE": "Stripe either won't onboard the payout account or flags it, since it's not behind a US bank",
    "CA": "Stripe and Shopify Payments both expect a US bank account behind the payout, and a Canadian one doesn't cut it",
    "GB": "Stripe wants a US bank account behind the payout, not a UK one, so it flags it or won't onboard it at all",
    "JP": "the payout sits behind a Japanese bank, so US processors flag it or the FX spread eats the margin on every US order",
}
BODY_V3 = (
    "Hi,\n\n"
    "{store} sells to US customers from {country}, which is usually exactly what gets a Stripe payout account "
    "flagged: {pain}.\n\n"
    "The fix is a US LLC + EIN (no SSN needed) + a real US bank account behind it, not a Wise/Payoneer-style "
    "account, which is what trips the flag in the first place.\n\n"
    "Worth 15 minutes to see if it's worth it for {store}? No-cost call, no pitch:\n{site}\n\n"
    "Reply \"remove\" and I'll leave it there.\n\n"
    "NameMarshal\nhttps://namemarshal.com"
)


def render(lead):
    import random
    store = html.unescape(lead["store"])
    cn = COUNTRY_NAME.get(lead["country"], lead["country"])
    use_v3 = int(hashlib.sha1((lead.get("email") or "").lower().encode()).hexdigest()[:8], 16) % 100 < 50
    if use_v3:
        subj = random.choice(SUBJECTS_V3).format(store=store)
        body = BODY_V3.format(store=store, country=cn, pain=PAIN_V3.get(lead["country"], "a non-US payout account gets flagged more often"), site=SITE)
    else:
        subj = random.choice(SUBJECTS).format(store=store)
        body = BODY.format(store=store, country=cn, pain=PAIN.get(lead["country"], "extra friction on every US sale"), site=SITE)
    return subj, body


# ---- qualification ----
ROLE_BAD = ("privacy", "careers", "career", "jobs", "job", "hr", "recruitment", "collab", "collabs", "collaboration",
            "press", "media", "pr", "legal", "dmca", "abuse", "returns", "refunds", "wholesale", "billing", "accounts",
            "accounting", "invoices", "noreply", "no-reply", "donotreply", "affiliates", "affiliate", "influencers",
            "marketing", "newsletter", "dispatch", "shipping", "warehouse", "logistics", "payments", "payment", "finance")
JEV_Q = {
    "doola_fit": {"type": "noul", "instructions": "This store's owner is outside the US, sells to US customers, and plausibly lacks a US LLC, so a US LLC + EIN + US bank solves a real problem for them"},
    "can_pay": {"type": "noul", "instructions": "The business has real revenue (catalogue size, review count, pricing, reputation) to pay $300-$3000/yr without hesitation; score HIGH only for an established, clearly-trading business"},
    "owner_reachable": {"type": "noul", "instructions": "The listed email likely reaches the owner or a real decision maker directly, not a support desk of a large/well-known brand"},
    "too_big": {"type": "noul", "instructions": "This is a large, established or famous brand that already has US counsel/entities, so it is a poor cold-email target"},
}
MIN_FIT, MIN_PAY, MAX_BIG = 0.55, 0.45, 0.45
COUNTRIES = {"AE", "JP"}  # 2026-10-31 owner decision: rich markets only — UAE + Japan (CA/GB have Stripe; no pain there)


def pick_email(emails, domain):
    root = (domain or "").lower().replace("www.", "").split(".")[0]
    cands = []
    for e in emails or []:
        e = str(e).strip().lower().strip(".,;")
        if "@" not in e:
            continue
        lp, ed = e.split("@", 1)
        if lp in ROLE_BAD or root[:5] not in ed.replace("-", ""):
            continue
        core = lp.replace(".", "").replace("_", "").replace("-", "")
        tier = 0 if (core.isalpha() and len(core) <= 20) else (1 if lp in ("hello", "hi", "contact", "info", "team", "office", "sales", "shop", "orders") else 3)
        cands.append((tier, e))
    if not cands:
        return None
    return sorted(cands)[0][1]


def prefilter(lead):
    if lead.get("country") not in COUNTRIES:
        return False
    return has_mx(lead["email"].split("@")[1])


def score(lead):
    if lead.get("products") or lead.get("reviews"):
        extra = f"products={lead.get('products')}, reviews={lead.get('reviews')}"
    else:
        extra = f"page snippet: {(lead.get('snippet') or '')[:500]}"
    st = (f"Shopify/e-commerce store: name='{lead['store']}', domain='{lead['domain']}', country='{lead['country']}', {extra}. "
          f"Offer: free 15-min call to explore forming a US LLC + EIN + US bank account.")
    s = jev(st, JEV_Q)
    if not s:
        return None
    s["score"] = round(0.45 * s["doola_fit"] + 0.4 * s["can_pay"] + 0.15 * s["owner_reachable"] * (1 - s["too_big"]), 3)
    s["ok"] = s["doola_fit"] >= MIN_FIT and s["can_pay"] >= MIN_PAY and s["too_big"] <= MAX_BIG
    return s


def seed_rows():
    try:
        raw = json.load(open(SEED_JSON))
    except Exception:
        return []
    out = []
    for r in raw:
        e = pick_email(r.get("emails"), r["domain"])
        if not e:
            continue
        name = re.sub(r"\s*[|\-:–—].*$", "", r.get("name") or r["domain"].split(".")[0]).strip()[:40]
        out.append({"email": e, "store": name or r["domain"], "domain": r["domain"], "country": r["country"],
                     "products": r.get("products"), "reviews": r.get("reviews"), "source": "seed"})
    return out


def seed_contacted():
    return set()


# ---- fresh lead harvesting (Firecrawl): city x category combinatorial, so the query pool is wide ----
CITIES = {
    "AE": ["Dubai", "Abu Dhabi", "Sharjah"],
    "CA": ["Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa", "Edmonton"],
    "GB": ["London", "Manchester", "Birmingham", "Glasgow", "Leeds", "Bristol", "Edinburgh"],
}
CATEGORIES = ["fashion", "beauty and skincare", "jewelry", "home decor", "pet products", "fitness gear",
              "baby products", "outdoor gear", "supplements and wellness", "accessories", "candle and gift",
              "activewear", "footwear", "coffee and food brand", "furniture",
              "watches", "sunglasses", "bags and luggage", "swimwear", "art prints", "phone accessories",
              "stationery and gifts", "toys", "haircare", "men's grooming", "tea and specialty food",
              "kitchenware", "yoga and wellness accessories", "sneakers", "plus size fashion"]


def harvest_queries():
    out = []
    for country, cities in CITIES.items():
        for city in cities:
            for cat in CATEGORIES:
                out.append((f"{city} {cat} online store Shopify ships to USA contact email", country))
    return out


def leads_from_results(results, country):
    out = []
    for r in results or []:
        url = r.get("url") or ""
        host = re.sub(r"^https?://", "", url).split("/")[0]
        dom = reg_domain(host)
        md = r.get("markdown") or ""
        own = sorted({e.lower().strip(".") for e in EMAIL_RX.findall(md) if reg_domain(e.split("@")[1]) == dom})
        e = pick_email(own, dom)
        if not e:
            continue
        title = (r.get("title") or (r.get("metadata") or {}).get("title") or dom.split(".")[0]).strip()
        name = re.sub(r"\s*[|\-:–—].*$", "", title).strip()[:40] or dom
        snippet = re.sub(r"\s+", " ", md)[:600]
        out.append({"email": e, "store": name, "domain": dom, "country": country, "snippet": snippet, "source": "firecrawl:" + dom})
    return out
