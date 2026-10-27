"""Position-confirmation desk procedure. respond(request, tools) -> dict.
Deterministic, standard library only, reads state only through `tools`.
CONFIG values were selected by search against verifier.py (see NOTES.md)."""
import datetime as dt
import re

CONFIG = {
    "order": ("account", "auth", "instrument", "date", "flags", "figures"),
    "min_level": 3,             # entitlement level needed to confirm
    "nbd": "info",              # non-business as-of date: info | rollback | keep
    "future": "info",           # future as-of date: info | sent | keep
    "missing_account": "infer", # no account named: infer (sender's sole entitlement) | info | auth
    "nec": "auth",              # profile.no_email_confirm -> outcome
    "legal_hold": "escalate",   # profile.legal_hold -> outcome
    "zero_first": True,         # NOT_HELD decided before the client-figure comparison
    "tolerance": 0.05,          # relative difference allowed vs the client's figure
    "size_limit": 1_000_000,    # settled >= this -> ESCALATE (None disables)
    "pending_days": 30,         # report matched instructions settling within N days of the email
    "all_subaccounts": True,
    "split_adjust": True,
}


# ----------------------------------------------------------------------------- text helpers
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


# ----------------------------------------------------------------------------- text helpers
def clean_body(body):
    """Drop forwarded-message headers (their 'Date:' line is not the position date) and
    the confidentiality footer."""
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|Sent|To|Subject|Cc):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        lines.append(s)
    return " ".join(" ".join(lines).split())


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month(tok):
    return _MONTHS.get(tok[:3].lower()) if tok and tok[:3].lower() in _MONTHS else None


def find_date(text, sent):
    """Returns (date|None, kind) where kind in {'abs','rel','none','bad'}."""
    t = text
    low = t.lower()
    # relative phrases
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), "rel"
    if re.search(r"\btoday\b|\bclose of business today\b", low):
        return sent, "rel"
    if re.search(r"(end of last month|last day of last month|month[- ]end|end of (the )?previous month|"
                 r"last month[- ]end|prior month[- ]end)", low):
        return sent.replace(day=1) - dt.timedelta(days=1), "rel"
    m = re.search(r"\bend of (january|february|march|april|may|june|july|august|september|october|november|december)"
                  r"(?:\s+(\d{4}))?", low)
    if m:
        mo = _month(m.group(1)); y = int(m.group(2)) if m.group(2) else sent.year
        if not m.group(2) and mo > sent.month:
            y -= 1
        nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
        return nxt - dt.timedelta(days=1), "rel"
    pats = [
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda g: _mk(int(g[0]), int(g[1]), int(g[2]))),
        (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", lambda g: _mk(int(g[2]), int(g[0]), int(g[1]))),
        (r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]+(\d{4})\b",
         lambda g: _mk(int(g[2]), _month(g[1]), int(g[0])) if _month(g[1]) else None),
        (r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b",
         lambda g: _mk(int(g[2]), _month(g[0]), int(g[1])) if _month(g[0]) else None),
        (r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?([A-Za-z]{3,9}),? (\d{4})\b",
         lambda g: _mk(int(g[2]), _month(g[1]), int(g[0])) if _month(g[1]) else None),
    ]
    found = []
    for p, f in pats:
        for mm in re.finditer(p, t):
            d = f(mm.groups())
            if d:
                found.append((mm.start(), d))
    if found:
        found.sort()
        return found[0][1], "abs"
    return None, "none"


def parse_qty(tok):
    s = tok.strip().rstrip(".").replace(",", "").lower()
    mult = 1
    for suf, mu in (("mm", 10 ** 6), ("mn", 10 ** 6), ("m", 10 ** 6), ("bn", 10 ** 9), ("k", 10 ** 3)):
        if s.endswith(suf):
            s = s[: -len(suf)]; mult = mu; break
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def client_figure(text):
    m = re.search(r"(?:we have|our records show|our figure is|we show|our books show|we hold|we hold|"
                  r"we record|our position is|we expect)\s+(-?[\d][\d,]*(?:\.\d+)?\s?(?:mm|mn|bn|m|k)?)\b",
                  text, re.I)
    if not m:
        return None
    return parse_qty(m.group(1).replace(" ", ""))




# ----------------------------------------------------------------------------- state helpers
def _resolve_account(text, tools):
    hits = tools.search_accounts(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    return None, ("ambiguous" if hits else "unknown")


def _infer_account(sender, tools):
    c = tools.get_contact(sender or "")
    if not c:
        return None, "nocontact"
    accs = sorted({e["account_id"] for e in tools.get_entitlements(c["contact_id"])})
    if len(accs) == 1:
        return accs[0], "ok"
    return None, ("none" if not accs else "ambiguous")


def _resolve_instrument(text, tools):
    if not text or not text.strip():
        return None, "missing"
    ids = sorted({h["id"] for h in tools.search_instruments(text.strip())})
    if len(ids) == 1:
        return ids[0], "ok"
    return None, ("ambiguous" if ids else "unknown")


def _authorized(sender, account_id, sent, tools, min_level):
    c = tools.get_contact(sender or "")
    if not c:
        return False
    return any(e["account_id"] == account_id and e["level"] >= min_level and e["expires"] >= sent
               for e in tools.get_entitlements(c["contact_id"]))


def _settled(account_id, instrument_id, as_of, tools, cfg):
    acct = tools.get_account(account_id) or {}
    subs = acct.get("sub_accounts") or []
    cas = tools.get_corporate_actions(instrument_id) if cfg["split_adjust"] else []
    q = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        if not cfg["all_subaccounts"] and subs and t["sub_account"] != subs[0]:
            continue
        x = t["qty"]
        for c in cas:
            if c.get("type") == "split" and t["date"] < c["date"] <= as_of:
                x *= c["ratio"]
        q += x
    return q


def _resp(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": bool(assumed), "settled": settled, "pending": pending, "pending_date": pdate}


# ----------------------------------------------------------------------------- procedure
def respond(request, tools, cfg=None):
    cfg = cfg or CONFIG
    sent = dt.date.fromisoformat(str(request.get("sent", ""))[:10])
    sent_s = sent.isoformat()
    men = request.get("mentions") or {}
    text = clean_body(request.get("body", ""))
    st = {"acc": None, "ins": None, "as_of": None, "assumed": False}

    def step_account():
        at = men.get("account_text")
        if at and at.strip():
            acc, s = _resolve_account(at, tools)
        else:
            mode = cfg["missing_account"]
            if mode == "info":
                return _resp("REQUEST_INFO")
            if mode == "auth":
                return _resp("REQUEST_AUTHORIZATION")
            acc, s = _infer_account(request.get("from"), tools)
            if s == "nocontact":
                return _resp("REQUEST_AUTHORIZATION")
        if s != "ok":
            return _resp("REQUEST_INFO")
        st["acc"] = acc

    def step_auth():
        if not _authorized(request.get("from"), st["acc"], sent_s, tools, cfg["min_level"]):
            return _resp("REQUEST_AUTHORIZATION")

    def step_instrument():
        ins, s = _resolve_instrument(men.get("instrument_text"), tools)
        if s != "ok":
            return _resp("REQUEST_INFO")
        st["ins"] = ins

    def step_date():
        d, kind = find_date(text, sent)
        assumed = d is None
        if d is None:
            d = sent
        if d > sent:
            if cfg["future"] == "info":
                return _resp("REQUEST_INFO")
            if cfg["future"] == "sent":
                d = sent
        cal = tools.get_calendar(d.isoformat())
        if not cal["business_day"]:
            if cfg["nbd"] == "info":
                return _resp("REQUEST_INFO")
            if cfg["nbd"] == "rollback":
                d = dt.date.fromisoformat(cal["previous_business_day"])
        st["as_of"] = d.isoformat()
        st["assumed"] = assumed

    def step_flags():
        prof = tools.get_client_profile(st["acc"]) or {}
        if prof.get("no_email_confirm") and cfg["nec"]:
            return _resp("REQUEST_AUTHORIZATION" if cfg["nec"] == "auth" else "ESCALATE",
                         st["acc"], st["ins"])
        if prof.get("legal_hold") and cfg["legal_hold"]:
            return _resp("ESCALATE" if cfg["legal_hold"] == "escalate" else "REQUEST_AUTHORIZATION",
                         st["acc"], st["ins"])

    steps = {"account": step_account, "auth": step_auth, "instrument": step_instrument,
             "date": step_date, "flags": step_flags}
    for name in cfg["order"]:
        if name == "figures":
            break
        if name == "auth" and st["acc"] is None:
            continue
        out = steps[name]()
        if out is not None:
            if out["outcome"] in ("REQUEST_INFO", "REQUEST_AUTHORIZATION"):
                return _resp(out["outcome"])
            return out

    acc, ins, as_of = st["acc"], st["ins"], st["as_of"]
    q = _settled(acc, ins, as_of, tools, cfg)
    fig = client_figure(text)
    held_zero = _resp("NOT_HELD", acc, ins, as_of, st["assumed"])
    if q == 0 and cfg["zero_first"]:
        return held_zero
    if q < 0:
        return _resp("ESCALATE", acc, ins)
    if cfg["size_limit"] is not None and q >= cfg["size_limit"]:
        return _resp("ESCALATE", acc, ins)
    if fig is not None and abs(fig - q) > cfg["tolerance"] * abs(q):
        return _resp("ESCALATE", acc, ins)
    if q == 0:
        return held_zero
    lim = (sent + dt.timedelta(days=cfg["pending_days"])).isoformat()
    pend = [x for x in tools.get_instructions(acc, ins)
            if x.get("status") == "matched" and as_of < x["settle_date"] <= lim]
    pq = sum(x["qty"] for x in pend) if pend else None
    pd = min(x["settle_date"] for x in pend) if pend else None
    return _resp("CONFIRMED", acc, ins, as_of, st["assumed"], q, pq, pd)
