#!/usr/bin/env python3
"""Outreach engine. One run (a Railway cron tick) does, in order:
   guard -> read inbound (bounces, complaints, removes, real replies) -> refill the lead pool -> send within caps -> daily digest.

   python3 run.py acd            normal run
   python3 run.py acd prescore   build the starting lead pool offline (used before the first deploy)
   python3 run.py acd status     print pool / sent / guard state

Environment: AGENTMAIL_KEYS (comma list), TYPESAFE_API_KEY (Jev), FIRECRAWL_KEYS (comma list), OWNER_EMAIL,
DATA_DIR, DRY_RUN, KILL_SWITCH, INBOX_DAILY_CAP, DAILY_MAX, MAX_PER_RUN, AU_OFFSET_HOURS, WINDOW (e.g. 9:00-16:30), WEEKDAYS_ONLY.
"""
import collections, concurrent.futures as cf, hashlib, importlib, json, os, random, re, socket, sys, time, fcntl, urllib.parse

# 2026-11-24: one socket read without a timeout hung the sender for eight hours. No call may block forever.
socket.setdefaulttimeout(45)
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
            # the API hands back an inbox_id UUID and the address; filters are written against the
            # address, so test both and key on the address (that is what the send path uses).
            iid = x.get("email") or x.get("inbox_id")
            hay = f"{x.get('email') or ''} {x.get('inbox_id') or ''}"
            if rx and not rx.search(hay):
                continue
            if rx_deny and rx_deny.search(hay):
                continue
            if st("limit_park", {}).get(iid) == lday(iso()):
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
    sup = _load_blocklist(st("suppress", {"emails": [], "domains": []}))
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
                    # 2026-11-02 owner order — hard full capacity, no self-holds: an old complaint
                    # sitting in the inbox re-paused the engine on every single pass. Only pause
                    # when the owner has not switched the kill-switch off for this service.
                    if E("DISABLE_COMPLAINT_PAUSE", "") == "1":
                        st("foreign_complaints", []).append({"ts": iso(), "inbox": iid, "original_subject": orig, "note": "pause disabled by env"})
                    else:
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
                # who stopped and how, so a multi-step campaign can end that lead's sequence
                st("stops", []).append({"f": f, "ts": ts, "hide": bool(re.search(r"\bhide\b", prev, re.I))})
                if dom and dom not in sup["domains"] and dom not in FREE_MAIL:
                    sup["domains"].append(dom)
                if f and f not in sup["emails"]:
                    sup["emails"].append(f)
            elif kind == "human":
                st("replies", []).append({"f": f, "ts": ts})
                _rl = st("reply_log", [])
                if not any(x.get("f") == f for x in _rl):
                    _rl.append({"f": f, "ts": ts})
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
        body = re.sub(r"[ \t]+", " ", str(full.get("extracted_text") or full.get("text") or "")) if c == 200 else ""
        # 2026-11-02: an Exchange auto-responder with Auto-Submitted: auto-generated and an empty body was
        # classified as a human reply, forwarded, AND answered — which fed a mail loop every 60 minutes.
        _hd = {str(a).lower(): str(b).lower() for a, b in ((full.get("headers") or {}) if c == 200 else {}).items()}
        if _hd.get("auto-submitted", "").startswith("auto") or "x-autoreply" in _hd or "x-autorespond" in _hd:
            fwd[mid] = "autoresponder-skipped"; continue
        if not body.strip():
            fwd[mid] = "empty-body-skipped"; continue
        # 2026-11-02 owner request: forward the FULL reply plus the original email we sent (thread context).
        _sent_orig = ""
        try:
            _sc, _sd = am(k, "GET", f"/inboxes/{q(iid)}/messages?labels=SENT&limit=50")
            if _sc == 200:
                _key = re.sub(r"^(re|fwd?):\s*", "", (subj or "").lower()).strip()[:40]
                _claimed = False
                for _m in (_sd.get("messages") or []):
                    _osub = re.sub(r"^(re|fwd?):\s*", "", str(_m.get("subject") or "").lower()).strip()
                    # 2026-11-02: fleet inboxes are shared by two campaigns — the first engine to forward
                    # a thread owns it. A forward is a SENT message to the owner tagged "[X reply] <base>";
                    # if one already exists for this base subject, this engine stays silent.
                    if _m2 := re.match(r"^\[\w[\w ]*\s+reply\]\s+(.+)$", str(_m.get("subject") or ""), re.I):
                        if _key and re.sub(r"^(re|fwd?):\s*", "", _m2.group(1)).lower().strip()[:40] == _key:
                            fwd[mid] = "claimed-by-other-campaign"
                            _claimed = True
                            break
                    if _key and _osub[:40] == _key and not _sent_orig:
                        _mid_o = _m.get("message_id") or _m.get("id")
                        _oc, _of = am(k, "GET", f"/inboxes/{q(iid)}/messages/{q(_mid_o)}")
                        if _oc == 200:
                            _sent_orig = re.sub(r"[ \t]+", " ", str(_of.get("extracted_text") or _of.get("text") or ""))
                        if not _sent_orig:
                            _sent_orig = str(_m.get("preview") or "")
                if _claimed:
                    continue
        except Exception as _e:
            _sent_orig = "(original not found: %s)" % str(_e)[:60]
        _noise = ('firecrawl','apify','tinyfish','stripe.com','shopify.com','vercel.com','github.com','openai.com',
                  'substack','intercom-mail','notifications.','no-reply','noreply','newsletter','mailchimp','sendgrid',
                  'google.com','microsoft.com','beehiiv','convertkit','hubspot','zapier','canva.com','linkedin.com')
        if any(n in (f + ' ' + subj).lower() for n in _noise):
            fwd[mid] = "noise-skipped"; continue
        if not _sent_orig:
            fwd[mid] = "no-original-skipped"; continue
        if len([x for x in fwd.values() if str(x).startswith("2026")]) >= 25:
            continue
        notify(inbox_key, f"[{CAMP.upper()} reply] {subj[:70]}",
               f"From: {f}\nTo inbox: {iid}\nReceived: {ts}\nThread: reply from the same inbox to continue (the engine does NOT auto-reply to people).\n\n"
               f"=== THEIR REPLY (full) ===\n{body}\n\n=== WHAT WE SENT THEM ===\n{_sent_orig}")
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
        if E("DISABLE_COMPLAINT_PAUSE", "") == "1":
            # 2026-11-02: owner order — hard full capacity. A complaint object persisted on the
            # volume kept this engine paused forever; clear it and keep sending.
            paused.pop("complaint", None)
            st("paused", paused)
        else:
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
HOLD_EXEMPT = {x.strip().lower() for x in os.environ.get("HOLD_EXEMPT", "").split(",") if x.strip()}   # emails released early (pool rows that lost their batch tag)


def today_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def pool_unsent(pool, sent_all, sup):
    """Leads we may still mail: not sent, not suppressed, and no address at the same organisation already mailed."""
    mailed_domains = {reg_domain(a.split("@")[1]) for a in sent_all if "@" in a}
    out = []
    for l in pool:
        e = l["email"]
        d = e.split("@")[1]
        if (l.get("state") or "") in ("blocked", "bounced"):
            continue
        if (l.get("not_before") or "") > today_utc():      # held lead: released on its date (YYYY-MM-DD)
            continue
        # 2026-11-06: owner's call. Freshly minted, Jev-ranked leads carry a "batch" tag and go first; everything that
        # was already in the pool is held until HOLD_LEGACY_UNTIL (YYYY-MM-DD, UTC), then released automatically.
        _hold = os.environ.get("HOLD_LEGACY_UNTIL", "").strip()
        if _hold and today_utc() < _hold and not l.get("batch") and e.lower() not in HOLD_EXEMPT:
            continue
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


def _load_blocklist(sup):
    """Domains that must never be mailed again (loops, legal threats, brand collisions).
    Lives in the image because state on this volume is ephemeral and got wiped every deploy."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blocked_domains.txt")
    try:
        for line in open(p):
            d = line.split("#")[0].strip().lower()
            if d and d not in sup["domains"]:
                sup["domains"].append(d)
    except Exception:
        pass
    return sup


def refill(pool, seen_leads, sent_all, sup):
    avail = len(pool_unsent(pool, sent_all, sup))
    if avail >= MIN_POOL:
        return {"pool_available": avail, "action": "none"}
    info = {"pool_available_before": avail}
    seed = [r for r in C.seed_rows() if r["email"] not in sent_all and r["email"] not in seen_leads and r["email"].split("@")[1] not in sup["domains"]]
    # 2026-11-02: Jev scoring inside the container kept returning unavailable, so the pool never grew
    # while pre-scored leads sat unused. Rows flagged preverified skip the gate entirely.
    pre = [r for r in seed if r.get("preverified")]
    for r in pre:
        seen_leads[r["email"]] = 1
        pool.append(dict(r, state=r.get("state") or ""))
    if pre:
        info["preverified_added"] = len(pre)
        seed = [r for r in seed if not r.get("preverified")]
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
    room = {}
    for i in inbox_key:
        room[i] = _om_room(om[i]) if i in om else max(0, INBOX_CAP - per_inbox_today.get(i, 0))
    _pref = E("PREFER_INBOX_REGEX", "")
    _prx = __import__("re").compile(_pref) if _pref else None
    order = sorted(inbox_key, key=lambda i: (0 if (_prx and _prx.search(i)) else 1, -room[i]))
    used, parked, sent = collections.Counter(), set(), 0
    for lead in batch:
        # follow-ups have to go out from the inbox that opened the thread, so omail only takes step 1
        cands = [i for i in order if (i not in om) or step == 1]
        ib = next((i for i in cands if used[i] < room[i] and inbox_key[i] not in parked), None)
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
            sent_state[lead["email"]] = {"inbox": ib, "ts": iso(), "state": lead.get("state"), "arm": lead.get("_arm")}
            # Arm log: append-only JSONL, one row per send, so arm rates can be read back without the API.
            try:
                with open(P("arm_log.jsonl"), "a") as _f:
                    _f.write(json.dumps({"ts": iso(), "em": lead["email"], "arm": lead.get("_arm"),
                                         "subj": subj[:120], "inbox": ib}) + "\n")
            except Exception:
                pass
            log("SENT", ib, "->", lead["email"], "arm=" + (lead.get("_arm") or "?"))
        elif c == 429:
            parked.add(inbox_key[ib])
            log("429 parked org", str(d)[:140])
        else:
            # 2026-11-01: a failed inbox was retried for every following lead (used[] not bumped).
            # Park the org for this run AND persist the inbox so future passes skip it.
            parked.add(inbox_key[ib]); used[ib] += 1
            _derr = str(d)
            # 2026-11-02: an unretryable target (bad address, blocked domain) was retried every pass and
            # starved the queue. Two strikes and the lead is parked for good.
            if c in (400, 403, 404, 422, 451, 550, 551, 553):
                _tries = int(lead.get("tries") or 0) + 1
                lead["tries"] = _tries
                # 2026-11-04: "Recipient(s) blocked" is ORG-specific — the same address often sends
                # fine from another org. Never insta-block on it; let the normal 2-strike rule decide.
                if _tries >= 2:
                    lead["state"] = "blocked"
                    log("BLOCKED lead after", _tries, "tries:", lead["email"], _derr[:100])
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
    if CAMP == "tw1000":
        return tw_main()
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
    _before = len(leads)
    leads = [l for l in leads if l["email"] not in sent_addrs]
    if len(leads) != _before:
        log("dedupe: dropped", _before - len(leads), "leads already contacted from these inboxes")
    sent_state = st("sent", {})
    sent_all = sent_addrs | set(sent_state) | C.seed_contacted()
    events = process_inbound(inbox_key, sent_addrs)
    sup = _load_blocklist(st("suppress", {"emails": [], "domains": []}))
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


# ============================== tw1000: multi-step campaign ==============================
# Playbook docs/tw1000-playbook.md §10.1. Separate flow from the single-step pool engine used by
# acd/bc/nm: tw1000 sends a fixed 4-step sequence per lead, so what it needs is per-lead progress,
# a due-step queue, threading and a step-1 daily ramp — not a refilling pool.

STEPS = {"1": 0, "2": 3, "3": 7, "4": 14}
THREADED = ("2", "4")            # steps whose subject starts "Re:" and must continue the step-1 thread
RAMP = ((3, 45), (6, 90), (10 ** 6, 120))   # campaign day -> step-1 sends per day (playbook §5)
STATE_TZ = {"NSW": 11, "VIC": 11, "TAS": 11, "ACT": 11, "QLD": 10, "SA": 10.5, "NT": 9.5, "WA": 8}


def _local_now(state):
    return dt.datetime.utcnow() + dt.timedelta(hours=STATE_TZ.get((state or "").upper(), 10))


def _in_window(state):
    t = _local_now(state)
    if t.weekday() not in (1, 2, 3):          # Tue-Thu only
        return False
    return (7, 30) <= (t.hour, t.minute) <= (10, 30)


def _campaign_day(progress):
    firsts = [p.get("t1") for p in progress.values() if p.get("t1")]
    if not firsts:
        return 1
    try:
        return (dt.date.today() - dt.date.fromisoformat(min(firsts)[:10])).days + 1
    except Exception:
        return 1


def _step1_cap(progress):
    override = E("STEP1_CAP", "")
    if override:
        return int(override)
    d = _campaign_day(progress)
    for limit_day, per_day in RAMP:
        if d <= limit_day:
            return per_day
    return 120


def _tw_log(row):
    try:
        with open(P("tw1000_sends.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def _tw_stop(email, reason, progress, sup, lead=None):
    p = progress.setdefault(email, {})
    p["stopped"] = reason
    p["stopped_ts"] = iso()
    if email not in sup["emails"]:
        sup["emails"].append(email)
    if reason == "hide" and lead and lead.get("profile_id"):
        _tw_hide(lead["profile_id"])
    log("STOP", email, reason)


def _tw_hide(profile_id):
    """playbook §6: a 'hide' reply hides the directory listing the same day."""
    base = E("SUPABASE_URL", "")
    key = E("SUPABASE_SECRET_KEY", "") or E("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        log("hide: no SUPABASE_URL/SUPABASE_SECRET_KEY; profile", profile_id, "not updated")
        return
    c, d = http("PATCH", f"{base}/rest/v1/vula_sub_profiles?id=eq.{profile_id}",
                {"status": "hidden"}, {"apikey": key, "Authorization": "Bearer " + key,
                                       "Content-Type": "application/json", "Prefer": "return=minimal"})
    log("hide profile", profile_id, c)


def _tw_strand(protocol_name, since_hours=14):
    """(email -> first classified reply) so a reply strand stops the sequence before we send again."""
    seen = st("inbound_seen", {})
    cut = (now() - dt.timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    return {mid: k for mid, k in seen.items() if False} or {}



# ---------------------------- OpenMail transport (TenderWin-branded inboxes) ----------------------------
# Owner order 2026-11-20: cold mail goes from TenderWin or generic-brand mailboxes. AgentMail's only
# TenderWin org is capped at 100 recipients a day, so the omail.sh TenderWin inboxes carry first-touch
# sends. Plain text only (step 1/3/4); the designed HTML card stays on AgentMail.
def _om_senders():
    try:
        return {s["address"]: s for s in json.loads(E("OPENMAIL_SENDERS", "[]") or "[]")}
    except Exception:
        return {}


def _om_room(snd):
    """Remaining cold contacts for this account today, straight from the provider."""
    c, d = http("GET", "https://api.openmail.sh/v1/limits/cold", None,
                {"Authorization": "Bearer " + snd["key"], "User-Agent": "Mozilla/5.0 Chrome/141.0"})
    try:
        acc = (d or {}).get("account") or {}
        return max(0, int(acc.get("remaining") or 0))
    except Exception:
        return 0


def _om_send(snd, to, subject, text):
    body = {"to": to, "subject": subject, "body": text}
    return http("POST", f"https://api.openmail.sh/v1/inboxes/{snd['id']}/send", body,
                {"Authorization": "Bearer " + snd["key"], "User-Agent": "Mozilla/5.0 Chrome/141.0",
                 "Content-Type": "application/json"})


def tw_main():
    bootstrap()
    lock = open(P(".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another run holds the lock; exiting")
        return
    sender = E("SENDER_NAME", "") or C.SENDER_NAME
    inbox_key = discover()
    om = _om_senders()
    for a in om:
        inbox_key.setdefault(a, "om")
    log(f"tw1000: {len(inbox_key)} inboxes, DRY={DRY}, sender={sender}")
    if not inbox_key:
        log("no inboxes found: check AGENTMAIL_KEYS")
        return
    leads = C.seed_rows()
    # harvested emails can arrive wrapped ("<info@x.com>") or with stray spaces
    clean = []
    for l in leads:
        e = re.sub(r"[<>\s\"']", "", str(l.get("email") or "")).lower()
        if "@" in e and "." in e.split("@")[-1]:
            l["email"] = e
            clean.append(l)
    leads = clean
    progress = st("progress", {})
    if not leads:
        log("no seed leads: seed/tw1000_leads.json missing")
        return
    for l in leads:                                        # arm is stable, never reassigned
        p = progress.setdefault(l["email"], {})
        p.setdefault("arm", C.arm_for(l["email"]))
        l["_arm"] = p["arm"]
    split = collections.Counter(l["_arm"] for l in leads)
    log("seed", len(leads), "arms", dict(split))

    sent_addrs, per_inbox_today, last48 = sent_ground_truth(inbox_key)
    _before = len(leads)
    leads = [l for l in leads if l["email"] not in sent_addrs]
    if len(leads) != _before:
        log("dedupe: dropped", _before - len(leads), "leads already contacted from these inboxes")
    st("sent", {})                                     # shared key names kept for guard/digest
    sup = _load_blocklist(st("suppress", {"emails": [], "domains": []}))
    events = process_inbound(inbox_key, sent_addrs)

    # a reply of any kind, or a stop, ends the sequence for that address (playbook §3)
    seed_addrs = {l["email"].lower() for l in leads}
    for x in st("reply_log", []):
        em = (x.get("f") or "").lower()
        if em in seed_addrs and not progress.get(em, {}).get("stopped"):
            _tw_stop(em, "replied", progress, sup)
    for em in [a.strip().lower() for a in E("STOP_LIST", "").split(",") if a.strip()]:
        if not progress.get(em, {}).get("stopped"):
            _tw_stop(em, "operator", progress, sup)
    for r in st("replies", []):
        em = (r.get("f") or "").lower()
        if em in seed_addrs and not progress.get(em, {}).get("stopped"):
            _tw_stop(em, "replied", progress, sup)
    for s_ in st("stops", []):
        em = (s_.get("f") or "").lower()
        if em in seed_addrs and progress.get(em, {}).get("stopped") != "hide":
            lead = next((l for l in leads if l["email"].lower() == em), None)
            _tw_stop(em, "hide" if s_.get("hide") else "remove", progress, sup, lead)
    st("replies", []).clear()
    st("stops", []).clear()

    if MODE == "status":
        done = collections.Counter(p.get("s", 0) for p in progress.values())
        due = sum(1 for l in leads if _tw_due(l["email"], progress) )
        print(json.dumps({"leads": len(leads), "arms": dict(split), "by_last_step": done,
                          "stopped": sum(1 for p in progress.values() if p.get("stopped")),
                          "campaign_day": _campaign_day(progress), "step1_cap_today": _step1_cap(progress),
                          "due_now": due, "sent_today": dict(per_inbox_today),
                          "paused": st("paused", {})}, indent=1))
        flush()
        return

    reason = guard(inbox_key, last48, set())
    if reason:
        log("NOT SENDING:", reason)
        flush()
        return

    step1_today = sum(1 for p in progress.values() if str(p.get("t1") or "")[:10] == iso()[:10])
    cap1 = _step1_cap(progress)
    room = {}
    for i in inbox_key:
        room[i] = _om_room(om[i]) if i in om else max(0, INBOX_CAP - per_inbox_today.get(i, 0))
    queue = []
    for l in leads:
        em = l["email"]
        p = progress[em]
        if p.get("stopped") and not str(p["stopped"]).startswith("skip:"):
            continue
        step = _tw_due(em, progress)
        if not step:
            continue
        if step == 1 and step1_today >= cap1:
            continue
        if not _in_window(l.get("state")) and not E("IGNORE_WINDOW", ""):
            continue
        queue.append((l, step))
    # keep the day's strongest leads, then interleave arms so no arm gets a better inbox or hour
    queue.sort(key=lambda x: -float(x[0].get("_score") or 0))
    _band = queue[: max(24, min(len(queue), MAX_RUN * DAILY_MAX))]
    _band.sort(key=lambda x: hashlib.sha1(x[0]["email"].encode()).hexdigest())
    queue = _band
    # skips do not consume an inbox slot, so the queue is over-filled: a lead that cannot render for
    # its arm is dropped at send time rather than eating one of the day's sends.
    budget = min(MAX_RUN, DAILY_MAX)
    # a lead that cannot render costs a second, not a send: keep trying until the day's budget is met
    queue = queue[: max(budget * 2, int(E("QUEUE_ATTEMPTS", "600")))]
    log(f"queue {len(queue)} (step1 today {step1_today}/{cap1}, inbox cap {INBOX_CAP}, inboxes {len(inbox_key)})")
    if not queue:
        digest(inbox_key, events)
        flush()
        return

    _pref = E("PREFER_INBOX_REGEX", "")
    _prx = __import__("re").compile(_pref) if _pref else None
    order = sorted(inbox_key, key=lambda i: (0 if (_prx and _prx.search(i)) else 1, -room[i]))
    used, parked, sent = collections.Counter(), set(), 0
    for lead, step in queue:
        # follow-ups have to go out from the inbox that opened the thread, so omail only takes step 1
        cands = [i for i in order if (i not in om) or step == 1]
        ib = next((i for i in cands if used[i] < room[i] and inbox_key[i] not in parked), None)
        if not ib:
            log("no inbox with room left")
            break
        em, arm = lead["email"], lead["_arm"]
        r, used_arm = None, arm
        for cand in (arm, *[a for a in "BAC" if a != arm]):
            try:
                lead["_arm"] = cand
                r = C.render_step(lead, step, C.trade_rx_for(lead.get("trade")), sender)
                used_arm = cand
                break
            except ValueError as e:
                last = e
        lead["_arm"] = arm
        if r is None:
            # two honest attempts is enough: a lead with no evidence today is retried once the feed
            # refreshes, not on every pass for the rest of the campaign
            tries = int(progress[em].get("skips") or 0) + 1
            progress[em]["skips"] = tries
            log("skip", em, f"arm {arm} step {step}: all arms short of evidence ({last}) [try {tries}]")
            progress[em]["stopped"] = (f"skip-final:{last}" if tries >= 2 else f"skip:{last}")
            continue
        if used_arm != arm:
            log("fallback", em, f"{arm}->{used_arm} step {step}")
        if str(progress[em].get("stopped") or "").startswith("skip:"):
            progress[em].pop("stopped", None)
        subj = r["subject"]
        if DRY:
            log("DRY", ib, f"{arm}{step}", "->", em, "|", subj)
            used[ib] += 1
            if step == 1:
                step1_today += 1
            order.sort(key=lambda i: used[i])
            continue
        k = inbox_key[ib]
        if ib in om:
            c, d = _om_send(om[ib], em, subj, r["text"])
            if c in (200, 201):
                sent += 1
                used[ib] += 1
                progress[em].update({"s": 1, "ts1": iso(), "ib1": ib, "t1": iso(),
                                     "m1": d.get("messageId") or d.get("threadId")})
                step1_today += 1
                _tw_log({"ts": iso(), "em": em, "arm": used_arm, "arm_assigned": arm, "step": 1,
                         "subj": subj[:120], "inbox": ib, "mid": d.get("messageId"), "transport": "openmail"})
                log("SENT", ib, f"{arm}{step}", "->", em, "|", subj)
            elif c in (429, 402) or "limit" in str(d).lower():
                used[ib] = room[ib]
                log("LIMIT", ib, c, str(d)[:90])
            else:
                used[ib] += 1
                log("ERR", c, ib, em, str(d)[:140])
            order.sort(key=lambda i: used[i])
            time.sleep(random.uniform(float(E("SEND_GAP_MIN", "15")), float(E("SEND_GAP_MAX", "35"))))
            continue
        payload = {"to": [em], "text": r["text"]}
        if r.get("html"):
            payload["html"] = r["html"]
        mid1 = (progress[em].get("m1") or "")
        if str(step) in THREADED and mid1:
            path = f"/inboxes/{q(ib)}/messages/{urllib.parse.quote(mid1, safe='')}/reply"
            c, d = am(k, "POST", path, payload)
        else:
            c, d = am(k, "POST", f"/inboxes/{q(ib)}/messages/send", dict(payload, subject=subj))
        if c in (200, 201):
            sent += 1
            used[ib] += 1
            mid = d.get("message_id") or d.get("id")
            p = progress[em]
            p["s"] = step
            p["ts" + str(step)] = iso()
            p["ib" + str(step)] = ib
            if step == 1:
                p["t1"] = iso()
                p["m1"] = mid
                step1_today += 1
            else:
                p.setdefault("follow", []).append(step)
            _tw_log({"ts": iso(), "em": em, "arm": used_arm, "arm_assigned": arm, "step": step,
                     "subj": subj[:120], "inbox": ib, "mid": mid})
            log("SENT", ib, f"{arm}{step}", "->", em, "|", subj)
        elif c == 429 or c == 402 or "limit" in str(d).lower():
            parked.add(k)
            st("limit_park", {})[ib] = lday(iso())
            log("LIMIT parked", ib, c, str(d)[:90])
        else:
            parked.add(k)
            used[ib] += 1
            # same two-strike rule as the shared path: a target that rejects on every org stops eating a slot
            if c in (400, 403, 404, 422, 451, 550, 551, 553):
                p_try = int(progress[em].get("tries") or 0) + 1
                progress[em]["tries"] = p_try
                if p_try >= 2:
                    progress[em]["stopped"] = f"blocked:{c}"
                    log("BLOCKED lead after", p_try, "tries:", em, str(d)[:80])
            log("ERR", c, ib, em, str(d)[:140])
        order.sort(key=lambda i: used[i])
        time.sleep(random.uniform(float(E("SEND_GAP_MIN", "15")), float(E("SEND_GAP_MAX", "35"))))
    log("tw1000 run complete:", sent, "sent")
    digest(inbox_key, events)
    flush()


def _tw_due(email, progress):
    """Next step number that is due for this lead, or 0. Days are offsets from step 1 (playbook §3)."""
    p = progress.get(email) or {}
    if p.get("stopped") and not str(p["stopped"]).startswith("skip:"):
        return 0
    last = int(p.get("s") or 0)
    if last >= 4:
        return 0
    nxt = last + 1
    if nxt == 1:
        return 1
    t1 = p.get("t1")
    if not t1:
        return 1
    try:
        due = dt.date.fromisoformat(t1[:10]) + dt.timedelta(days=STEPS[str(nxt)])
    except Exception:
        return nxt
    return nxt if dt.date.today() >= due else 0


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
