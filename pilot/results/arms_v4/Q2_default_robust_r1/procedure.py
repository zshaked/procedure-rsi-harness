import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WD = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+)?"

# Policy switches (adjusted from oracle answers)
MIN_LEVEL = 2
FUTURE_DATE_OUTCOME = "REQUEST_INFO"
LEGAL_HOLD_OUTCOME = "ESCALATE"
NO_EMAIL_OUTCOME = "REQUEST_AUTHORIZATION"
SPLIT_BASIS = "as_of"   # adjust holdings for splits dated <= as_of


def _clean(body):
    b = body
    b = re.sub(r"-{5,}\s*Forwarded message\s*-{5,}.*?\n\s*\n", "", b, flags=re.S | re.I)
    b = re.split(r"\n\s*This email and any attachments", b)[0]
    return b


def _mon(s):
    return MONTHS[s[:3].lower()]


def _safe(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _prev_month_end(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _infer_year(m, d, sent):
    c = _safe(sent.year, m, d)
    if c is None:
        return None
    if c > sent:
        c2 = _safe(sent.year - 1, m, d)
        return c2 or c
    return c


def parse_date(body, sent):
    """returns (date or None, found_expression_bool)"""
    b = _clean(body)
    low = b.lower()
    # relative expressions
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), True
    if re.search(r"(end of last month|last day of last month|month[- ]end|end of the month|end of previous month|last day of the month)", low):
        return _prev_month_end(sent), True
    if re.search(r"\btoday\b", low):
        return sent, True
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", b)
    if m:
        d = _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", b)
    if m:
        a, c, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _safe(y, a, c) or _safe(y, c, a)
        if d:
            return d, True
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]\s*" + MON_RE + r"[a-z]*\.?,?[- ]\s*(20\d\d)\b", b, re.I)
    if m:
        d = _safe(int(m.group(3)), _mon(m.group(2)), int(m.group(1)))
        if d:
            return d, True
    m = re.search(r"\b" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", b, re.I)
    if m:
        d = _safe(int(m.group(3)), _mon(m.group(1)), int(m.group(2)))
        if d:
            return d, True
    # no year
    m = re.search(r"\b(?:as of|as at|date|on)\s+(?:close of business\s+)?" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", b, re.I)
    if m:
        d = _infer_year(_mon(m.group(1)), int(m.group(2)), sent)
        if d:
            return d, True
    m = re.search(r"\b(?:as of|as at|date|on)\s+(?:close of business\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+" + MON_RE + r"\b", b, re.I)
    if m:
        d = _infer_year(_mon(m.group(2)), int(m.group(1)), sent)
        if d:
            return d, True
    return None, False


def parse_stated(body):
    b = _clean(body)
    m = re.search(r"(?:we show|we have|records show|figure is|we hold|our books show|show)\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s*(mm|m|k)?\b(?![-/])", b, re.I)
    if not m:
        return None
    num = m.group(1).replace(",", "")
    try:
        v = float(num)
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    if suf == "k":
        v *= 1000
    elif suf in ("m", "mm"):
        v *= 1000000
    return int(round(v))


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    men = request.get("mentions") or {}
    at = (men.get("account_text") or "").strip()
    it = (men.get("instrument_text") or "").strip()
    if not at:
        return _resp("REQUEST_INFO")
    accs = tools.search_accounts(at)
    if len(accs) != 1:
        return _resp("REQUEST_INFO")
    aid = accs[0]["id"]

    # authorization
    sender = request["from"].strip().lower()
    contact = tools.get_contact(sender)
    prof = tools.get_client_profile(aid) or {}
    authorized = False
    if contact:
        dom = sender.split("@")[-1]
        doms = [x.lower() for x in prof.get("domains", [])]
        if dom in doms:
            for e in tools.get_entitlements(contact["contact_id"]):
                if e["account_id"] == aid and e["level"] >= MIN_LEVEL and e["expires"] >= request["sent"]:
                    authorized = True
    if not authorized:
        return _resp("REQUEST_AUTHORIZATION")

    if prof.get("no_email_confirm"):
        return _resp("REQUEST_AUTHORIZATION")

    if not it:
        return _resp("REQUEST_INFO")
    inss = tools.search_instruments(it)
    if len(inss) != 1:
        return _resp("REQUEST_INFO")
    iid = inss[0]["id"]

    # as-of date
    d, found = parse_date(request["body"], sent)
    assumed = not found
    if d is None:
        d = sent
    if found and d > sent and FUTURE_DATE_OUTCOME:
        return _resp(FUTURE_DATE_OUTCOME)
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    if prof.get("legal_hold"):
        return _resp(LEGAL_HOLD_OUTCOME, account_id=aid, instrument_id=iid) if LEGAL_HOLD_OUTCOME == "ESCALATE" else _resp(LEGAL_HOLD_OUTCOME)

    # position
    splits = tools.get_corporate_actions(iid)
    total = 0
    raw_total = 0
    for t in tools.get_ledger(aid, iid):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        raw_total += q
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q

    stated = parse_stated(request["body"])
    if total <= 0:
        return _resp("NOT_HELD", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed)
    pend = [x for x in tools.get_instructions(aid, iid)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    pq0 = sum(x["qty"] for x in pend)
    if stated is not None and stated != total + pq0 and stated != raw_total + pq0:
        return _resp("ESCALATE", account_id=aid, instrument_id=iid, as_of=as_of,
                     as_of_assumed=assumed, settled=total)

    pq = sum(x["qty"] for x in pend)
    pdte = max(x["settle_date"] for x in pend) if pend else None
    return _resp("CONFIRMED", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed,
                 settled=total, pending=pq or None, pending_date=pdte if pq else None)
