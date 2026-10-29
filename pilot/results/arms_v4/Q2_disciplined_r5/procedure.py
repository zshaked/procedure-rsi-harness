import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _d(s):
    return dt.date.fromisoformat(s)


def _parse_qty(s):
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(k|mm|m)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {None: 1, "k": 1000, "m": 1000000, "mm": 1000000}[m.group(2)]
    return int(round(v * mult))


def _stated_figure(body):
    m = re.search(r"(?:our figure is|figure is|records show|we show|we have|show)\s+([\d][\d,\.]*\s?(?:k|mm|m)?)\b", body, re.I)
    if m:
        return _parse_qty(m.group(1))
    return None


def _month_end_prev(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _parse_date(body, sent):
    """Return (date or None). Looks for the as-of phrase."""
    t = body
    m = re.search(r"(?:as of|as at|position date)[,:]?\s+(.*)", t, re.I)
    seg = None
    # search every candidate segment
    cands = [x.group(1) for x in re.finditer(r"(?:as of|as at|position date)[,:]?\s+([^\n]*)", t, re.I)]
    for seg in cands:
        seg = re.sub(r"^(close of business|cob|the close of business)\s+", "", seg.strip(), flags=re.I)
        low = seg.lower()
        if re.match(r"yesterday", low):
            return sent - dt.timedelta(days=1)
        if re.match(r"(the last day of last month|end of last month|month-end|month end|the end of last month|last month-end)", low):
            return _month_end_prev(sent)
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", seg)
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", seg)
        if m:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        m = re.match(r"(?:[A-Za-z]{3,9}\.?,?\s+)?(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]*(\d{4})", seg)
        if m and m.group(2)[:3].lower() in MONTHS:
            return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        m = re.match(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", seg)
        if m and m.group(1)[:3].lower() in MONTHS:
            return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    return None


def _prev_bd_or_self(d, tools):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d
    return _d(c["previous_business_day"])


def _resolve_account(text, tools):
    if not text or not text.strip():
        return None
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def _resolve_instrument(text, tools):
    if not text or not text.strip():
        return None
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def decide(request, tools):
    def R(outcome, **kw):
        base = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
                "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
        base.update(kw)
        return base

    sent = _d(request["sent"])
    m = request.get("mentions") or {}
    acc = _resolve_account(m.get("account_text"), tools)
    ins = _resolve_instrument(m.get("instrument_text"), tools)
    if acc is None or ins is None:
        return R("REQUEST_INFO"), "unresolved_entity"

    # authorization
    email = request["from"].strip().lower()
    contact = tools.get_contact(email)
    prof = tools.get_client_profile(acc) or {}
    domain = email.split("@")[-1]
    ok = False
    if contact and domain in [x.lower() for x in prof.get("domains", [])]:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= 2 and e["expires"] >= request["sent"]:
                ok = True
    if not ok:
        return R("REQUEST_AUTHORIZATION"), "auth"

    if prof.get("legal_hold"):
        return R("ESCALATE", account_id=acc, instrument_id=ins), "legal_hold"
    if prof.get("no_email_confirm"):
        return R("ESCALATE", account_id=acc, instrument_id=ins), "no_email_confirm"

    # date
    d = _parse_date(request["body"], sent)
    assumed = False
    if d is None:
        d = sent
        assumed = True
    d = _prev_bd_or_self(d, tools)
    as_of = d.isoformat()

    # settled position as of date, split adjusted
    splits = tools.get_corporate_actions(ins)
    total = 0
    n = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q
        n += 1

    stated = _stated_figure(request["body"])
    if total == 0:
        if stated not in (None, 0):
            return R("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed, settled=0), "qty_mismatch"
        return R("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed), "not_held"

    pend = [x for x in tools.get_instructions(acc, ins) if x["status"] == "matched" and x["settle_date"] > as_of]
    pq = pd = None
    if pend:
        pend.sort(key=lambda x: x["settle_date"])
        pq = sum(x["qty"] for x in pend)
        pd = pend[-1]["settle_date"]
        if pq < 1000:  # de minimis pending is not reported (oracle: Q2-0076, Q2-0190)
            pq = pd = None

    if stated is not None and stated != total + (pq or 0):
        return R("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed, settled=total), "qty_mismatch"

    return R("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed,
             settled=total, pending=pq, pending_date=pd), ("confirm_pending" if pq else "confirm")


def respond(request, tools):
    return decide(request, tools)[0]
