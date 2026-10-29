import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}

TOLERANCE = 0.10      # relative gap between the client's stated figure and ours that is tolerated
MIN_LEVEL = 2         # entitlement level needed to receive a confirmation


# ----------------------------------------------------------------------------- text helpers
def _strip_forward_header(body):
    lines = body.split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i].strip().startswith("---------- Forwarded message"):
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _mon(s):
    return MONTHS[s.lower()[:3]]


def _mkdate(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month_end_before(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent, tools=None):
    """Return the date the requester asks about, or None if no date is given."""
    low = text.lower()
    # ISO / 2026/01/31
    m = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", low)
    if m:
        d = _mkdate(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d
    # 12 January 2026 / 12-Jan-2026 / Mon 12 Jan 2026 / 12th Jan, 2026
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/.]+" + MONTH_RE + r"\.?[\s\-/,.]+(\d{4})\b", low)
    if m:
        d = _mkdate(int(m.group(3)), _mon(m.group(2)), int(m.group(1)))
        if d:
            return d
    # January 12, 2026
    m = re.search(r"\b" + MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low)
    if m:
        d = _mkdate(int(m.group(3)), _mon(m.group(1)), int(m.group(2)))
        if d:
            return d
    # 1/23/2026 (US month first; day first only if impossible otherwise)
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", low)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _mkdate(y, b, a) if a > 12 else _mkdate(y, a, b)
        if d:
            return d
    # 1/23/26
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2})\b", low)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
        d = _mkdate(y, b, a) if a > 12 else _mkdate(y, a, b)
        if d:
            return d
    # day + month without a year: take the latest such date not after the sending date
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MONTH_RE + r"\b", low) or \
        re.search(r"\b" + MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})", low)
    if m:
        g = m.groups()
        if g[0].isdigit():
            day, mon = int(g[0]), _mon(g[1])
        else:
            mon, day = _mon(g[0]), int(g[1])
        d = _mkdate(sent.year, mon, day)
        if d and d > sent:
            d = _mkdate(sent.year - 1, mon, day)
        if d:
            return d
    # ---- relative phrases
    low = re.sub(r"[\-_]+", " ", low)
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1)
    m = re.search(r"\b(\d+|two|three|four|five)\s+(?:business\s+|working\s+)?days?\s+ago\b", low)
    if m:
        n = {"two": 2, "three": 3, "four": 4, "five": 5}.get(m.group(1)) or int(m.group(1))
        return sent - dt.timedelta(days=n)
    if re.search(r"\b(today|close of business today|cob today)\b", low):
        return sent
    if re.search(r"(year[\s\-]*end|end\s+of\s+(the\s+)?(last|previous|prior)\s+year|end\s+of\s+(the\s+)?year)", low):
        return dt.date(sent.year - 1, 12, 31) if sent.month < 12 or sent.day < 31 else sent
    if re.search(r"(quarter[\s\-]*end|end\s+of\s+(the\s+)?(last|previous|prior)\s+quarter|end\s+of\s+(the\s+)?quarter)", low):
        q_start_month = ((sent.month - 1) // 3) * 3 + 1
        return dt.date(sent.year, q_start_month, 1) - dt.timedelta(days=1)
    if re.search(r"(last|previous|prior)\s+(business\s+|working\s+)?day\s+of\s+(the\s+)?(last|previous|prior)\s+month"
                 r"|end\s+of\s+(the\s+)?(last|previous|prior)\s+month|(last|previous|prior)\s+month[\s\-]*end"
                 r"|month[\s\-]*end|end\s+of\s+(the\s+)?month|last\s+(business\s+|working\s+)?day\s+of\s+(the\s+)?month"
                 r"|last\s+(business|working)\s+day\s+of\s+last\s+month", low):
        return _month_end_before(sent)
    m = re.search(r"\b(?:last|previous|prior|this past)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
    if m:
        wd = WEEKDAYS[m.group(1)]
        d = sent - dt.timedelta(days=1)
        while d.weekday() != wd:
            d -= dt.timedelta(days=1)
        return d
    if re.search(r"\b(end|close)\s+of\s+(the\s+)?(last|previous|prior)\s+week\b|\blast\s+week[\s\-]*end\b", low):
        d = sent - dt.timedelta(days=sent.weekday() + 3)   # Friday of previous week
        return d
    if re.search(r"\b(previous|prior|last)\s+(business|working)\s+day\b", low):
        d = sent - dt.timedelta(days=1)
        while d.weekday() >= 5:
            d -= dt.timedelta(days=1)
        return d
    return None


_NUM = r"(-?\s?\d[\d,]*(?:\.\d+)?)\s*(k|mm|m|million|thousand)?"


def parse_qty(body):
    m = re.search(r"(?:records show|books show|figure is|figure of|we show|we have|we hold|our figure|show us holding|shows?)\s*:?\s*" + _NUM + r"(?![\w/\-])",
                  body, re.I)
    if not m:
        return None
    s = m.group(1).replace(",", "").replace(" ", "")
    try:
        v = float(s)
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    if suf in ("k", "thousand"):
        v *= 1e3
    elif suf in ("mm", "m", "million"):
        v *= 1e6
    return int(round(v))


# ----------------------------------------------------------------------------- system helpers
def _on_or_before_business_day(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def _lookup_account(text, tools):
    if not text:
        return []
    t = re.sub(r"\s+", " ", text.strip().strip(".,;:()\"'"))
    hits = tools.search_accounts(t)
    if not hits and t.lower().startswith("the "):
        hits = tools.search_accounts(t[4:])
    return hits


def _lookup_instrument(text, tools):
    if not text:
        return []
    t = re.sub(r"\s+", " ", text.strip().strip(".,;:()\"'"))
    hits = tools.search_instruments(t)
    seen, out = set(), []
    for h in hits:
        if h["id"] not in seen:
            seen.add(h["id"])
            out.append(h)
    return out


def _position(acct_id, inst_id, as_of, tools):
    splits = tools.get_corporate_actions(inst_id)
    total = 0
    for t in tools.get_ledger(acct_id, inst_id):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q = q * s["ratio"]
            total += q
    return int(round(total))


def _pending(acct_id, inst_id, as_of, tools):
    tot, last = 0, None
    for x in tools.get_instructions(acct_id, inst_id):
        if x["status"] == "matched" and x["settle_date"] > as_of:
            tot += x["qty"]
            if last is None or x["settle_date"] > last:
                last = x["settle_date"]
    return tot, last


def _valid_entitlement(contact, acct_id, tools, sent_iso):
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] == acct_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent_iso:
            return True
    return False


def _domain_ok(contact, acct_id, tools):
    prof = tools.get_client_profile(acct_id)
    if not prof:
        return False
    dom = contact["email"].split("@")[-1].lower()
    return dom in [d.lower() for d in prof["domains"]]


def _authorized(contact, acct_id, tools, sent_iso):
    if contact is None:
        return False
    return _domain_ok(contact, acct_id, tools) and _valid_entitlement(contact, acct_id, tools, sent_iso)


def _sender_verified(contact, tools):
    """Sender is a known contact writing from a domain registered for an account they hold an entitlement on."""
    if contact is None:
        return False
    for e in tools.get_entitlements(contact["contact_id"]):
        if _domain_ok(contact, e["account_id"], tools):
            return True
    return False


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ----------------------------------------------------------------------------- main
def _respond(request, tools):
    sent_iso = request["sent"]
    sent = dt.date.fromisoformat(sent_iso)
    body = _strip_forward_header(request.get("body") or "")
    men = request.get("mentions") or {}
    m_from = re.search(r"[\w.+\-]+@[\w.\-]+", request.get("from") or "")
    contact = tools.get_contact(m_from.group(0)) if m_from else None

    acct_text = men.get("account_text")
    if not acct_text:
        m = re.search(r"\b(ACC-\d+|SA-\d+)\b", body)
        acct_text = m.group(1) if m else None
    inst_text = men.get("instrument_text")
    if not inst_text:
        m = re.search(r"\bUS[0-9A-Z]{9}\d\b", body)
        inst_text = m.group(0) if m else None

    # 1. who is writing: unknown senders / unregistered domains cannot be answered at all
    if not _sender_verified(contact, tools):
        return _resp("REQUEST_AUTHORIZATION")

    # 2. which client
    accs = _lookup_account(acct_text, tools)
    insts = _lookup_instrument(inst_text, tools)
    if len(accs) != 1:
        return _resp("REQUEST_INFO")
    acct = accs[0]

    # 3. is the sender entitled to this client
    if not _authorized(contact, acct["id"], tools, sent_iso):
        return _resp("REQUEST_AUTHORIZATION")

    if len(insts) != 1:
        return _resp("REQUEST_INFO", account_id=acct["id"])
    inst = insts[0]
    base = dict(account_id=acct["id"], instrument_id=inst["id"])

    d = parse_date(body, sent, tools)
    if d is None or d > sent:
        return _resp("REQUEST_INFO", **base)
    d = _on_or_before_business_day(d, tools)
    as_of = d.isoformat()

    prof = tools.get_client_profile(acct["id"]) or {}
    if prof.get("legal_hold"):
        return _resp("ESCALATE", as_of=as_of, **base)

    settled = _position(acct["id"], inst["id"], as_of, tools)
    pend, pdate = _pending(acct["id"], inst["id"], as_of, tools)

    if settled == 0 and pend == 0:
        return _resp("NOT_HELD", as_of=as_of, **base)

    stated = parse_qty(body)
    if stated is not None:
        ok = False
        for ref in {settled, settled + pend}:
            if ref == 0:
                ok = ok or stated == 0
            else:
                ok = ok or abs(stated - ref) / abs(ref) <= TOLERANCE
        if not ok:
            return _resp("ESCALATE", as_of=as_of, settled=settled, **base)

    return _resp("CONFIRMED", as_of=as_of, settled=settled,
                 pending=pend or None, pending_date=pdate if pend else None, **base)


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _resp("REQUEST_INFO")
