import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 2


def _d(s):
    return dt.date.fromisoformat(s)


def _strip_forward(body):
    return re.sub(r"-{3,}\s*Forwarded message\s*-{3,}\s*\nFrom:[^\n]*\nDate:[^\n]*\n", "", body)


def _last_month_end(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date or None, kind) kind in 'explicit','relative',None."""
    b = _strip_forward(body)
    low = b.lower()
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", b)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[-\s]([A-Za-z]{3})[a-z]*[-\s,]*(20\d\d)\b", b)
    if m and m[2].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])), "explicit"
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", b)
    if m and m[1].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[1].lower()], int(m[2])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", b)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2])), "explicit"
    if re.search(r"last day of (?:last|the previous) month|end of (?:last|the previous) month|month[- ]end|end of month|end of the month", low):
        return _last_month_end(sent), "relative"
    if "yesterday" in low:
        return sent - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", low):
        return sent, "relative"
    return None, None


def parse_figure(body):
    b = _strip_forward(body)
    m = re.search(r"(?:figure is|we show|we have|records show|our books show|shows?)\s+([\d][\d,\.]*)\s*(k|mm|m)?\b", b, re.I)
    if not m:
        return None
    num = m[1].rstrip(".,")
    suf = (m[2] or "").lower()
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    if suf == "k":
        v *= 1000
    elif suf in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def _resolve_account(text, tools):
    if not text:
        return None, "none"
    t = text.strip()
    hits = tools.search_accounts(t)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if not hits:
        return None, "none"
    return None, "ambiguous"


def _resolve_instrument(text, tools):
    if not text:
        return None, "none"
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    return None, ("none" if not hits else "ambiguous")


def _prev_bd(d, tools):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d
    return _d(c["previous_business_day"])


def _info():
    return {"outcome": "REQUEST_INFO", "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _auth():
    r = _info()
    r["outcome"] = "REQUEST_AUTHORIZATION"
    return r


def authorized(request, acct_id, tools):
    sent = _d(request["sent"])
    c = tools.get_contact(request["from"])
    if not c:
        return False
    prof = tools.get_client_profile(acct_id)
    if not prof:
        return False
    dom = request["from"].lower().split("@")[-1]
    if dom not in [x.lower() for x in prof["domains"]]:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct_id and e["level"] >= MIN_LEVEL and _d(e["expires"]) >= sent:
            return True
    return False


def respond(request, tools):
    m = request.get("mentions") or {}
    sent = _d(request["sent"])
    acct, ast = _resolve_account(m.get("account_text"), tools)
    if ast != "ok":
        return _info()
    if not authorized(request, acct, tools):
        return _auth()
    inst, ist = _resolve_instrument(m.get("instrument_text"), tools)
    if ist != "ok":
        return _info()
    d, kind = parse_date(request["body"], sent)
    assumed = False
    if d is None:
        d, assumed = sent, True
    if d > sent:
        return _info()
    d = _prev_bd(d, tools)
    as_of = d.isoformat()

    splits = [s for s in tools.get_corporate_actions(inst) if s["date"] <= as_of]
    settled = 0
    raw = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        raw += q
        for s in splits:
            if t["date"] < s["date"]:
                q *= s["ratio"]
        settled += q

    base = {"account_id": acct, "instrument_id": inst, "as_of": as_of, "as_of_assumed": assumed,
            "settled": None, "pending": None, "pending_date": None}
    prof = tools.get_client_profile(acct)
    stated = parse_figure(request["body"])
    pend = [x for x in tools.get_instructions(acct, inst) if x["status"] == "matched" and x["settle_date"] > as_of]
    def _padj(x):
        q = x["qty"]
        for sp in tools.get_corporate_actions(inst):
            if as_of < sp["date"] <= x["settle_date"]:
                q *= sp["ratio"]
        return q
    pq = sum(_padj(x) for x in pend)
    if prof.get("legal_hold") or (stated is not None and stated not in (settled, settled + pq, raw, raw + pq)):
        base["outcome"] = "ESCALATE"
        base["settled"] = settled
        return base
    if settled == 0:
        base["outcome"] = "NOT_HELD"
        return base
    base["outcome"] = "CONFIRMED"
    base["settled"] = settled
    if pend:
        base["pending"] = pq
        base["pending_date"] = min(x["settle_date"] for x in pend)
    return base
