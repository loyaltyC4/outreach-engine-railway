#!/usr/bin/env python3
"""Build seed/tw1000_leads.json: harvested emails joined to TenderWin profiles by normalised name.

Reality of the AU dataset (2026-11-19): vula_sub_profiles has no state, website, phone, postcode or
claim_email, and vula_awards.province is mostly null/"National" for these non-winner leads. So:
profile_id is joined for arm B, state is filled where an award province exists, and the gaps are
reported rather than invented.
"""
import collections
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "engine"))
import tenderwin  # noqa: E402
import tw1000  # noqa: E402

PROJECT = "lwwahygviakbccwoqvfo"
SECRET = open("/tmp/au_key").read().strip()
SRC = os.path.join(HERE, "tenderwin_leads.json")
OUT = os.path.join(HERE, "tw1000_leads.json")
STATE_HINTS = json.load(open("/tmp/supplier_state.json")) if os.path.exists("/tmp/supplier_state.json") else {}

DROP = re.compile(r"\b(pty|ltd|limited|inc|aust|australia|group|holdings|the)\b", re.I)
OUT_NAMES = re.compile(r"\b(department|council|university|trustee|hospital|city of|shire of)\b", re.I)
TERRITORY = {"02": "NSW", "03": "VIC", "07": "QLD", "08": "WA"}


def prefix_match(key):
    """Fallback when the exact normalised name misses: prefix search on name_key."""
    if len(key) < 6:
        return []
    q = urllib.parse.quote(key[:24])
    try:
        return api(f"vula_sub_profiles?select=id,name,abn,trades,award_count,award_total,award_buyers,last_award&name_key=ilike.*{q}*&limit=5")
    except Exception:
        return []


def api(path):
    req = urllib.request.Request(f"https://{PROJECT}.supabase.co/rest/v1/{path}",
                                 headers={"apikey": SECRET, "Authorization": "Bearer " + SECRET})
    return json.load(urllib.request.urlopen(req, timeout=60))


def norm(name):
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = re.sub(r"\s+", " ", DROP.sub(" ", s)).strip()
    return s.replace(" ", "")


def trade_of(*labels):
    for lab in labels:
        for t, rx in tenderwin.TRADE_RX.items():
            if lab and re.search(rx, str(lab), re.I):
                return t
    return ""


def main():
    rows = json.load(open(SRC))
    profiles = collections.defaultdict(list)
    for off in range(0, 11000, 1000):
        got = api(f"vula_sub_profiles?select=id,name,abn,trades,award_count,award_total,award_buyers,last_award&limit=1000&offset={off}")
        if not got:
            break
        for p in got:
            profiles[norm(p.get("name"))].append(p)

    import concurrent.futures as cf
    seen, out, drops = set(), [], collections.Counter()
    for r in rows:
        em = (r.get("email") or "").strip().lower()
        co = (r.get("company") or "").strip()
        if not em or em in seen:
            drops["dup/empty"] += 1
            continue
        seen.add(em)
        dom_em = em.split("@")[-1]
        if re.search(r"\.(gov|edu)\.au$|\.gov$|\.edu$", dom_em):
            drops["gov/edu domain"] += 1
            continue
        if OUT_NAMES.search(co):
            drops["out-of-scope name"] += 1
            continue
        trade = trade_of(r.get("trade"))
        if not trade:
            drops["no trade"] += 1
            continue
        if len(co.split()) < 2 or co.lower() in ("contact", "industry", "team", "home", "about"):
            co = em.split("@")[-1].split(".")[0].replace("-", " ").title()   # "claims.au@sedgwick.com" -> "Sedgwick"
        nk = norm(co)
        cand = profiles.get(nk)
        if not cand:
            # a loose ilike on name_key can land on an unrelated company; keep it only when one
            # normalised name is a prefix of the other
            cand = [p for p in prefix_match(nk) if len(norm(p.get("name"))) >= 8
                    and (nk.startswith(norm(p.get("name"))) or norm(p.get("name")).startswith(nk))]
        pr = max(cand, key=lambda p: int(p.get("award_count") or 0)) if cand else None
        if pr and pr.get("name"):
            co = pr["name"]                      # the harvested name is often junk ("Industry"); trust the ABN record

        if pr is None:
            drops["no profile match"] += 1
        elif int(pr.get("award_count") or 0) > 25 or float(pr.get("award_total") or 0) > 20_000_000:
            drops["not SME"] += 1
            continue
        hinted = STATE_HINTS.get(co.lower()) or {}
        state = (max(hinted, key=hinted.get) if hinted else "") or (r.get("state") or TERRITORY.get((r.get("phone") or "")[:2], ""))
        out.append({
            "email": em, "company": co, "contact_name": r.get("contact_name") or "",
            "trade": trade, "state": state, "profile_id": (pr or {}).get("id"),
            "abn": (pr or {}).get("abn") or "", "award_buyers": (pr or {}).get("award_buyers") or [],
            "last_award": (pr or {}).get("last_award") or "", "award_count": int((pr or {}).get("award_count") or 0),
            "award_total": float((pr or {}).get("award_total") or 0),
            "consent_source_url": "", "consent_seen_at": "", "source": r.get("source") or "",
            "arm": tw1000.arm_for(em),
        })

    out.sort(key=lambda l: (-l["award_count"], l["company"]))
    json.dump(out, open(OUT, "w"), indent=1)
    arms = collections.Counter(l["arm"] for l in out)
    print(json.dumps({"kept": len(out), "arms": dict(arms),
                      "with_profile": sum(1 for l in out if l["profile_id"]),
                      "with_state": sum(1 for l in out if l["state"]),
                      "drops": dict(drops)}, indent=1))


main()
