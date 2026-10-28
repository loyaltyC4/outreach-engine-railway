"""Shared helpers for the outreach engine. Standard library only, so the image stays tiny."""
import json, os, re, time, datetime as dt, urllib.request, urllib.parse, urllib.error

UA = "outreach-engine/1.0"


def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(t=None):
    return (t or now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def http(method, url, payload=None, headers=None, timeout=40):
    h = {"User-Agent": UA}
    h.update(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


# ---------- AgentMail ----------
AM = "https://api.agentmail.to/v0"


def am(key, method, path, payload=None):
    return http(method, AM + path, payload, {"Authorization": "Bearer " + key})


def q(s):
    return urllib.parse.quote(s, safe="")


def parse_addr(s):
    s = s if isinstance(s, str) else (s.get("email") or "") if isinstance(s, dict) else ""
    m = re.search(r"<([^>]+)>", s) or re.search(r"([^\s<>\"']+@[^\s<>\"']+)", s)
    return (m.group(1) if m else "").lower().strip(".,;")


def msg_to(m):
    to = m.get("to") or []
    to = to if isinstance(to, list) else [to]
    return [parse_addr(t) for t in to if t]


# ---------- DNS (MX over HTTPS, no system tools needed) ----------
_mx = {}


def has_mx(domain):
    if domain in _mx:
        return _mx[domain]
    ok = False
    for _ in range(2):
        c, d = http("GET", "https://cloudflare-dns.com/dns-query?name=%s&type=MX" % urllib.parse.quote(domain),
                    headers={"Accept": "application/dns-json"}, timeout=15)
        if c == 200:
            ok = any(a.get("type") == 15 for a in d.get("Answer", []) or [])
            break
    _mx[domain] = ok
    return ok


# ---------- Jev (typesafe systemone) ----------
def jev(state, questions):
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        return None
    for _ in range(3):
        c, d = http("POST", "https://api.typesafe.ai/v1/systemone",
                    {"model": "jev-latest", "state": state, "questions": questions},
                    {"Authorization": "Bearer " + key}, timeout=90)
        if c == 200 and "answers" in d:
            return {k: round(v["noul"], 3) for k, v in d["answers"].items()}
        time.sleep(1.5)
    return None


# ---------- Firecrawl search (rotates through the key pool) ----------
class Firecrawl:
    def __init__(self):
        self.keys = [k.strip() for k in os.environ.get("FIRECRAWL_KEYS", "").split(",") if k.strip()]
        self.i = 0
        self.dead = set()

    def search(self, query, limit=15):
        for _ in range(len(self.keys)):
            if not self.keys:
                return None
            k = self.keys[self.i % len(self.keys)]
            self.i += 1
            if k in self.dead:
                continue
            c, d = http("POST", "https://api.firecrawl.dev/v1/search",
                        {"query": query, "limit": limit, "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}},
                        {"Authorization": "Bearer " + k}, timeout=120)
            if c == 200:
                return d.get("data") or []
            if c in (401, 402, 403):
                self.dead.add(k)
        return None


FREE_MAIL = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.au", "bigpond.com", "bigpond.net.au",
             "iinet.net.au", "optusnet.com.au", "live.com", "icloud.com", "outlook.com.au", "hotmail.com.au", "tpg.com.au",
             "internode.on.net", "westnet.com.au", "me.com", "aol.com", "protonmail.com", "proton.me", "msn.com", "live.com.au"}

EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def reg_domain(host):
    host = host.lower().split(":")[0].replace("www.", "")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-1] == "au" and parts[-2] in ("com", "org", "net", "gov", "edu", "asn", "id"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])
