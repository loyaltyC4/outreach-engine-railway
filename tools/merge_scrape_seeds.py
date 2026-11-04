#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bridge between the scraping agent's seed files and the engine lead feeds.

The scraping agent (per docs/SCRAPING-AGENT-HANDOVER.md + SURGICAL-SCRAPE-SPEC.md)
writes spec-schema JSON to seed/. The engines read git feeds (LEAD_FEED_URL):
leads.json (NameMarshal), leads_au.json (TenderWin), bc_leads.json (BidCheck);
ACD rows land in seed/seed_acd_feed.json for its next image build.

Run after each scrape batch:  python3 tools/merge_scrape_seeds.py [--dry]

Rules honoured (from the spec): never preverified=true (engine Jev gates them),
email dedupe, max 2 addresses per domain per campaign.
"""
import json, os, sys, datetime, subprocess
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(REPO, "seed")
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
def month_name(iso):
    try:
        d = datetime.date.fromisoformat(str(iso)[:10]); return f"{MONTHS[d.month-1]} {d.year}"
    except Exception: return None
def adapter_tw(r):
    t = r.get("trigger") or {}
    return {"company": r.get("name"), "name": r.get("name"), "email": r.get("email"),
            "emails": [r.get("email")], "trade": r.get("trade"), "province": r.get("state"),
            "state": r.get("state"), "domain": r.get("domain"), "country": "AU",
            "award_buyer": (t.get("buyer") or "").split(" - ")[0][:48] or None,
            "award_month": month_name(t.get("date")),
            "snippet": f"award {t.get('kind','')} {t.get('date','')} value={t.get('value','')}",
            "source_tag": r.get("source_tag"), "platform": None}
def adapter_bc(r):
    return {"company": r.get("name"), "name": r.get("name"), "email": r.get("email"),
            "emails": [r.get("email")], "trade": r.get("trade"),
            "province": r.get("state") or "Gauteng", "domain": r.get("domain"), "country": "ZA",
            "snippet": f"trigger {json.dumps(r.get('trigger') or {}, ensure_ascii=False)[:160]}",
            "source_tag": r.get("source_tag")}
def adapter_nm(r):
    t = r.get("trigger") or {}; sig = r.get("signals") or {}
    return {"domain": r.get("domain"), "name": r.get("name"), "store": r.get("name"),
            "email": r.get("email"), "emails": [r.get("email")], "country": r.get("country"),
            "products": None,
            "snippet": f"{t.get('kind','trigger')}: {sig.get('revenue_proxy','')} owner={sig.get('owner_confidence','')}",
            "source_tag": r.get("source_tag"), "platform": None}
def adapter_acd(r):
    return {"company": r.get("name"), "name": r.get("name"), "email": r.get("email"),
            "emails": [r.get("email")], "trade": r.get("trade") or "disability support",
            "province": r.get("state"), "state": r.get("state"), "domain": r.get("domain"),
            "country": "AU",
            "snippet": f"ndis {json.dumps(r.get('trigger') or {}, ensure_ascii=False)[:120]}",
            "source_tag": r.get("source_tag")}
FEEDS = [
    (["tw_award_winners.json","tw_prequal.json","tw_supply_nation.json"], adapter_tw, "leads_au.json"),
    (["bc_csd_winners.json","bc_cidb.json"], adapter_bc, "bc_leads.json"),
    (["nm_amazon_jp.json","nm_dubai_free_zone.json","nm_rakuten_base.json"], adapter_nm, "leads.json"),
    (["acd_ndis_providers.json","acd_hcp.json"], adapter_acd, "seed/seed_acd_feed.json"),
]
def load(p):
    try: return json.load(open(p))
    except Exception: return []
def main():
    dry = "--dry" in sys.argv
    for names, adapt, rel in FEEDS:
        rows = []
        for n in names: rows.extend(load(os.path.join(SEED, n)))
        rows = [r for r in rows if isinstance(r, dict) and "@" in str(r.get("email") or "")]
        if not rows:
            print(f"{rel}: no scraped rows yet (sources: {','.join(names)})"); continue
        adapted = [a for a in (adapt(r) for r in rows) if a["email"] and a["domain"]]
        path = os.path.join(REPO, rel)
        feed = load(path)
        have = {str(x.get("email","")).lower() for x in feed}
        dom = {}
        for x in feed: dom[str(x.get("domain") or "").lower()] = dom.get(str(x.get("domain") or "").lower(),0)+1
        added = []
        for a in adapted:
            e=a["email"].lower(); d=str(a["domain"]).lower()
            if e in have or dom.get(d,0)>=2: continue
            have.add(e); dom[d]=dom.get(d,0)+1; added.append(a)
        if added and not dry:
            feed.extend(added); json.dump(feed, open(path,"w"), indent=1, ensure_ascii=False)
            env = dict(os.environ, GIT_AUTHOR_NAME="loyaltyC4", GIT_AUTHOR_EMAIL="slyvesterchiko1@gmail.com",
                       GIT_COMMITTER_NAME="loyaltyC4", GIT_COMMITTER_EMAIL="slyvesterchiko1@gmail.com")
            subprocess.run(["git","-C",REPO,"add",rel],env=env,capture_output=True)
            subprocess.run(["git","-C",REPO,"commit","-q","-m",f"{rel}: +{len(added)} scraped leads (spec bridge)"],env=env,capture_output=True)
            subprocess.run(["git","-C",REPO,"push","-q","origin","main"],env=env,capture_output=True)
        print(f"{rel}: +{len(added)} added ({len(rows)} scraped, dropped {len(adapted)-len(added)} on dedupe/domain-cap)" + (" [DRY]" if dry else ""))
if __name__ == "__main__": main()
