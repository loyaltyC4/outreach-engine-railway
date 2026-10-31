"""NameMarshal templates — THE OWNER-APPROVED PACK (reports/cold-email-pack-2026-10-31).
Three arms (A payout / B question / C three things), CTA L (link) vs R (reply-first),
English + Japanese for JP, observation line chosen by lead source_tag. Single source of truth:
build_pack.py in reports/. Do not edit copy here without updating the pack.
"""
import hashlib

OPTOUT = 'Not relevant? Reply "remove" and I will not email again.'
OPTOUT_JA = "ご不要の場合は「remove」とご返信ください。以後ご連絡いたしません。"
SIGN = "{sender}\nNameMarshal | namemarshal.com"
LINK = "namemarshal.com/doola?utm_source=cold&utm_term={arm}"

CTA = {
    "L": "I can show you what the setup looks like for {store} on a 15-minute call, no charge: " + LINK,
    "R": 'Reply "yes" and I will send a link to a 15-minute call, no charge, to see what it would look like for {store}.',
}

SUBJECTS = {
    "A": ["{store}'s US payouts", "US LLC for {store}?", "quick question, {store}"],
    "B": ["where {store}'s US payments land", "US LLC for {store}?", "quick question, {store}"],
    "C": ["US LLC for {store}?", "{store}'s US payouts", "quick question, {store}"],
}

E1 = {
    "A": "{greeting}\n\n{observation}\n\nA US Stripe account is built around three things: a US LLC, an EIN and a US bank account. Stripe and Shopify also tend to look harder at payouts that land in a Wise or Payoneer-style account than at a real US bank account.\n\nAs a non-resident you can get the EIN without an SSN. {cta}\n\n" + OPTOUT + "\n\n" + SIGN,
    "B": "{greeting}\n\n{observation}\n\nQuick question: when a US customer pays {store}, where does the money land, and how many hops before it reaches you?\n\nEach hop is a place for an FX spread or a payout hold to show up. A US LLC, an EIN (no SSN needed for non-residents) and a US bank account cut most of them out. {cta}\n\n" + OPTOUT + "\n\n" + SIGN,
    "C": "{greeting}\n\n{observation}\n\nSelling into the US from {country} usually comes down to three things: a US LLC, an EIN (non-residents do not need an SSN) and a US bank account behind your payouts.\n\nWhether that is worth doing depends on how much {store} sells in the US. {cta} No pitch either way.\n\n" + OPTOUT + "\n\n" + SIGN,
}

SUBJECTS_JA = ["{store}様の米国向け入金について", "{store}様のUS LLCについて", "{store}様の米国売上について"]
E1_JA = "{greeting_ja}\n\n{observation_ja}\n\n米国向けのStripeアカウントは、米国のLLC、EIN、米国の銀行口座の3つを前提にしています。StripeやShopifyは、WiseやPayoneerのような口座への入金を、実在する米国の銀行口座への入金よりも慎重に確認する傾向があります。\n\n非居住者はSSNなしでEINを取得できます。{store}様の場合に具体的にどうなるか、15分のオンライン通話（無料）でご説明します：{link}\n\n" + OPTOUT_JA + "\n\n{sender}\nNameMarshal | namemarshal.com"

# observation lines by source_tag (use only when the signal is true; source_tag is set by the harvest)
OBSERVATIONS = {
    "U-FZ":    "Saw {store} was licensed in {free_zone} recently, congratulations.",
    "U-AMZ":   "Noticed {store} is on Amazon.com now as well as Amazon.ae.",
    "U-FB":    "You mentioned in {group} that you are looking at selling to the US.",
    "U-AD":    "Noticed {store} is running ads aimed at US shoppers.",
    "U-FORUM": "Saw your question about Stripe payouts for a business based in the UAE.",
    "U-SITE":  "{store} sells to US customers from the UAE.",
    "J-AMZ":   "Noticed {store} ships from Japan to US customers on Amazon.com.",
    "J-MALL":  "Noticed {store} sells to overseas customers through {platform}.",
    "J-JETRO": "Saw {store} took part in a JETRO programme for selling overseas.",
    "J-AD":    "Noticed {store} is running ads aimed at US shoppers.",
    "J-FORUM": "Saw your question about Stripe payouts for a business based in Japan.",
    "J-SITE":  "{store} sells to US customers from Japan.",
}
OBS_JA = {
    "J-AMZ":   "{store}がAmazon.comで日本から米国のお客様に発送されているのを拝見しました。",
    "J-MALL":  "{store}が{platform}で海外のお客様に向けて販売されているのを拝見しました。",
    "J-SITE":  "{store}が日本から米国のお客様に向けて販売されているのを拝見しました。",
}

GREETING_EN = "Hi {first},"
GREETING_JA = "{first}様、いつもお世話になっております。"
FALLBACK_SIGNER = "Daniel"

COUNTRY_NAME = {"AE": "the UAE", "JP": "Japan"}


def _h(email, mod):
    return int(hashlib.sha1((email or "").lower().encode()).hexdigest()[:8], 16) % mod


_JUNK_TITLE = ("payment","shipping","options","contact","about","policy","terms","privacy","faq","home",
               "welcome","cart","checkout","account","login","delivery","returns","blog","news","store","shop online","official site")

def _clean_name(lead):
    raw = (lead.get("name") or lead.get("store") or "").strip()
    dom = (lead.get("domain") or "").lower()
    low = raw.lower()
    if (not raw) or (len(raw) < 3) or any(low.startswith(w) or low == w or f"{w} " in low for w in _JUNK_TITLE) or raw.count(" ") > 5:
        if dom:
            part = dom.split(".")[0].replace("-", " ").replace("_", " ")
            return " ".join(w.capitalize() for w in part.split() if w)
        return "your store"
    return raw


def render(lead, send_index=0):
    """Returns (subject, body). Arm + CTA mode are stable per lead; subject rotates by send_index."""
    store = _clean_name(lead)
    email = lead.get("email") or ""
    country = lead.get("country") or ""
    arm = "ABC"[_h(email, 3)]
    cta_mode = "LR"[_h(email + "|cta", 2)]
    use_ja = country == "JP" and _h(email + "|ja", 100) < 50
    tag = lead.get("source_tag") or ("J-SITE" if country == "JP" else "U-SITE")

    first = (lead.get("contact") or "").split()[0] if (lead.get("contact") or "").split() else ""
    greeting = GREETING_EN.format(first=first) if first else f"Hi {store} team,"
    fields = {
        "store": store,
        "country": COUNTRY_NAME.get(country, country),
        "greeting": greeting,
        "sender": FALLBACK_SIGNER,
        "arm": arm,
        "link": LINK.replace("{arm}", arm),
        "cta": "",
        "free_zone": lead.get("free_zone") or "the free zone",
        "platform": lead.get("platform") or "your store platform",
        "group": lead.get("group") or "the group",
    }
    fields["cta"] = CTA[cta_mode].format(**fields)
    fields["observation"] = OBSERVATIONS.get(tag, OBSERVATIONS["J-SITE" if country == "JP" else "U-SITE"]).format(**fields)

    if use_ja:
        greeting_ja = (GREETING_JA.format(first=first) if first else f"{store}様、いつもお世話になっております。")
        fields["greeting_ja"] = greeting_ja
        fields["observation_ja"] = OBS_JA.get(tag, OBS_JA["J-SITE"]).format(**fields)
        subj = SUBJECTS_JA[send_index % len(SUBJECTS_JA)].format(**fields)
        body = E1_JA.format(**fields)
    else:
        subs = SUBJECTS[arm]
        subj = subs[send_index % len(subs)].format(**fields)
        body = E1[arm].format(**fields)
    return subj, body
