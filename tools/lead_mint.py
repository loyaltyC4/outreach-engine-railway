#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lead_mint.py - mint a Jev-ranked month of leads for the four campaigns (TenderWin, BidCheck, NameMarshal, ACD).

Resumable, checkpointed, no sending. Stages (each reads/writes ~/AutoClaw/Shared/leadgen/mint-20261105/cache):
  contacted   every address already mailed (AgentMail sent folders, 90 days + ledgers) -> dedupe base
  build       existing pools + harvested candidates -> free hard gates (syntax, free-mail, gov/edu, big brands,
              contacted, trade, dead MX) -> cache/cands.jsonl
  harvest     NEW leads: AusTender award winners (public OCDS API) + search harvests via TinyFish (free tier)
  enrich      TinyFish fetch of each site: real name, phones, country evidence, own-domain emails
  resolve     repair names, upgrade role inboxes to named owners, country gate (two signals), pick one email/domain
  score       Jev (the engines' own scorers) on every resolved lead
  export      rank, cross-campaign domain uniqueness, staging jsonl, engine feeds, report, backup

  python3 tools/lead_mint.py status
  python3 tools/lead_mint.py contacted|build|harvest|enrich|resolve|score|export [--limit N]
  python3 tools/lead_mint.py all
Never prints keys. Never calls AgentMail send. Never touches sender settings."""
import collections, csv, difflib, html, json, os, random, re, sys, threading, time
import datetime as dt
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
DAY = "20261105"
WORK = HOME / "AutoClaw/Shared/leadgen/mint-20261105"
CACHE, LOGS = WORK / "cache", WORK / "logs"
STAGING = HOME / "AutoClaw/Shared/leadgen/staging"
for _d in (CACHE, LOGS, STAGING):
    _d.mkdir(parents=True, exist_ok=True)
NOW = dt.datetime.utcnow()
CAMPS = ("tw", "bc", "nm", "acd")


def log(*a):
    line = "[%s] %s" % (dt.datetime.utcnow().strftime("%H:%M:%S"), " ".join(str(x) for x in a))
    print(line, flush=True)
    with open(LOGS / "mint.log", "a") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------ env (never printed)
ENV = {}
for _line in open(HOME / "AutoClaw/Shared/.secrets/keys.env", errors="ignore"):
    _m = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(['\"]?)([^'\"\s#]*)\2", _line)
    if _m:
        ENV[_m.group(1)] = _m.group(3)
for _k in ("TYPESAFE_API_KEYS", "TYPESAFE_API_KEY", "TINYFISH_KEYS"):
    if ENV.get(_k):
        os.environ[_k] = ENV[_k]
os.environ.setdefault("SEED_DIR", str(REPO / "seed"))
import util  # noqa: E402  (needs the env above)
from util import reg_domain as rd  # noqa: E402


# ------------------------------------------------------------------ small helpers
def jl_read(path):
    out = []
    try:
        with open(path) as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return out


_wlock = threading.Lock()


def jl_append(path, obj):
    with _wlock:
        with open(path, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def jread(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def jwrite(path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


EMAIL_RX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
VALID_RX = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$")
BAD_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js|ico|pdf|woff2?)$", re.I)
PLACEHOLDER = re.compile(r"^(example|test|sample|yourname|your-?email|name|email|user|username|domain|john\.?doe|jane\.?doe)@|@(example|domain|email|yourdomain|sentry|wixpress|godaddy|squarespace|mysite)\.", re.I)


def norm_email(e):
    e = re.sub(r"^(?:%[0-9a-fA-F]{2})+", "", str(e or "")).strip().strip(".,;:<>()[]\"'").lower()
    e = re.sub(r"\+[^@]*@", "@", e)
    return e


def email_ok(e):
    return bool(VALID_RX.match(e)) and not BAD_EXT.search(e) and not PLACEHOLDER.search(e)


FREEMAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.com.au", "yahoo.co.jp", "ymail.com", "hotmail.com", "hotmail.com.au", "outlook.com", "outlook.com.au",
            "live.com", "live.com.au", "msn.com", "icloud.com", "me.com", "aol.com", "bigpond.com", "bigpond.net.au", "optusnet.com.au", "iinet.net.au", "tpg.com.au",
            "webmail.co.za", "mweb.co.za", "telkomsa.net", "vodamail.co.za", "polka.co.za", "proton.me", "protonmail.com", "qq.com", "163.com", "naver.com",
            "docomo.ne.jp", "ezweb.ne.jp", "softbank.ne.jp", "i.softbank.jp", "ocn.ne.jp", "nifty.com", "biglobe.ne.jp", "excite.co.jp", "gmx.com", "mail.com", "zoho.com"}
GOVEDU = re.compile(r"(^|\.)(gov|edu|mil)(\.|$)|\.ac\.[a-z]{2}$|\.govt\.|\.sch\.|\.school\.|\.go\.jp$|\.lg\.jp$|\.ed\.jp$|\.ac\.jp$|\.nhs\.uk$|^(council|parliament)\.", re.I)
BIG_RX = re.compile(r"\b(deloitte|kpmg|pwc|ernst|accenture|ibm|microsoft|oracle|telstra|optus|boeing|lockheed|bae systems|thales|serco|downer|cimic|cpb contractors|lendlease|ventia|"
                    r"transurban|amazon|google|salesforce|servicenow|capgemini|infosys|tata|cisco|dell|hewlett|fujitsu|unisys|eskom|transnet|sasol|vodacom|mtn|standard bank|absa|"
                    r"nedbank|firstrand|old mutual|sanlam|bidvest|shoprite|pick n pay|woolworths|coles|bunnings|officeworks|jb hi-fi|myer|rakuten|uniqlo|muji|sony|panasonic|toyota|honda|"
                    r"hitachi|toshiba|softbank|emaar|majid al futtaim|dubai holding|etisalat|du telecom|"
                    r"department of|ministry|municipal|municipality|council|shire|city of|university|college|tafe|hospital|health service|local health|health network|library|school|"
                    r"police|fire (and|&) rescue|authority|commission|parliament|government|commonwealth|crown|defence)\b", re.I)
JUNK_NAME = re.compile(r"^(privacy|contact|home|welcome|about|terms|cookie|login|log in|sign|menu|search|404|error|untitled|index|gov pty|com pty|net pty|org pty|au pty|co pty|"
                       r"skip to|main menu|navigation|page not found|just a moment|attention required|access denied|forbidden|coming soon|under construction)|"
                       r"privacy policy|terms (of|and)|contact (us|info|information|details)|about (us|this site)|cookie|\b(com|net|org|gov|edu|co)\b pty|^[\W\d_]+$|"
                       r"default web site|wordpress|wix\.com|godaddy|domain (name )?(for sale|parked)|\b(nbsp|amp)\b", re.I)
NOISE_DOMAINS = re.compile(r"(paintnite|terminal49|elpdata|subser|kayiseit|nordgreen|buyandship|carawayhome|sentry|wixpress|squarespace|godaddy|shopify\.com$|wordpress|cloudflare|"
                           r"linkedin|facebook|instagram|twitter|youtube|tiktok|pinterest|yelp|yellowpages|truelocal|hotfrog|oneflare|localsearch|startlocal|whitepages|brabys|"
                           r"tenders\.gov|austender|etenders|tendersa|abr\.business|opencorporates|dnb\.com|zoominfo|crunchbase|indeed|seek\.com|glassdoor|reddit|wikipedia|"
                           r"ebay\.|amazon\.|rakuten|mercari|yahoo\.co\.jp|booking\.com|tripadvisor|airbnb|trustpilot|google\.|bing\.|apple\.com|microsoft\.)", re.I)
ROLE = set("""info support sales contact contactus enquiries enquiry office admin administration hello hi team help customer customercare customerservice service services reception frontdesk
hr jobs careers recruit recruitment accounts accounting billing invoices payroll finance legal compliance privacy dpo press media pr marketing newsletter news comms outreach affiliates
affiliate partnership partnerships wholesale b2b returns refunds shipping delivery logistics warehouse dispatch orders order noreply no-reply donotreply unsubscribe abuse dmca security
webmaster postmaster mailer-daemon test demo example mail enq bookings booking reservations studio shop store feedback complaints general mailbox email enquire query queries quotes quote
estimating estimates projects operations ops sales2 service2 hello2 website web design internet cs""".split())
ROLE_OK = {"tw": {"tenders", "tender", "bids", "bid", "estimating", "estimates", "contracts", "procurement", "quotes", "quote", "projects", "operations", "office", "admin", "info", "hello"},
           "bc": {"tenders", "tender", "bids", "bid", "estimating", "contracts", "procurement", "quotes", "quote", "projects", "operations"},
           "nm": set(), "acd": {"intake", "referrals", "referral", "admissions", "coordinator", "clientservices", "enquiries", "enquiry", "info", "hello", "admin", "office"}}
# role inboxes that are acceptable ONLY for a micro business (site says owner/family/small team) - enforced in resolve()
MICRO_OK = {"info", "hello", "office", "admin", "enquiries", "enquiry", "contact", "mail", "team", "hi"}


DEPT = set("""acquisition acquisitions view views events event sponsorship donations donate fundraising volunteer volunteers community client clients member members membership customer
tenders design web website digital creative production publishing editor editorial research student students alumni library admissions admission nsw qld vic tas act au aus sa wa nt
reception booking bookings bookkeeping tax property lettings leasing rentals sales2 sales3 service2 careers2 hello2 inquiry inquiries query feedback complaints compliance safety whs ohs
quality environment sustainability procurement purchasing buyer buyers supplier suppliers vendor vendors creditors debtors credit collections claims quotes team1 team2 staff all everyone
general main head hq director directors management manager managers board secretary registrar clinic clinics practice surgery centre center depot warehouse store shop online ecommerce
shopify wholesale retail trade trades enquiries enquire intake referrals referral coordinator clientservices melbourne sydney brisbane perth adelaide canberra hobart darwin geelong newcastle wollongong goldcoast cairns townsville johannesburg pretoria durban capetown tokyo osaka dubai abudhabi sharjah traffic plumbing electrical cleaning landscaping painting roofing welding hire rental rentals fleet courier freight parts spares workshop service servicing repairs repair install installs""".split())
BUSINESS_WORD = {"care", "nursing", "plumbing", "electrical", "cleaning", "security", "construction", "group", "solutions", "enterprises", "trading", "projects", "building", "services",
                 "painting", "roofing", "landscaping", "maintenance", "engineering", "consulting", "logistics", "transport", "catering", "pest", "hvac", "mechanical"}


def local_kind(email, camp):
    """named | role_ok | role. 'named' means the local part looks like a person (first, first.last, initial+surname)."""
    local = email.split("@")[0].lower()
    core = re.sub(r"[^a-z]", "", local)
    toks = [t for t in re.split(r"[._\-]+", local) if t]
    if core in ROLE_OK[camp] and core not in {"info", "hello", "admin", "office"}:
        return "role_ok"
    if core in ROLE or core in MICRO_OK or core in DEPT or core in BUSINESS_WORD or len(core) < 3:
        return "role"
    if any(t in DEPT or t in ROLE or t in BUSINESS_WORD or t in ("sa", "nsw", "qld", "vic", "wa", "tas", "act", "nt", "au") for t in toks):
        return "role"
    if len(toks) == 1 and re.fullmatch(r"[a-z]{3,10}", toks[0]):
        return "named"                                   # first name or initial+surname (jsmith, sarah)
    if len(toks) == 2 and all(re.fullmatch(r"[a-z]{2,15}", t) for t in toks):
        return "named"                                   # sarah.jones / sarah_jones / sarah-jones
    if len(toks) == 2 and re.fullmatch(r"[a-z]", toks[0]) and re.fullmatch(r"[a-z]{3,15}", toks[1]):
        return "named"                                   # j.smith
    return "role"


# ------------------------------------------------------------------ country / state
STATE_BY_CITY = {"sydney": "NSW", "newcastle": "NSW", "wollongong": "NSW", "parramatta": "NSW", "melbourne": "VIC", "geelong": "VIC", "ballarat": "VIC", "bendigo": "VIC", "brisbane": "QLD",
                 "gold coast": "QLD", "townsville": "QLD", "cairns": "QLD", "toowoomba": "QLD", "sunshine coast": "QLD", "perth": "WA", "adelaide": "SA", "hobart": "TAS", "launceston": "TAS",
                 "darwin": "NT", "canberra": "ACT"}
AU_STATES = {"NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"}
ZA_PROV = ["Gauteng", "KwaZulu-Natal", "Western Cape", "Eastern Cape", "Free State", "Limpopo", "Mpumalanga", "North West", "Northern Cape"]


def norm_state(v):
    s = str(v or "").strip()
    if s.upper() in AU_STATES:
        return s.upper()
    return STATE_BY_CITY.get(s.lower(), s if s in ZA_PROV else "")


MARK = {
    "AU": re.compile(r"\bABN\b|\bAustralia(n)?\b|\+61|\(0[2-478]\)\s?\d{4}|\b(NSW|VIC|QLD|SA|WA|TAS|ACT|NT)\s+\d{4}\b|\b(Sydney|Melbourne|Brisbane|Perth|Adelaide|Canberra|Hobart|Darwin)\b", re.I),
    "ZA": re.compile(r"South Africa|\+27|\(0\d{2}\)\s?\d{3}\s?\d{4}|\b(Gauteng|KwaZulu|Western Cape|Johannesburg|Pretoria|Cape Town|Durban|Bloemfontein|Polokwane|Mpumalanga)\b|\bCSD\b|B-?BBEE|\bCIDB\b|\(Pty\)", re.I),
    "JP": re.compile(r"Japan|\+81|〒|\b(Tokyo|Osaka|Kyoto|Yokohama|Nagoya|Fukuoka|Sapporo|Kobe)\b|[都道府県市区町村]"),
    "AE": re.compile(r"\bUAE\b|United Arab Emirates|\+971|\bDubai\b|Abu Dhabi|Sharjah|\bAED\b|\bDMCC\b|\bDIFC\b|Ajman|Ras Al Khaimah", re.I),
}
JA_CHARS = re.compile(r"[぀-ヿ一-鿿]")
TLD_OF = {"AU": (".au",), "ZA": (".za",), "JP": (".jp",), "AE": (".ae",)}
CAMP_COUNTRY = {"tw": "AU", "acd": "AU", "bc": "ZA"}  # nm is JP or AE per lead


def country_signals(domain, text_markers, want):
    sig = 0
    if domain.endswith(TLD_OF[want]):
        sig += 1
    if text_markers.get(want, 0) >= 1:
        sig += 1
    if text_markers.get(want, 0) >= 3:
        sig += 1
    if want == "JP" and text_markers.get("ja_chars", 0) >= 40:
        sig += 1
    return sig


# ------------------------------------------------------------------ name repair
LEGAL_RX = re.compile(r"((?:[A-Z0-9][\w&'’.\-]*\s+){0,6}[A-Z0-9][\w&'’.\-]*\s+(?:Pty\.?\s*\(?Ltd\.?\)?|\(Pty\)\s*Ltd\.?|Pty\.?\s+Limited|Limited|Ltd\.?|Inc\.?|CC|K\.K\.|Co\.,?\s*Ltd\.?|LLC|FZ-?LLC|FZE|FZCO))\b")
SEP = re.compile(r"\s+[|–—\-:·•»]\s+|\s*\|\s*")
LEAD_JUNK = re.compile(r"^(contact( us)?|about( us)?|welcome to|home( page)?|homepage|official site of|official website of)\s*[:\-–|]?\s*", re.I)


def letters(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def sim_domain(name, domain):
    root = rd(domain).split(".")[0]
    a, b = letters(name), letters(root)
    if not a or not b or len(b) < 3:
        return 0.0
    if b in a or (len(a) >= 5 and a in b):
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def tidy_name(s):
    s = html.unescape(str(s or "")).replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip(" -|:·•–—")
    for _ in range(2):
        s = LEAD_JUNK.sub("", s).strip(" -|:·•–—")
    s = re.sub(r"\s*[\(\[].*?[\)\]]\s*$", "", s).strip() if re.search(r"[\(\[]", s) and not re.search(r"\(Pty\)", s, re.I) else s
    if s.isupper() and len(s) > 4:
        s = s.title()
    return s


def good_name(s):
    return bool(s) and 3 <= len(s) <= 60 and len(s.split()) <= 7 and not JUNK_NAME.search(s) and not re.search(r"@|https?:|www\.", s)


def repair_name(raw, domain, title, legal_names, ja_ok=False):
    """Return (name, how) where how in existing|legal|title|none. Never invents a name."""
    cands = []
    r = tidy_name(raw)
    if good_name(r):
        cands.append(("existing", r))
    for ln in (legal_names or [])[:6]:
        ln = tidy_name(ln)
        if good_name(ln):
            cands.append(("legal", ln))
    for piece in SEP.split(html.unescape(title or "")):
        p = tidy_name(piece)
        if good_name(p):
            cands.append(("title", p))
    best, bs = None, 0.0
    for how, nm in cands:
        sc = sim_domain(nm, domain) + (0.15 if how == "legal" else 0) + (0.05 if how == "existing" else 0)
        if sc > bs:
            best, bs = (nm, how), sc
    # an existing/legal name is trusted if it resembles the domain OR carries a legal suffix; a title piece must resemble the domain
    if best and (bs >= 0.62 or (best[1] in ("existing", "legal") and re.search(r"\b(pty|ltd|limited|inc|cc|llc|k\.k\.)\b", best[0], re.I))):
        return best[0], best[1]
    if best and best[1] == "existing" and not title:
        return best[0], "existing"
    return "", "none"


# ------------------------------------------------------------------ rate-limited TinyFish
class TinyFish:
    def __init__(self):
        self.keys = [k.strip() for k in os.environ.get("TINYFISH_KEYS", "").split(",") if k.strip()]
        self.next_ok = {("s", k): 0.0 for k in self.keys}
        self.next_ok.update({("f", k): 0.0 for k in self.keys})
        self.dead = set()
        self.i = 0
        self.lock = threading.Lock()
        self.stats = collections.Counter()

    def _pick(self, kind, gap):
        while True:
            with self.lock:
                live = [k for k in self.keys if k not in self.dead]
                if not live:
                    return None
                best = min(live, key=lambda k: self.next_ok[(kind, k)])
                wait = self.next_ok[(kind, best)] - time.time()
                if wait <= 0:
                    self.next_ok[(kind, best)] = time.time() + gap
                    return best
            time.sleep(min(max(wait, 0.05), 1.0))

    def _call(self, kind, gap, req_fn):
        for attempt in range(4):
            key = self._pick(kind, gap)
            if key is None:
                return None, "no_keys"
            try:
                code, data = req_fn(key)
            except Exception as e:
                code, data = 0, str(e)[:120]
            if code == 200:
                self.stats[kind + "_ok"] += 1
                return data, None
            if code in (401, 403):
                self.dead.add(key)
                self.stats["dead_keys"] += 1
                continue
            if code == 429 or code >= 500 or code == 0:
                with self.lock:
                    self.next_ok[(kind, key)] = time.time() + 5 + attempt * 8
                self.stats[kind + "_retry"] += 1
                continue
            return None, "http%s" % code
        return None, "failed"

    def search(self, q, page=1):
        def fn(key):
            url = "https://api.search.tinyfish.ai?query=" + urllib.parse.quote(q) + ("&page=%d" % page if page > 1 else "")
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"X-API-Key": key}), timeout=45) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, None
        return self._call("s", 2.2, fn)

    def fetch(self, urls):
        def fn(key):
            req = urllib.request.Request("https://api.fetch.tinyfish.ai", method="POST", data=json.dumps({"urls": urls}).encode(),
                                         headers={"X-API-Key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, None
        return self._call("f", 0.45, fn)


TF = None


def tf():
    global TF
    if TF is None:
        TF = TinyFish()
    return TF


# ------------------------------------------------------------------ STAGE: contacted
def stage_contacted(args):
    out = CACHE / "contacted.json"
    cutoff = (NOW - dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S")
    keys = {k: v for k, v in ENV.items() if re.search(r"AGENTMAIL.*KEY|POOL\d+_AGENTMAIL_KEY", k) and v}
    emails = set()

    def pages(key, iid):
        got, tok = [], None
        for _ in range(150):
            path = "/inboxes/%s/messages?limit=100&labels=sent" % util.q(iid) + ("&page_token=%s" % tok if tok else "")
            c, d = util.am(key, "GET", path)
            if c != 200:
                break
            ms = d.get("messages", [])
            for m in ms:
                if (m.get("timestamp") or "")[:19] >= cutoff:
                    got += [util.parse_addr(t) for t in (m.get("to") or [])]
            tok = d.get("next_page_token")
            if not tok or not ms or (ms[-1].get("timestamp") or "")[:19] < cutoff:
                break
        return got

    def one(item):
        name, key = item
        c, d = util.am(key, "GET", "/inboxes?limit=100")
        res = set()
        if c != 200:
            return name, res, c
        for ib in d.get("inboxes", []):
            res.update(x for x in pages(key, ib.get("inbox_id")) if x)
        return name, res, 200
    t0 = time.time()
    bad = 0
    with ThreadPoolExecutor(10) as ex:
        for name, res, code in ex.map(one, keys.items()):
            emails |= res
            bad += code != 200
    log("contacted: AgentMail sent-folders", len(emails), "addresses from", len(keys), "keys (%d unreadable)" % bad, "in %ds" % (time.time() - t0))
    n0 = len(emails)
    for r in csv.DictReader(open(REPO / "seed/acd_contacted.csv")):
        emails.add(norm_email(r.get("email")))
    tw = jread(HOME / "AutoClaw/Shared/leadgen/tw_ledger.json", {})
    if isinstance(tw, dict):
        for k, v in tw.items():
            if "@" in str(k):
                emails.add(norm_email(k))
            if isinstance(v, dict) and v.get("email"):
                emails.add(norm_email(v["email"]))
    for p in (HOME / "AutoClaw/Shared").glob("**/sent_log.jsonl"):
        for r in jl_read(p):
            e = norm_email(r.get("em") or r.get("email") or "")
            if e:
                emails.add(e)
    for p in (HOME / "AutoClaw/Shared/leadgen/bc_ship_ledger.json", HOME / "AutoClaw/Shared/leadgen/bc_extra_leads.json"):
        pass
    emails = {e for e in emails if "@" in e}
    # domains we have mailed: never re-approach an organisation (skip shared mail domains)
    doms = collections.Counter()
    for e in emails:
        d = e.split("@")[1]
        if d not in FREEMAIL:
            doms[rd(d)] += 1
    jwrite(out, {"emails": sorted(emails), "domains": sorted(doms), "built": NOW.isoformat(), "agentmail_addresses": n0})
    log("contacted: total %d addresses, %d organisations -> %s" % (len(emails), len(doms), out.name))


def load_contacted():
    c = jread(CACHE / "contacted.json", None)
    if not c:
        log("ERROR: run `contacted` first")
        sys.exit(2)
    return set(c["emails"]), set(c["domains"])


# ------------------------------------------------------------------ pools
BC_TRADE_MAP = {"cleaning": "Cleaning", "security": "Security", "construction": "Construction", "civil": "Civil", "electrical": "Electrical", "facilities": "Facilities",
                "maintenance": "Facilities", "building maintenance": "Facilities", "ict": "ICT", "supplies": "Supplies", "transport": "Transport", "catering": "Catering",
                "solar": "Electrical", "plumbing": "plumbing-contractors", "plumbing-contractors": "plumbing-contractors", "electrical-contractors": "electrical-contractors",
                "painting": "Construction", "roofing": "Construction", "paving": "Civil", "general-suppliers": "Supplies", "transport-contractors": "Transport"}


def tw_trade(t):
    import tenderwin
    t = str(t or "").strip()
    if t in tenderwin.TRADES:
        return t
    tl = t.lower()
    for k in tenderwin.TRADES:
        if k.lower() == tl:
            return k
    alias = {"landscape": "landscaping", "gardening": "landscaping", "mowing": "landscaping", "electrician": "electrical", "plumber": "plumbing", "building": "construction",
             "painter": "painting", "air conditioning": "HVAC", "hvac": "HVAC", "it": "ICT", "pest": "pest control", "traffic": "traffic management", "waste": "waste"}
    for a, k in alias.items():
        if a in tl:
            return k
    return ""


def load_pools(limit=None):
    rows = collections.defaultdict(list)
    for r in jread(REPO / "leads_au.json", []):
        rows["tw"].append(dict(email=r.get("email"), company=r.get("company"), trade=r.get("trade"), state=r.get("province") or r.get("state"), origin="pool:leads_au"))
    for r in jread(REPO / "seed/tenderwin_leads.json", []):
        rows["tw"].append(dict(email=r.get("email"), company=r.get("company"), trade=r.get("trade"), state=r.get("state"), contact=r.get("contact_name"),
                               trigger={"kind": "award_won", "buyer": r.get("award_buyer"), "month": r.get("award_month")} if r.get("award_buyer") else None, origin="pool:tw_seed"))
    for fn in ("bc_leads.json", "bidcheck-deploy/leads.json"):
        for r in jread(REPO / fn, []):
            rows["bc"].append(dict(email=r.get("email"), company=r.get("company"), trade=r.get("trade"), state=r.get("province"), variant=r.get("variant"), signer=r.get("signer"),
                                   trigger={"kind": "award_won", "buyer": r.get("award_buyer"), "month": r.get("award_month")} if r.get("award_buyer") else None, origin="pool:" + fn))
    for r in jread(REPO / "leads.json", []):
        rows["nm"].append(dict(email=r.get("email"), company=r.get("name"), country=r.get("country"), source_tag=r.get("source_tag"), platform=r.get("platform"),
                               products=r.get("products"), reviews=r.get("reviews"), snippet=r.get("snippet"), origin="pool:nm_leads"))
    pri = {"hcp_providers", "disability_providers", "support_agencies"}
    for r in csv.DictReader(open(REPO / "seed/acd_leads.csv")):
        if r.get("campaign") in pri:
            rows["acd"].append(dict(email=r.get("email"), company=r.get("company"), trade=r.get("campaign"), state=r.get("state"), city=r.get("city"), contact=r.get("contact_name"),
                                    source=r.get("source"), origin="pool:acd_leads"))
    if os.environ.get("MINT_ONLY_HARVEST"):          # 2026-11-06: only genuinely new leads; the old pools are held back
        for camp in CAMPS:
            rows[camp] = []
    for camp in CAMPS:
        for h in jl_read(CACHE / ("harvest_%s.jsonl" % camp)):
            h.setdefault("origin", "harvest")
            rows[camp].append(h)
    if limit:
        for camp in CAMPS:
            rows[camp] = rows[camp][:limit]
    return rows


# ------------------------------------------------------------------ STAGE: build (free gates)
def stage_build(args):
    limit = args.get("limit")
    c_emails, c_domains = load_contacted()
    blocked = set()
    try:
        for ln in open(REPO / "engine/blocked_domains.txt"):
            d = ln.split("#")[0].strip().lower()
            if d:
                blocked.add(d)
    except Exception:
        pass
    pools = load_pools(limit)
    mx = jread(CACHE / "mx.json", {})
    rejects = collections.defaultdict(collections.Counter)
    kept = collections.defaultdict(list)
    seen = set()
    for camp in CAMPS:
        for r in pools[camp]:
            rej = rejects[camp]
            em = norm_email(r.get("email"))
            site = norm_email(r.get("email")).split("@")[-1] if em else ""
            domain_only = not em and r.get("domain")
            if domain_only:
                site = str(r["domain"]).lower().replace("www.", "")
                em = ""
            elif not email_ok(em):
                rej["invalid_email"] += 1
                continue
            dom = rd(site) if site else ""
            if not dom or "." not in dom:
                rej["no_domain"] += 1
                continue
            if em and em in c_emails:
                rej["already_contacted_email"] += 1
                continue
            if dom in c_domains or dom in blocked or site in blocked:
                rej["already_contacted_org_or_blocked"] += 1
                continue
            if site in FREEMAIL or dom in FREEMAIL:
                if camp != "bc" or not em:
                    rej["freemail"] += 1
                    continue
            if GOVEDU.search(site) or GOVEDU.search(dom):
                rej["gov_edu"] += 1
                continue
            if NOISE_DOMAINS.search(site):
                rej["noise_domain"] += 1
                continue
            nm_txt = str(r.get("company") or "")
            if BIG_RX.search(nm_txt) or BIG_RX.search(dom.split(".")[0].replace("-", " ")):
                rej["big_or_public_body"] += 1
                continue
            # trade / country normalisation per campaign
            if camp == "tw":
                tr = tw_trade(r.get("trade"))
                if not tr:
                    rej["trade_not_bucketed"] += 1
                    continue
                r["trade"] = tr
                r["state"] = norm_state(r.get("state"))
                r["country"] = "AU"
            elif camp == "bc":
                tr = BC_TRADE_MAP.get(str(r.get("trade") or "").strip().lower(), "")
                if not tr:
                    rej["trade_not_in_bc_pool"] += 1
                    continue
                r["trade"] = tr
                r["state"] = norm_state(r.get("state"))
                r["country"] = "ZA"
            elif camp == "nm":
                if r.get("country") not in ("JP", "AE"):
                    rej["country_not_jp_ae"] += 1
                    continue
            elif camp == "acd":
                r["country"] = "AU"
                r["state"] = norm_state(r.get("state"))
            key = (camp, em or dom)
            if key in seen:
                rej["dup_in_pool"] += 1
                continue
            seen.add(key)
            r.update(camp=camp, email=em, site=site, domain=dom, kind=local_kind(em, camp) if em else "unknown")
            kept[camp].append(r)
        log("build %s: pool %d -> kept %d | %s" % (camp, len(pools[camp]), len(kept[camp]), dict(rejects[camp].most_common(8))))
    # dead-domain check (DoH MX/A), cached
    doms = sorted({r["site"] for c in CAMPS for r in kept[c]} - set(mx))
    log("build: MX check on %d new domains" % len(doms))

    def chk(d):
        try:
            return d, bool(util.has_mx(d))
        except Exception:
            return d, True
    with ThreadPoolExecutor(24) as ex:
        for d, ok in ex.map(chk, doms):
            mx[d] = ok
    jwrite(CACHE / "mx.json", mx)
    total = 0
    with open(CACHE / "cands.jsonl", "w") as f:
        for camp in CAMPS:
            n_dead = 0
            for r in kept[camp]:
                if not mx.get(r["site"], True):
                    n_dead += 1
                    continue
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                total += 1
            rejects[camp]["dead_domain"] = n_dead
            log("build %s: dead domains dropped %d" % (camp, n_dead))
    jwrite(CACHE / "build_rejects.json", {c: dict(rejects[c]) for c in CAMPS})
    log("build: %d candidates -> cands.jsonl" % total)


# ------------------------------------------------------------------ STAGE: harvest
OCDS = "https://api.tenders.gov.au/ocds/findByDates/contractPublished/%s/%s"
SUPPLIER_OK = re.compile(r"\b(pty|ltd|limited|group|services|solutions|contracting|contractors|constructions?|cleaning|security|electrical|plumbing|engineering|maintenance|"
                         r"landscap\w*|building|builders|civil|projects|consulting|industries|enterprises|trading|supplies|systems|technologies|technology|digital|logistics|"
                         r"catering|painting|roofing|fencing|surveying|environmental|facilit\w+|property|training|recruitment|transport|haulage|mechanical|hvac|refrigeration)\b", re.I)
NGO_RX = re.compile(r"\\b(foundation|charit(y|able)|society|church|ministr(y|ies)|ministries|non-?profit|not-for-profit|volunteer|donat(e|ion)|fundrais\\w+|community (centre|center|group|organisation)|association of|chamber of commerce|\\bclub\\b|incorporated|associates? inc)\\b", re.I)
BIG2 = re.compile(r"\\b(henry schein|medline|cardinal health|bupa|ramsay|sonic healthcare|healthscope|aurizon|jacobs|aecom|wsp|arup|stantec|worley|monadelphous|programmed|spotless|compass group|sodexo|"
                  r"coca-cola|nestle|unilever|woolworths|coles|bunnings|harvey norman|wesfarmers|mcdonald|kfc|subway|starbucks|visy|boral|holcim|csr limited|brickworks|hanson|fletcher|"
                  r"the smith family|salvation army|red cross|anglicare|uniting|baptist|mission australia|st vincent|catholic|oxfam|world vision|goodstart)\\b", re.I)
PERSON = re.compile(r"^[A-Z][a-z'\-]+,\s+[A-Z][a-z]")


def _ocds_window(span):
    s, e = span
    url = OCDS % (s.strftime("%Y-%m-%dT00:00:00Z"), e.strftime("%Y-%m-%dT23:59:59Z"))
    out, pages = [], 0
    while url and pages < 60:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lead-mint/1.0"}), timeout=60) as r:
                d = json.loads(r.read())
        except Exception:
            time.sleep(2)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lead-mint/1.0"}), timeout=60) as r:
                    d = json.loads(r.read())
            except Exception:
                break
        for rel in d.get("releases", []):
            c = (rel.get("contracts") or [{}])[0]
            try:
                amt = float((c.get("value") or {}).get("amount") or 0)
            except Exception:
                amt = 0
            if amt < 100000 or amt > 20000000:
                continue
            a = (rel.get("awards") or [{}])[0]
            buyer = next((p.get("name") for p in rel.get("parties", []) if "procuringEntity" in (p.get("roles") or [])), "")
            for s_ in a.get("suppliers") or []:
                out.append({"name": (s_.get("name") or "").strip(), "amount": amt, "date": (c.get("dateSigned") or a.get("date") or "")[:10], "buyer": buyer or "", "ocid": rel.get("ocid")})
        url = (d.get("links") or {}).get("next")
        pages += 1
    return out


def harvest_awards(days=365, workers=6):
    cache = CACHE / "awards.json"
    if cache.exists():
        return jread(cache, [])
    end = NOW
    spans = []
    for i in range(0, days, 7):
        spans.append((end - dt.timedelta(days=min(i + 7, days)), end - dt.timedelta(days=i)))
    recs = []
    with ThreadPoolExecutor(workers) as ex:
        for n, res in enumerate(ex.map(_ocds_window, spans), 1):
            recs += res
            if n % 10 == 0:
                log("awards: %d/%d windows, %d contract rows" % (n, len(spans), len(recs)))
    by = {}
    for r in recs:
        nm = r["name"]
        if not nm or PERSON.match(nm) or BIG_RX.search(nm) or GOVEDU.search(nm.lower()) or not SUPPLIER_OK.search(nm):
            continue
        k = letters(nm)
        e = by.setdefault(k, {"name": nm, "total": 0, "n": 0, "last": "", "buyer": "", "top": 0})
        e["total"] += r["amount"]
        e["n"] += 1
        if r["date"] > e["last"]:
            e["last"] = r["date"]
        if r["amount"] > e["top"]:
            e["top"], e["buyer"] = r["amount"], r["buyer"]
    sup = sorted(by.values(), key=lambda x: -x["total"])
    jwrite(cache, sup)
    log("awards: %d contract rows -> %d candidate suppliers (>=A$100k, business-like names)" % (len(recs), len(sup)))
    return sup


def tw_trade_from_name(nm):
    import tenderwin
    for t, rx in tenderwin.TRADE_RX.items():
        if re.search(rx, nm, re.I):
            return t
    return ""


def find_site(name, extra="Australia", country_tlds=(".au",)):
    r, err = tf().search('"%s" %s' % (name, extra))
    for x in (r or {}).get("results", [])[:8]:
        u = x.get("url") or ""
        host = urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
        if not host or NOISE_DOMAINS.search(host) or GOVEDU.search(host):
            continue
        tld_ok = host.endswith(country_tlds) or host.endswith((".com", ".net", ".org"))
        if tld_ok and sim_domain(name, host) >= 0.55:
            return rd(host), x
    return None, None


def stage_harvest(args):
    which = args.get("which") or "awards"
    limit = args.get("limit") or 4000
    if which == "awards":
        sup = harvest_awards()[:limit]
        done = {h["name"] for h in jl_read(CACHE / "harvest_tw.jsonl")}
        miss = {h["name"] for h in jl_read(CACHE / "harvest_tw_nosite.jsonl")}
        todo = [s for s in sup if s["name"] not in done and s["name"] not in miss]
        log("harvest awards: %d suppliers, %d to resolve to a website" % (len(sup), len(todo)))
        n_ok = 0

        def one(s):
            dom, hit = find_site(s["name"])
            return s, dom
        with ThreadPoolExecutor(14) as ex:
            for i, (s, dom) in enumerate(ex.map(one, todo), 1):
                if dom:
                    n_ok += 1
                    jl_append(CACHE / "harvest_tw.jsonl", {"name": s["name"], "company": s["name"], "domain": dom, "site": dom, "trade": tw_trade_from_name(s["name"]) or "construction",
                                                           "trigger": {"kind": "award_won", "buyer": s["buyer"], "date": s["last"], "value": round(s["top"]), "month": None},
                                                           "origin": "harvest:austender_award", "country": "AU"})
                else:
                    jl_append(CACHE / "harvest_tw_nosite.jsonl", {"name": s["name"]})
                if i % 200 == 0:
                    log("harvest awards: %d/%d resolved (%d with a website) | tinyfish %s" % (i, len(todo), n_ok, dict(tf().stats)))
        log("harvest awards done: %d with a website" % n_ok)
        return
    # generic search harvest: queries file per campaign
    qs = QUERIES.get(which, [])
    limit_q = args.get("limit") or len(qs)
    done_q = {h["q"] for h in jl_read(CACHE / ("harvestq_%s.jsonl" % which))}
    todo = [q for q in qs[:limit_q] if q["q"] not in done_q]
    log("harvest %s: %d queries to run" % (which, len(todo)))

    def runq(q):
        out = []
        for pg in (1, 2):
            r, err = tf().search(q["q"], pg)
            if not r:
                break
            for x in r.get("results", []):
                u = x.get("url") or ""
                host = urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
                if not host or NOISE_DOMAINS.search(host) or GOVEDU.search(host):
                    continue
                if not host.endswith(q["tlds"]) and not host.endswith(".com"):
                    continue
                out.append({"company": x.get("title") or "", "domain": rd(host), "site": host, "trade": q.get("trade"), "state": q.get("state"), "country": q.get("country"),
                            "snippet": (x.get("snippet") or "")[:300], "origin": "harvest:search:" + which, "source_url": u, "platform": q.get("platform"), "source_tag": q.get("source_tag")})
        return q, out
    n = 0
    with ThreadPoolExecutor(10) as ex:
        for i, (q, out) in enumerate(ex.map(runq, todo), 1):
            seen = set()
            for o in out:
                if o["domain"] in seen:
                    continue
                seen.add(o["domain"])
                jl_append(CACHE / ("harvest_%s.jsonl" % which), o)
                n += 1
            jl_append(CACHE / ("harvestq_%s.jsonl" % which), {"q": q["q"], "n": len(seen)})
            if i % 50 == 0:
                log("harvest %s: %d/%d queries, %d sites | tinyfish %s" % (which, i, len(todo), n, dict(tf().stats)))
    log("harvest %s done: %d candidate sites" % (which, n))


def _mkq(tpl, items, tlds, country, **extra):
    return [dict(q=tpl.format(**i), tlds=tlds, country=country, **{**extra, **i.get("meta", {})}) for i in items]


def build_queries():
    import acd, tenderwin
    Q = {}
    # ACD: NDIS / HCP / Support at Home providers by place
    svc = ["NDIS registered provider", "home care package provider", "in-home aged care provider", "disability support services provider", "Support at Home provider"]
    Q["acd"] = [dict(q='%s %s %s contact email' % (s, c, st), tlds=(".au",), country="AU", trade="disability_providers" if "NDIS" in s or "disability" in s else "hcp_providers", state=st)
                for c, st in acd.PLACES for s in svc]
    # TW: trade x state
    Q["tw"] = [dict(q='%s "%s" Australia contact email enquiry' % (tenderwin.TRADE_LABELS.get(t, t), s), tlds=(".au",), country="AU", trade=t, state=s) for t in tenderwin.TRADES for s in tenderwin.STATES]
    # BC: SA trades x provinces
    bt = {"Cleaning": "cleaning company", "Security": "security company", "Construction": "building contractor", "Civil": "civil engineering contractor", "Electrical": "electrical contractor",
          "Facilities": "maintenance contractor", "ICT": "IT services company", "Supplies": "office supplies company", "Transport": "transport company", "Catering": "catering company"}
    cities = {"Gauteng": ["Johannesburg", "Pretoria", "Centurion"], "Western Cape": ["Cape Town"], "KwaZulu-Natal": ["Durban", "Pietermaritzburg"], "Eastern Cape": ["Gqeberha", "East London"],
              "Free State": ["Bloemfontein"], "Limpopo": ["Polokwane"], "Mpumalanga": ["Nelspruit", "Witbank"], "North West": ["Rustenburg"], "Northern Cape": ["Kimberley"]}
    Q["bc"] = [dict(q='%s %s South Africa contact email CSD registered' % (v, c), tlds=(".za",), country="ZA", trade=t, state=p) for t, v in bt.items() for p, cs in cities.items() for c in cs]
    # NM: Japan + UAE stores selling to the US
    jp_cat = ["matcha tea", "handmade ceramics pottery", "washi stationery", "kitchen knives", "denim workwear", "skincare cosmetics", "bonsai garden", "kimono yukata", "anime figures collectibles",
              "sake whisky", "japanese snacks", "tenugui towels", "calligraphy supplies", "fishing tackle", "mechanical keyboards", "watches", "bags leather goods", "sneakers streetwear"]
    Q["nm"] = [dict(q='%s online shop Japan international shipping worldwide contact' % c, tlds=(".jp",), country="JP", source_tag="J-SITE") for c in jp_cat]
    Q["nm"] += [dict(q='%s ships to USA Japan seller own store contact email' % c, tlds=(".jp",), country="JP", source_tag="J-SITE") for c in jp_cat]
    ae_cat = ["fashion", "abayas modest wear", "perfume oud", "jewellery", "beauty skincare", "home decor", "coffee dates gourmet", "fitness supplements", "kids toys", "electronics accessories", "art prints", "furniture"]
    Q["nm"] += [dict(q='%s Shopify store Dubai UAE ships to USA contact email' % c, tlds=(".ae",), country="AE", source_tag="U-SITE") for c in ae_cat]
    Q["nm"] += [dict(q='%s brand UAE international shipping USA contact us' % c, tlds=(".ae",), country="AE", source_tag="U-SITE") for c in ae_cat]
    return Q


QUERIES = {}


# ------------------------------------------------------------------ STAGE: enrich (TinyFish fetch)
PHONE = {"AU": re.compile(r"(?:\+61\s?|\(?0)[2-478]\)?[\s\-]?\d{4}[\s\-]?\d{4}|\b04\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b"),
         "ZA": re.compile(r"(?:\+27\s?|\(?0)\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{4}"),
         "JP": re.compile(r"(?:\+81[\s\-]?|0)\d{1,4}[\s\-]\d{1,4}[\s\-]\d{3,4}"),
         "AE": re.compile(r"(?:\+971[\s\-]?|00971|0)(?:[2-9]|5\d)[\s\-]?\d{3}[\s\-]?\d{4}")}
MICRO = re.compile(r"owner[- ]operat|family[- ]owned|family[- ]run|small business|sole trader|one[- ]man|husband and wife|our (small )?team of (\d|two|three|four|five|six|seven|eight|nine|ten)\b|founded by|owned and operated|veteran[- ]owned|locally owned|個人事業|家族経営|代表取締役", re.I)


def parse_fetch_result(res, site):
    text = res.get("text") or ""
    sitedom = rd(site)
    emails = []
    for m in EMAIL_RX.findall(text):
        e = norm_email(m)
        if email_ok(e) and rd(e.split("@")[1]) == sitedom and e not in emails:
            emails.append(e)
    marks = {k: len(rx.findall(text)) for k, rx in MARK.items()}
    marks["ja_chars"] = len(JA_CHARS.findall(text))
    phones = {}
    for k, rx in PHONE.items():
        ph = rx.findall(text)
        if ph:
            phones[k] = re.sub(r"\s+", " ", ph[0]).strip()
    legal = []
    for m in LEGAL_RX.finditer(text[:4000] + " " + text[-2500:]):
        s = m.group(1).strip()
        if s not in legal and len(s) < 70:
            legal.append(s)
    return {"title": res.get("title") or "", "desc": (res.get("description") or "")[:260], "lang": res.get("language"), "emails": emails, "marks": marks, "phones": phones,
            "legal": legal[:6], "micro": bool(MICRO.search(text)), "head": re.sub(r"\s+", " ", text[:420]), "final": res.get("final_url") or res.get("url"), "len": len(text)}


def merge_pages(parts):
    out = None
    for p in parts:
        if out is None:
            out = p
            continue
        out["emails"] = list(dict.fromkeys(out["emails"] + p["emails"]))
        for k, v in p["marks"].items():
            out["marks"][k] = out["marks"].get(k, 0) + v
        for k, v in p["phones"].items():
            out["phones"].setdefault(k, v)
        out["legal"] = list(dict.fromkeys(out["legal"] + p["legal"]))[:6]
        out["micro"] = out["micro"] or p["micro"]
    return out


def enrich_batch(batch):
    """batch: list of (site, need_contact). One TinyFish call fetches home (+/contact,/about) for each; merge per site."""
    urls, owner = [], {}
    for site, need in batch:
        paths = ["/"] + (["/contact", "/contact-us"] if need else [])
        for p in paths:
            u = "https://%s%s" % (site, p)
            urls.append(u)
            owner[u] = site
    data, err = tf().fetch(urls)
    per = collections.defaultdict(list)
    if data:
        for res in data.get("results", []):
            u = res.get("url") or ""
            s = owner.get(u) or next((v for k, v in owner.items() if k.rstrip("/") == u.rstrip("/")), None)
            if s:
                per[s].append(parse_fetch_result(res, s))
        errs = {e.get("url"): e for e in data.get("errors", [])}
    else:
        errs = {}
    # retry the www. host once for sites that returned nothing (http->https/www redirects surface as errors)
    miss = [(st, nd) for st, nd in batch if not per.get(st) and not st.startswith("www.")]
    if miss:
        wurls = {"https://www.%s/" % st: st for st, nd in miss}
        d2, e2 = tf().fetch(list(wurls))
        for res in (d2 or {}).get("results", []):
            st = wurls.get(res.get("url") or "")
            if st:
                per[st].append(parse_fetch_result(res, st))
    out = []
    for site, need in batch:
        parts = per.get(site)
        if parts:
            rec = merge_pages(parts)
            rec.update(site=site, ok=True, ts=time.time())
        else:
            rec = {"site": site, "ok": False, "err": (str(errs.get("https://%s/" % site, {}).get("error")) if errs else err) or "nopage", "ts": time.time()}
        out.append(rec)
    return out


def stage_enrich(args):
    limit = args.get("limit")
    cands = jl_read(CACHE / "cands.jsonl")
    have = {r["site"] for r in jl_read(CACHE / "fetch.jsonl")}
    need_contact = {}
    sites = {}
    for c in cands:
        s = c["site"]
        sites.setdefault(s, c["camp"])
        if c.get("kind") in ("role", "unknown", "role_ok"):
            need_contact[s] = True
    todo = [(s, need_contact.get(s, False)) for s in sites if s not in have]
    if limit:
        todo = todo[:limit]
    log("enrich: %d sites to fetch (%d already cached)" % (len(todo), len(have)))
    batches = [todo[i:i + 4] for i in range(0, len(todo), 4)]
    n = ok = 0
    t0 = time.time()
    with ThreadPoolExecutor(int(args.get("workers") or 20)) as ex:
        futs = [ex.submit(enrich_batch, b) for b in batches]
        for f in as_completed(futs):
            try:
                for rec in f.result():
                    jl_append(CACHE / "fetch.jsonl", rec)
                    n += 1
                    ok += bool(rec.get("ok"))
            except Exception as e:
                log("enrich batch error", str(e)[:100])
            if n and n % 400 < 4:
                log("enrich: %d/%d fetched, %d alive | %.1f/s | tinyfish %s" % (n, len(todo), ok, n / max(time.time() - t0, 1), dict(tf().stats)))
    log("enrich done: %d fetched, %d alive" % (n, ok))


# ------------------------------------------------------------------ STAGE: resolve
def stage_resolve(args):
    cands = jl_read(CACHE / "cands.jsonl")
    fetch = {}
    for r in jl_read(CACHE / "fetch.jsonl"):
        if r.get("ok") or r["site"] not in fetch:
            fetch[r["site"]] = r
    by_site = collections.defaultdict(list)
    for c in cands:
        by_site[c["site"]].append(c)
    c_emails, c_domains = load_contacted()
    rej = collections.defaultdict(collections.Counter)
    out = []
    for site, group in by_site.items():
        base = group[0]
        camp = base["camp"]
        f = fetch.get(site)
        if not f or not f.get("ok"):
            rej[camp]["site_unreachable"] += 1
            continue
        final_dom = rd(urllib.parse.urlparse(f.get("final") or "").netloc or site)
        if final_dom != rd(site) and (NOISE_DOMAINS.search(final_dom) or sim_domain(rd(site).split(".")[0], final_dom) < 0.4):
            rej[camp]["redirects_off_site"] += 1
            continue
        want = CAMP_COUNTRY.get(camp) or base.get("country")
        marks = dict(f["marks"])
        sig = country_signals(base["site"], marks, want)
        if sig < 2:
            rej[camp]["country_unverified"] += 1
            continue
        if marks.get("ja_chars", 0) and want in ("AU", "ZA", "AE") and marks.get("ja_chars", 0) > 200:
            rej[camp]["wrong_language"] += 1
            continue
        # competitor / aggregator / support-desk pages
        if camp in ("tw", "bc", "nm") and NGO_RX.search(f["title"] + " " + f["desc"] + " " + base.get("company", "")):
            rej[camp]["nonprofit_or_charity"] += 1
            continue
        if BIG2.search(f["title"] + " " + f["desc"] + " " + base.get("company", "") + " " + site):
            rej[camp]["large_or_chain"] += 1
            continue
        if re.search(r"tender (alert|portal|notification)|find tenders|tender search|directory of|listing of|business directory", f["head"] + " " + f["title"], re.I):
            rej[camp]["aggregator_or_directory"] += 1
            continue
        # email choice: named own-domain beats role beats role_ok. Candidates = pool emails + emails published on the site.
        opts = {}
        for c in group:
            if c["email"]:
                opts[c["email"]] = c
        for e in f["emails"]:
            if e not in opts and e not in c_emails and e.split("@")[1] not in FREEMAIL:
                x = dict(base)
                x.update(email=e, kind=local_kind(e, camp), origin=base["origin"] + "+site_email")
                opts[e] = x
        order = {"named": 0, "role_ok": 1, "role": 2}
        best = None
        for e, c in sorted(opts.items(), key=lambda kv: order.get(kv[1].get("kind"), 3)):
            if c.get("kind") in order and e not in c_emails:
                best = c
                break
        if not best:
            rej[camp]["no_email"] += 1
            continue
        core = re.sub(r"[^a-z]", "", best["email"].split("@")[0])
        if best["kind"] == "role" and not (core in MICRO_OK and f.get("micro")):
            rej[camp]["role_inbox_not_micro"] += 1
            continue
        raw = best.get("company") or base.get("company") or ""
        name, how = repair_name(raw, site, f["title"], f["legal"])
        if not name and camp != "tw":
            rej[camp]["no_reliable_name"] += 1
            continue
        lead = dict(best)
        lead.update(company=name, name_how=how, kind=best["kind"], country=want, phone=f["phones"].get(want, ""), site_title=f["title"], site_desc=f["desc"], micro=f.get("micro", False),
                    marks=marks, country_signals=sig, snippet=(f["desc"] or f["head"])[:300], alt_emails=[e for e in opts if e != best["email"]][:4])
        if camp == "tw" and not lead.get("state"):
            for st, rx in (("NSW", r"\bNSW\b|New South Wales|Sydney"), ("VIC", r"\bVIC\b|Victoria|Melbourne"), ("QLD", r"\bQLD\b|Queensland|Brisbane"), ("WA", r"\bWA\b|Western Australia|Perth"),
                           ("SA", r"\bSA\b|South Australia|Adelaide"), ("TAS", r"Tasmania|Hobart"), ("ACT", r"\bACT\b|Canberra"), ("NT", r"Northern Territory|Darwin")):
                if re.search(rx, f["head"] + " " + f["desc"] + " " + f["title"]):
                    lead["state"] = st
                    break
        out.append(lead)
        rej[camp]["resolved"] += 1
    with open(CACHE / "resolved.jsonl", "w") as fh:
        for l in out:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    jwrite(CACHE / "resolve_rejects.json", {c: dict(rej[c]) for c in CAMPS})
    for c in CAMPS:
        log("resolve %s: %s" % (c, dict(rej[c].most_common())))
    log("resolve: %d leads -> resolved.jsonl" % len(out))


# ------------------------------------------------------------------ STAGE: score (Jev)
BC_Q = {
    "will_pay": {"type": "noul", "instructions": "This South African business is established and profitable enough to pay about R300 per month for a tender-alert and bid-readiness service. Score HIGH for a real operating company with a professional presence; LOW for hobby sites, one-person informal traders with no website content, or very large corporates."},
    "bids_tenders": {"type": "noul", "instructions": "This business is in a trade that regularly bids on South African government or municipal tenders (construction, civil, electrical, plumbing, cleaning, security, ICT, supplies, transport, maintenance, catering). Score LOW for consumer retail, hospitality, schools, councils, government bodies and non-SA companies."},
    "owner_reads": {"type": "noul", "instructions": "This email address likely reaches the owner, a director or the person who prepares bids, not a generic support desk."},
    "real_company": {"type": "noul", "instructions": "This is a real, registered South African company that actually operates (not a directory, aggregator, lead-gen page or placeholder site)."},
}


def jev_state(camp, l):
    if camp == "bc":
        return ("South African business: company='%s', trade='%s', province='%s', email='%s' (%s inbox), website='%s', description='%s'. Evidence: %s" %
                (l.get("company"), l.get("trade"), l.get("state") or "", l["email"], l["kind"], l["site"], l.get("site_desc", "")[:200], l.get("snippet", "")[:200]))
    return None


def score_one(item):
    camp, l = item
    import acd, tenderwin, namemarshal
    ctx = dict(l)
    try:
        if camp == "acd":
            s = acd.score({"email": l["email"], "company": l["company"], "city": l.get("city") or l.get("state") or "", "state": l.get("state") or "", "source": (l.get("source") or l.get("origin") or "") + " | " + (l.get("site_desc") or "")[:120]})
        elif camp == "tw":
            tr = l.get("trigger") or {}
            s = tenderwin.score({"email": l["email"], "company": l["company"] or l["site"], "trade": l.get("trade") or "", "state": l.get("state") or "", "source": (l.get("origin") or "") + " | " + (l.get("site_desc") or "")[:120],
                                 "award_buyer": (tr.get("buyer") or "")})
        elif camp == "nm":
            s = namemarshal.score({"email": l["email"], "store": l["company"], "domain": l["site"], "country": l["country"], "products": l.get("products"), "reviews": l.get("reviews"),
                                   "snippet": (l.get("site_desc") or "") + " " + (l.get("snippet") or "")})
        else:
            s = util.jev(jev_state("bc", l), BC_Q)
            if s:
                s["score"] = round(0.45 * s["will_pay"] + 0.35 * s["bids_tenders"] + 0.20 * s["real_company"], 3)
                s["ok"] = s["bids_tenders"] >= 0.6 and s["will_pay"] >= 0.45 and s["real_company"] >= 0.5 and s["owner_reads"] >= (0.5 if l["kind"] == "named" else 0.65)
        return l["email"], s
    except Exception as e:
        return l["email"], None


def stage_score(args):
    res = jl_read(CACHE / "resolved.jsonl")
    done = {r["e"]: r for r in jl_read(CACHE / "jev.jsonl")}
    todo = [(l["camp"], l) for l in res if l["email"] not in done or done[l["email"]].get("s") is None]
    if args.get("limit"):
        todo = todo[: args["limit"]]
    log("score: %d leads to score (%d cached) with %d Jev keys" % (len(todo), len(done), len(util._jev_keys())))
    n = nn = fails = 0
    t0 = time.time()
    with ThreadPoolExecutor(int(args.get("workers") or 10)) as ex:
        for e, s in ex.map(score_one, todo):
            n += 1
            if s is None:
                nn += 1
                fails += 1
                if fails >= 40 and fails == n:
                    log("score: Jev is not answering (40 consecutive failures) - stopping; re-run later")
                    break
            else:
                fails = 0
            jl_append(CACHE / "jev.jsonl", {"e": e, "s": s, "ts": time.time()})
            if n % 300 == 0:
                log("score: %d/%d | %.1f/s | unavailable %d" % (n, len(todo), n / max(time.time() - t0, 1), nn))
    log("score done: %d scored, %d unavailable (held, not dropped)" % (n - nn, nn))


# ------------------------------------------------------------------ STAGE: export
def stage_export(args):
    res = jl_read(CACHE / "resolved.jsonl")
    jev = {}
    for r in jl_read(CACHE / "jev.jsonl"):
        if r.get("s"):
            jev[r["e"]] = r["s"]
    c_emails, c_domains = load_contacted()
    ranked = collections.defaultdict(list)
    drops = collections.defaultdict(collections.Counter)
    pending = []
    for l in res:
        s = jev.get(l["email"])
        if s is None:
            pending.append(l)
            continue
        if not s.get("ok"):
            drops[l["camp"]]["jev_fail"] += 1
            continue
        mult = {"named": 1.0, "role_ok": 0.92, "role": 0.7}.get(l["kind"], 0.7)
        bonus = 0.0
        tr = l.get("trigger") or {}
        if tr.get("kind") == "award_won":
            bonus += 0.08 + min(0.07, (tr.get("value") or 0) / 5_000_000 * 0.07)
        if l.get("micro"):
            bonus += 0.03
        if l.get("name_how") in ("legal", "existing"):
            bonus += 0.02
        l["jev"] = s
        l["rank"] = round(s.get("score", 0) * mult + bonus, 4)
        ranked[l["camp"]].append(l)
    # cross-campaign: one organisation appears once (highest rank wins); within campaign one address per organisation
    best_for = {}
    for camp in CAMPS:
        for l in ranked[camp]:
            d = rd(l["site"])
            if d not in best_for or l["rank"] > best_for[d][0]:
                best_for[d] = (l["rank"], camp)
    final = {}
    for camp in CAMPS:
        keep, seen = [], set()
        for l in sorted(ranked[camp], key=lambda x: -x["rank"]):
            d = rd(l["site"])
            if best_for[d][1] != camp:
                drops[camp]["claimed_by_other_campaign"] += 1
                continue
            if d in seen:
                drops[camp]["second_address_same_org"] += 1
                continue
            seen.add(d)
            keep.append(l)
        final[camp] = keep
    # ---- staging jsonl (handover schema) + feeds
    crawled = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    names = {"tw": "tenderwin", "bc": "bidcheck", "nm": "namemarshal", "acd": "acd"}
    for camp in CAMPS:
        with open(STAGING / ("%s-%s.jsonl" % (names[camp], DAY)), "w") as f:
            for i, l in enumerate(final[camp], 1):
                f.write(json.dumps({"company": l["company"], "domain": rd(l["site"]), "email": l["email"], "phone": l.get("phone", ""), "socials": "", "country": l["country"],
                                    "niche": l.get("trade") or l.get("source_tag") or "", "fit": round(l["jev"].get("score", 0) * 10, 1), "note": (l.get("site_desc") or "")[:140],
                                    "source_url": "https://" + l["site"] + "/", "crawled_at": crawled, "jev": l["jev"], "dedupe": "clean", "rank": i, "rank_score": l["rank"], "owner_reach": l["kind"],
                                    "state": l.get("state", ""), "trigger": l.get("trigger"), "origin": l.get("origin")}, ensure_ascii=False) + "\n")
    stamp = NOW.strftime("%Y%m%d-%H%M")
    BK = WORK / "feed_backups" / stamp
    BK.mkdir(parents=True, exist_ok=True)
    for fn in ("leads_au.json", "bc_leads.json", "leads.json", "seed/acd_leads.csv", "bidcheck-deploy/leads.json"):
        try:
            (BK / fn.replace("/", "__")).write_bytes((REPO / fn).read_bytes())
        except Exception:
            pass
    feeds = WORK / "feeds"
    feeds.mkdir(exist_ok=True)

    def nb(l):
        return {"batch": "mint-" + DAY} if str(l.get("origin") or "").startswith("harvest") else {}

    def tw_row(l):
        tr = l.get("trigger") or {}
        month = None
        try:
            d = dt.date.fromisoformat(str(tr.get("date") or "")[:10])
            month = "%s %d" % (d.strftime("%b"), d.year)
        except Exception:
            month = tr.get("month")
        return {"company": l["company"], "name": l["company"], "email": l["email"], "emails": [l["email"]], "trade": l["trade"], "province": l.get("state") or "", "state": l.get("state") or "",
                "domain": rd(l["site"]), "country": "AU", "award_buyer": (tr.get("buyer") or "").split(" - ")[0][:48] or None, "award_month": month,
                "snippet": (l.get("site_desc") or "")[:200], "source_tag": "mint_" + DAY, "score": l["rank"], "owner_reach": l["kind"], "platform": None, "preverified": True, **nb(l)}

    n_bc = max(1, len(final["bc"]))
    bc_pos = {id(l): i for i, l in enumerate(final["bc"])}

    def bc_row(l):
        # BidCheck's sender sorts by (tier, -jev_hot_p, -jev_activity): feed those from our Jev result so the ranking is native.
        tr = l.get("trigger") or {}
        i = bc_pos[id(l)]
        tier = "T1" if i < n_bc * 0.25 else ("T2" if i < n_bc * 0.65 else "T3")
        return {"company": l["company"], "email": l["email"], "trade": l["trade"], "domain": rd(l["site"]), "variant": l.get("variant") or "", "signer": l.get("signer") or "",
                "source": "mint_" + DAY, "award_buyer": (tr.get("buyer") or None), "award_month": tr.get("month"), "province": l.get("state") or "", "score": l["rank"],
                "tier": tier, "jev_hot_p": l["rank"], "jev_activity": round(l["jev"].get("bids_tenders", 0), 3), "owner_reach": l["kind"], **nb(l)}

    def nm_row(l):
        return {"domain": rd(l["site"]), "name": l["company"], "country": l["country"], "email": l["email"], "emails": [l["email"]] + l.get("alt_emails", [])[:2], "source_tag": l.get("source_tag") or ("J-SITE" if l["country"] == "JP" else "U-SITE"),
                "platform": l.get("platform"), "products": l.get("products"), "reviews": l.get("reviews"), "snippet": (l.get("site_desc") or l.get("snippet") or "")[:300], "score": l["rank"], "preverified": True, **nb(l)}
    jwrite(feeds / "leads_au.json", [tw_row(l) for l in final["tw"]])
    jwrite(feeds / "bc_leads.json", [bc_row(l) for l in final["bc"]])
    jwrite(feeds / "leads.json", [nm_row(l) for l in final["nm"]])
    with open(feeds / "acd_leads.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["campaign", "email", "contact_name", "company", "city", "state", "source", "icp"])
        for l in final["acd"]:
            w.writerow([l.get("trade") if l.get("trade") in ("hcp_providers", "disability_providers", "support_agencies") else "disability_providers", l["email"], l.get("contact") or "", l["company"], l.get("city") or "", l.get("state") or "", "mint_" + DAY, "provider"])
    jwrite(feeds / "seed_acd_feed.json", [{"company": l["company"], "name": l["company"], "email": l["email"], "emails": [l["email"]], "domain": rd(l["site"]), "country": "AU",
                                           "snippet": (l.get("site_desc") or "")[:200], "source_tag": "mint_" + DAY, "preverified": True, "score": l["rank"], "jev_score": l["rank"],
                                           "trade": l.get("trade") or "care", "province": l.get("state") or "", "state": l.get("state") or "",
                                           "campaign": l.get("trade") if l.get("trade") in ("hcp_providers", "disability_providers", "support_agencies") else "disability_providers",
                                           **nb(l)} for l in final["acd"]])
    # pending-Jev + role/low tier kept out of feeds
    with open(STAGING / ("_pending_jev-%s.jsonl" % DAY), "w") as f:
        for l in pending:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    # ---- report
    rr = jread(CACHE / "resolve_rejects.json", {})
    br = jread(CACHE / "build_rejects.json", {})
    L = ["# Lead mint report - %s" % NOW.strftime("%Y-%m-%d %H:%M UTC"), "", "Funnel per campaign (counts are leads/organisations at each step).", ""]
    caps = {"tw": 275, "bc": 1860, "nm": 500, "acd": 690}
    for camp in CAMPS:
        n = len(final[camp])
        named = sum(1 for l in final[camp] if l["kind"] == "named")
        L += ["## %s" % names[camp], "- free-gate rejects: %s" % dict(br.get(camp, {})), "- resolve rejects: %s" % dict(rr.get(camp, {})), "- jev rejects / dedupe: %s" % dict(drops[camp]),
              "- **in feed: %d leads** (%d named-owner, %d role/micro) = **%.1f days** at the service's DAILY_MAX of %d" % (n, named, n - named, n / caps[camp], caps[camp]), ""]
        top = sorted(final[camp], key=lambda x: -x["rank"])[:10]
        L += ["Top 10:"] + ["  %2d. %s <%s> %s %s | rank %.3f | jev %s | %s" % (i, l["company"], l["email"], l.get("trade") or "", l.get("state") or "", l["rank"], round(l["jev"].get("score", 0), 2), (l.get("trigger") or {}).get("kind", "")) for i, l in enumerate(top, 1)] + [""]
    L += ["Pending Jev (held, not dropped): %d" % len(pending)]
    (WORK / "REPORT.md").write_text("\n".join(L))
    (STAGING / ("MINT-REPORT-%s.md" % DAY)).write_text("\n".join(L))
    log("export: " + ", ".join("%s=%d" % (names[c], len(final[c])) for c in CAMPS), "| pending jev", len(pending))


# ------------------------------------------------------------------ status / main
def stage_status(args):
    def n(p):
        return len(jl_read(p)) if str(p).endswith(".jsonl") else None
    log("status:", {p.name: n(p) for p in sorted(CACHE.glob("*.jsonl"))})
    log("contacted:", len(jread(CACHE / "contacted.json", {}).get("emails", [])), "addresses")
    for p in sorted(STAGING.glob("*-%s.jsonl" % DAY)):
        log("staging", p.name, len(jl_read(p)))


STAGES = {"contacted": stage_contacted, "build": stage_build, "harvest": stage_harvest, "enrich": stage_enrich, "resolve": stage_resolve, "score": stage_score, "export": stage_export, "status": stage_status}


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    args = {}
    for i, a in enumerate(argv):
        if a == "--limit":
            args["limit"] = int(argv[i + 1])
        if a == "--which":
            args["which"] = argv[i + 1]
        if a == "--workers":
            args["workers"] = int(argv[i + 1])
    global QUERIES
    QUERIES = build_queries() if cmd in ("harvest", "all") else {}
    if cmd == "all":
        for s in ("contacted", "harvest_awards", "build", "enrich", "resolve", "score", "export"):
            if s == "harvest_awards":
                stage_harvest({"which": "awards"})
                continue
            STAGES[s](args)
        return
    STAGES[cmd](args)


if __name__ == "__main__":
    main()
