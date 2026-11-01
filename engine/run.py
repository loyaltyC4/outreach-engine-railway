#!/usr/bin/env python3
"""Outreach engine. One run (a Railway cron tick) does, in order:
   guard -> read inbound (bounces, complaints, removes, real replies) -> refill the lead pool -> send within caps -> daily digest.

   python3 run.py acd            normal run
   python3 run.py acd prescore   build the starting lead pool offline (used before the first deploy)
   python3 run.py acd status     print pool / sent / guard state

Environment: AGENTMAIL_KEYS (comma list), TYPESAFE_API_KEY (Jev), FIRECRAWL_KEYS (comma list), OWNER_EMAIL,
DATA_DIR, DRY_RUN, KILL_SWITCH, INBOX_DAILY_CAP, DAILY_MAX, MAX_PER_RUN, AU_OFFSET_HOURS, WINDOW (e.g. 9:00-16:30), WEEKDAYS_ONLY.
"""
import collections, concurrent.futures as cf, importlib, json, os, random, re, sys, time, fcntl
import datetime as dt
from util import *

CAMP = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CAMPAIGN", "acd")
MODE = sys.argv[2] if len(sys.argv) > 2 else "run"
C = importlib.import_module(CAMP)
DATA = os.path.join(os.environ.get("DATA_DIR", "/data"), CAMP)
E = lambda k, d: os.environ.get(k, d)
DRY = E("DRY_RUN", "").lower() in ("1", "true", "yes")
KEYS = [k.strip() for k in E("AGENTMAIL_KEYS", "").split(",") if k.strip()]
OWNER = E("OWNER_EMAIL", "")
INBOX_CAP = int(E("INBOX_DAILY_CAP", "8"))        # total sends per inbox per day, counted from AgentMail so other lanes are included
DAILY_MAX = int(E("DAILY_MAX", "150"))             # this campaign's sends per day
MAX_RUN = int(E("MAX_PER_RUN", "10"))
MIN_POOL = int(E("MIN_POOL", "400"))
SCORE_BATCH = int(E("SCORE_BATCH", "150"))
HARVEST_PER_RUN = int(E("HARVEST_PER_RUN", "4"))
AU_OFF = float(E("AU_OFFSET_HOURS", "11"))
WINDOW = E("WINDOW", "9:00-16:30")
WEEKDAYS = E("WEEKDAYS_ONLY", "1") == "1"
BOUNCE_PAUSE = float(E("BOUNCE_PAUSE_RATE", "0.06"))
P = lambda name: os.path.join(DATA, name)


def lday(ts):
    """Calendar day in Australian local time for an ISO timestamp (caps reset at local midnight)."""
    try:
        return (dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S") + dt.timedelta(hours=AU_OFF)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def log(*a):
    print("[%s]" % iso(), *a, flush=True)


# ---------------- state ----------------
S = {}


def st(name, default):
    if name not in S:
        S[name] = load(P(name + ".json"), default)
    return S[name]


def flush():
    for n, v in S.items():
        save(P(n + ".json"), v)


def bootstrap():
    os.makedirs(DATA, exist_ok=True)
    seed_state = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed", "state", CAMP)
    if not os.path.exists(P("pool.json")) and os.path.isdir(seed_state):
        for f in os.listdir(seed_state):
            open(P(f), "wb").write(open(os.path.join(seed_state, f), "rb").read())
        log("seeded state from image:", os.listdir(seed_state))


# ---------------- mailboxes ----------------
def discover():
    import re as _re
    allow = E("INBOX_ALLOW_REGEX", "")
    deny = E("INBOX_DENY_REGEX", "")
    rx = _re.compile(allow) if allow else None
    rx_deny = _re.compile(deny) if deny else None
    ib = {}
    for k in KEYS:
        c, d = am(k, "GET", "/inboxes?limit=100")
        for x in d.get("inboxes", []) if c == 200 else []:
            iid = x.get("inbox_id") or x.get("email")
            if rx and not rx.search(iid):
                continue
            if rx_deny and rx_deny.search(iid):
                continue
            ib[iid] = k
    if rx or rx_deny:
        log(f"inbox filter allow=[{allow}] deny=[{deny}]: {len(ib)} inboxes in use")
    return ib


def sent_ground_truth(inbox_key):
    """Every address we have mailed from any of these inboxes (any campaign), plus per-inbox sends today."""
    today = lday(iso())
    addrs, per_inbox, last48 = set(), collections.Counter(), []

    def one(item):
        iid, k = item
        c, d = am(k, "GET", f"/inboxes/{q(iid)}/messages?labels=SENT&limit=100")
        return iid, (d.get("messages", []) if c == 200 else [])
    with cf.ThreadPoolExecutor(10) as ex:
        for iid, ms in ex.map(one, inbox_key.items()):
            for m in ms:
                ts = (m.get("timestamp") or m.get("created_at") or "")
                for a in msg_to(m):
                    addrs.add(a)
                if lday(ts) == today:
                    per_inbox[iid] += 1
                last48.append((ts, msg_to(m)))
    return addrs, per_inbox, last48


# ---------------- inbound ----------------
AUTO_RX = re.compile(r"auto(matic)?[- ]?reply|out of office|autoreply|ticket|case (number|#|id)|we.ve received|thank you for (contacting|your email|emailing)|"
                     r"thanks for (contacting|reaching)|enquiry (has been )?received|do not reply|no[- ]?reply|unmonitored|not monitored|no longer monitored|on leave", re.I)
STOP_RX = re.compile(r"^\W*(please\s+)?(remove|unsubscribe|stop)\b|remove me|take me off|do not (contact|email)|not interested|no thanks|opt.?out", re.I)


def classify(m, preview):
    f = parse_addr(m.get("from") or m.get("from_") or "")
    subj = str(m.get("subject") or "")
    sl = subj.lower()
    if "email-abuse" in f or "feedback report" in sl or "complaint" in sl and "amazonses" in f:
        return "complaint"
    if "mailer-daemon" in f or "postmaster" in f or any(w in sl for w in (
            "delivery status", "undeliverable", "failure notice", "couldn't be delivered", "returned mail", "permanent failure", "delivery has failed")):
        return "bounce"
    if any(w in f for w in ("noreply", "no-reply", "donotreply", "agentmail.to")):
        return "auto"
    if not (sl.startswith(("re:", "fw:", "fwd:", "aw:")) or any(h in sl for h in C.REPLY_HINTS)):
        return "other"                   # vendor newsletters, sign-up mail and so on: ignore completely
    if STOP_RX.search(preview[:240]):
        return "stop"
    if AUTO_RX.search(sl + " " + preview[:300]):
        return "auto"
    return "human"


def process_inbound(inbox_key, sent_addrs):
    seen = st("inbound_seen", {})
    sup = st("suppress", {"emails": [], "domains": []})
    fwd = st("forwarded", {})
    events = collections.Counter()
    new_human = []
    since = (now() - dt.timedelta(days=int(E("INBOUND_DAYS", "7")))).strftime("%Y-%m-%dT%H:%M:%S")

    def one(item):
        iid, k = item
        c, d = am(k, "GET", f"/inboxes/{q(iid)}/messages?limit=100")
        return iid, k, (d.get("messages", []) if c == 200 else [])
    with cf.ThreadPoolExecutor(10) as ex:
        res = list(ex.map(one, inbox_key.items()))
    for iid, k, ms in res:
        for m in ms:
            mid = m.get("message_id") or m.get("id")
            ts = (m.get("timestamp") or "")[:19]
            f = parse_addr(m.get("from") or m.get("from_") or "")
            if not mid or mid in seen or ts < since or iid.split("@")[0].lower() in f:
                continue
            prev = re.sub(r"\s+", " ", str(m.get("preview") or m.get("extracted_text") or m.get("text") or ""))
            kind = classify(m, prev)
            seen[mid] = kind
            events[kind] += 1
            dom = f.split("@")[-1] if "@" in f else ""
            if kind == "bounce":
                c, full = am(k, "GET", f"/inboxes/{q(iid)}/messages/{q(mid)}")
                body = " ".join(str(full.get(x) or "") for x in ("text", "extracted_text", "html")) if c == 200 else prev
                for a in set(a.lower().strip(".,;<>") for a in EMAIL_RX.findall(body)):
                    if a in sent_addrs:
                        if a not in sup["emails"]:
                            sup["emails"].append(a)
                        st("bounces", []).append({"to": a, "ts": iso()})
            elif kind == "complaint":
                # only a complaint about OUR emails pauses sending; mail from other tools using these inboxes is reported, not blocking
                c2, full = am(k, "GET", f"/inboxes/{q(iid)}/messages/{q(mid)}")
                txt = " ".join(str(full.get(x) or "") for x in ("text", "extracted_text", "html")) if c2 == 200 else ""
                orig = (re.search(r"Subject:\s*([^\n\r]{0,160})", txt) or [None, ""])[1]
                _ss = st("sent", {})
                _cut21 = (now() - dt.timedelta(days=21)).strftime("%Y-%m-%dT%H:%M:%S")
                _ours_recently = any(
                    v.get("inbox") == iid and str(v.get("ts", ""))[:19] >= _cut21
                    for v in _ss.values())
                if any(h in orig.lower() for h in C.REPLY_HINTS) and _ours_recently:
                    st("paused", {})["complaint"] = {"ts": iso(), "inbox": iid, "original_subject": orig}
                else:
                    st("foreign_complaints", []).append({"ts": iso(), "inbox": iid, "original_subject": orig})
                    # 2026-10-31: alert only FRESH foreign complaints (<24h) — redeployed containers otherwise
                    # re-alert the owner on every historical complaint in the inbox (duplicate-alert flood).
                    _fresh = ts[:19] >= (now() - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
                    if _fresh and E("FOREIGN_COMPLAINT_NOTIFY", "1") == "1":
                        notify(inbox_key, f"[{CAMP.upper()}] spam complaint about mail NOT sent by this engine",
                               f"Inbox: {iid}\nOriginal subject: {orig}\nSomething else is sending from this inbox; complaints hurt every campaign that shares it.")
            elif kind == "stop":
                if dom and dom not in sup["domains"] and dom not in FREE_MAIL:
                    sup["domains"].append(dom)
                if f and f not in sup["emails"]:
                    sup["emails"].append(f)
            elif kind == "human":
                # a person answered: never cold-mail that organisation again, and tell the owner (no auto-reply)
                if dom and dom not in sup["domains"] and dom not in FREE_MAIL:
                    sup["domains"].append(dom)
                new_human.append((iid, k, mid, f, str(m.get("subject") or ""), ts))
    meta = st("meta", {})
    meta.setdefault("started", iso(now() - dt.timedelta(hours=int(E("NOTIFY_BACKFILL_HOURS", "12")))))
    for iid, k, mid, f, subj, ts in new_human:
        if mid in fwd:
            continue
        if ts < meta["started"][:19]:
            fwd[mid] = "backfill-skipped"
            continue
        c, full = am(k, "GET", f"/inboxes/{q(iid)}/messages/{q(mid)}")
        body = re.sub(r"[ \t]+", " ", str(full.get("extracted_text") or full.get("text") or ""))[:1800] if c == 200 else ""
        notify(inbox_key, f"[{CAMP.upper()} reply] {subj[:70]}",
               f"From: {f}\nTo inbox: {iid}\nReceived: {ts}\nThread: reply from the same inbox to continue (the engine does NOT auto-reply to people).\n\n{body}")
        fwd[mid] = iso()
    return events


def notify(inbox_key, subject, body):
    if not OWNER or not inbox_key or DRY:
        log("NOTIFY(dry)" if DRY else "NOTIFY(no owner/inbox)", subject)
        return
    iid, k = sorted(inbox_key.items())[0]
    c, _ = am(k, "POST", f"/inboxes/{q(iid)}/messages/send", {"to": [OWNER], "subject": subject, "text": body})
    log("notified owner", c, subject)


# ---------------- guards ----------------
def guard(inbox_key, last48, sent_ours):
    paused = st("paused", {})
    if E("KILL_SWITCH", "") == "1":
        return "KILL_SWITCH=1"
    if paused.get("complaint") and not paused.get("complaint_cleared"):
        return "paused after a spam complaint: " + json.dumps(paused["complaint"])
    cut = (now() - dt.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S")
    n_sent = sum(1 for ts, tos in last48 if ts[:19] >= cut and any(t in sent_ours for t in tos))
    n_bounce = sum(1 for b in st("bounces", []) if b["ts"][:19] >= cut)
    rate = n_bounce / n_sent if n_sent >= 40 else 0
    if rate > BOUNCE_PAUSE and not paused.get("bounce_cleared"):
        paused["bounce"] = {"ts": iso(), "rate": round(rate, 3), "sent48": n_sent}
        return f"paused: bounce rate {rate:.1%} over {n_sent} sends in 48h"
    return None


def in_window():
    local = now() + dt.timedelta(hours=AU_OFF)
    if WEEKDAYS and local.weekday() >= 5:
        return False
    a, b = WINDOW.split("-")
    ah, am_ = [int(x) for x in a.split(":")]
    bh, bm = [int(x) for x in b.split(":")]
    t = local.hour * 60 + local.minute
    return ah * 60 + am_ <= t <= bh * 60 + bm


# ---------------- pool ----------------
def pool_unsent(pool, sent_all, sup):
    """Leads we may still mail: not sent, not suppressed, and no address at the same organisation already mailed."""
    mailed_domains = {reg_domain(a.split("@")[1]) for a in sent_all if "@" in a}
    out = []
    for l in pool:
        e = l["email"]
        d = e.split("@")[1]
        if e in sent_all or e in sup["emails"] or d in sup["domains"] or reg_domain(d) in mailed_domains:
            continue
        out.append(l)
    return out


def score_into_pool(cands, pool, seen_leads, limit, label):
    n_ok = n_try = 0
    window = [c for c in cands if c["email"] not in seen_leads][:limit * 3]
    queue = []
    with cf.ThreadPoolExecutor(16) as ex:
        verdicts = list(ex.map(C.prefilter, window))
    for c, ok in zip(window, verdicts):
        if ok:
            queue.append(c)
        else:
            seen_leads[c["email"]] = 1           # judged: rejected by the free filters
    queue = queue[:limit]
    with cf.ThreadPoolExecutor(8) as ex:
        for lead, s in zip(queue, ex.map(C.score, queue)):
            if s is None:
                continue                          # Jev unavailable: leave unjudged, retry next run
            seen_leads[lead["email"]] = 1
            n_try += 1
            if s["ok"]:
                lead.update({"score": s.get("score", round(sum(v for k, v in s.items() if k not in ("ok",)) / max(len(s) - 1, 1), 3)), "added": iso(), "via": label})
                pool.append(lead)
                n_ok += 1
    return n_try, n_ok


def refill(pool, seen_leads, sent_all, sup):
    avail = len(pool_unsent(pool, sent_all, sup))
    if avail >= MIN_POOL:
        return {"pool_available": avail, "action": "none"}
    info = {"pool_available_before": avail}
    seed = [r for r in C.seed_rows() if r["email"] not in sent_all and r["email"] not in seen_leads and r["email"].split("@")[1] not in sup["domains"]]
    if seed:
        t, ok = score_into_pool(seed, pool, seen_leads, SCORE_BATCH, "seed")
        info["seed_scored"], info["seed_added"] = t, ok
        if ok:
            return info
    # backlog exhausted or yielding nothing: harvest fresh leads from the web
    meta = st("meta", {})
    qs = C.harvest_queries()
    cur = meta.get("harvest_cursor", 0)
    fc = Firecrawl()
    found = []
    batch = [qs[(cur + i) % len(qs)] for i in range(HARVEST_PER_RUN)] if HARVEST_PER_RUN > 0 and qs else []
    if not batch:
        info["harvest"] = "disabled"
        return info
    with cf.ThreadPoolExecutor(min(len(batch), 8)) as ex:
        results = list(ex.map(lambda t: fc.search(t[0]), batch))
    for (qq, *rest), res in zip(batch, results):
        if res is None:
            info["harvest"] = "firecrawl unavailable"
            continue
        found += C.leads_from_results(res, *rest)
    meta["harvest_cursor"] = (cur + HARVEST_PER_RUN) % len(qs)
    found = [l for l in {l["email"]: l for l in found}.values() if l["email"] not in sent_all and l["email"] not in seen_leads and l["email"].split("@")[1] not in sup["domains"]]
    t, ok = score_into_pool(found, pool, seen_leads, SCORE_BATCH, "harvest")
    info["harvest_found"], info["harvest_scored"], info["harvest_added"] = len(found), t, ok
    return info


# ---------------- sending ----------------
def pick(avail, n, per_state_cap=18):
    avail = sorted(avail, key=lambda l: -l.get("score", 0))
    out, per, doms = [], collections.Counter(), set()
    for l in avail:
        s = l.get("state") or "?"
        rd = reg_domain(l["email"].split("@")[1])
        if per[s] >= per_state_cap or rd in doms:
            continue
        out.append(l)
        per[s] += 1
        doms.add(rd)
        if len(out) >= n:
            break
    return out


def send_batch(batch, inbox_key, per_inbox_today, sent_state):
    room = {i: max(0, INBOX_CAP - per_inbox_today.get(i, 0)) for i in inbox_key}
    order = sorted(inbox_key, key=lambda i: -room[i])
    used, parked, sent = collections.Counter(), set(), 0
    for lead in batch:
        ib = next((i for i in order if used[i] < room[i] and inbox_key[i] not in parked), None)
        if not ib:
            log("no inbox with room left")
            break
        subj, body = C.render(lead)
        if DRY:
            log("DRY", ib, "->", lead["email"], "|", subj)
            used[ib] += 1
            order.sort(key=lambda i: used[i])
            continue
        c, d = am(inbox_key[ib], "POST", f"/inboxes/{q(ib)}/messages/send", {"to": [lead["email"]], "subject": subj, "text": body})
        if c in (200, 201):
            sent += 1
            used[ib] += 1
            sent_state[lead["email"]] = {"inbox": ib, "ts": iso(), "state": lead.get("state")}
            log("SENT", ib, "->", lead["email"])
        elif c == 429:
            parked.add(inbox_key[ib])
            log("429 parked org", str(d)[:140])
        else:
            # 2026-11-01: a failed inbox was retried for every following lead (used[] not bumped).
            # Park the org for this run AND persist the inbox so future passes skip it.
            parked.add(inbox_key[ib]); used[ib] += 1
            _derr = str(d)
            if c == 403 and ("account_suspended" in _derr or "AccountSuspended" in _derr):
                _dl = st("dead_inboxes", [])
                if ib not in _dl:
                    _dl.append(ib); log("parking suspended inbox:", ib)
            log("ERR", c, ib, lead["email"], _derr[:140])
        order.sort(key=lambda i: used[i])
        time.sleep(random.uniform(20, 45))
    return sent


def digest(inbox_key, events_total):
    meta = st("meta", {})
    today = lday(iso())
    if now().hour < 5 or now().hour > 8 or meta.get("digest_day") == today:
        return                       # one digest a day, around 16:00-19:00 AU time
    sent = st("sent", {})
    n_today = sum(1 for v in sent.values() if lday(v["ts"]) == today)
    pool = st("pool", [])
    body = (f"{CAMP.upper()} daily digest {today}\nsent today (this engine): {n_today}\nsent all time (this engine): {len(sent)}\n"
            f"pool size: {len(pool)}\nsuppressed domains: {len(st('suppress', {}).get('domains', []))}\n"
            f"bounces recorded: {len(st('bounces', []))}\npaused: {json.dumps(st('paused', {}))}\ninbound events seen today: {dict(events_total)}")
    notify(inbox_key, f"[{CAMP.upper()}] daily digest {today}", body)
    meta["digest_day"] = today


# ---------------- main ----------------
def main():
    bootstrap()
    lock = open(P(".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another run holds the lock; exiting")
        return
    inbox_key = discover()
    log(f"{CAMP}: {len(inbox_key)} inboxes, {len(KEYS)} keys, DRY={DRY}")
    if not inbox_key:
        log("no inboxes found: check AGENTMAIL_KEYS")
        return
    sent_addrs, per_inbox_today, last48 = sent_ground_truth(inbox_key)
    sent_state = st("sent", {})
    sent_all = sent_addrs | set(sent_state) | C.seed_contacted()
    events = process_inbound(inbox_key, sent_addrs)
    sup = st("suppress", {"emails": [], "domains": []})
    pool, seen_leads = st("pool", []), st("seen", {})
    if MODE == "status":
        print(json.dumps({"pool": len(pool), "available": len(pool_unsent(pool, sent_all, sup)), "sent_engine": len(sent_state),
                          "sent_ground_truth": len(sent_addrs), "suppressed_domains": len(sup["domains"]), "bounces": len(st("bounces", [])),
                          "paused": st("paused", {}), "events": dict(events), "sent_today_by_inbox": dict(per_inbox_today)}, indent=1))
        flush()
        return
    if MODE == "prescore":
        target = int(E("PRESCORE_TARGET", "1500"))
        stale = 0
        while len(pool_unsent(pool, sent_all, sup)) < target and stale < 4:
            before = len(pool)
            info = refill(pool, seen_leads, sent_all, sup)
            log("prescore step:", json.dumps(info), "pool", len(pool))
            stale = stale + 1 if len(pool) == before else 0
            flush()
    refill_info = refill(pool, seen_leads, sent_all, sup) if MODE != "prescore" else {}
    log("refill:", json.dumps(refill_info))
    if E("RESET_PAUSE", "") == "1" and not st("meta", {}).get("reset_done"):
        # One-time reset of the guard state after inboxes were merged with another sender (its bounces were counted here).
        st("paused", {}).clear()
        st("bounces", []).clear()
        st("meta", {})["reset_done"] = iso()
        log("RESET_PAUSE applied once: cleared paused + bounces state")
    reason = guard(inbox_key, last48, set(sent_state))
    sent_today_total = sum(per_inbox_today.values())
    mine_today = sum(1 for v in sent_state.values() if lday(v["ts"]) == lday(iso()))
    if MODE == "prescore":
        flush()
        log("prescore done; pool", len(pool))
        return
    if reason:
        log("NOT SENDING:", reason)
        if not st("meta", {}).get("pause_notified") == reason:
            notify(inbox_key, f"[{CAMP.upper()}] sending paused", reason + "\nClear by deleting paused.json on the volume, or fix and set KILL_SWITCH=0.")
            st("meta", {})["pause_notified"] = reason
    elif not in_window() and not E("IGNORE_WINDOW", ""):
        log("outside the send window (AU business hours); not sending")
    else:
        n = min(MAX_RUN, DAILY_MAX - mine_today)
        avail = [l for l in pool_unsent(pool, sent_all, sup)]
        batch = pick(avail, n) if n > 0 else []
        log(f"sending {len(batch)} (mine today {mine_today}/{DAILY_MAX}; inbox cap {INBOX_CAP}; available {len(avail)})")
        send_batch(batch, inbox_key, per_inbox_today, sent_state)
    digest(inbox_key, events)
    flush()
    log("run complete")


if __name__ == "__main__":
    # 2026-11-01: this service has no cron schedule; without a loop the container exits after one
    # pass and throughput collapses to a handful of sends per deploy. Loop continuously.
    _interval = int(E("RUN_INTERVAL_SECONDS", "60"))
    if _interval <= 0:
        main()
    else:
        while True:
            try:
                main()
            except Exception as _e:
                log("pass crashed:", str(_e)[:300])
            time.sleep(_interval)
