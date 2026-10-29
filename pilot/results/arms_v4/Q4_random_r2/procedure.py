import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
TOL = 0.10


def _num(s):
    s = s.strip().lower().replace(",", "")
    mult = 1
    if s.endswith("mm"):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def _stated(body):
    pats = [r"(?:records show|we show|we have|figure is|we hold|shows?)\s+([\d][\d,\.]*\s*(?:mm|m|k)?)\b",
            r"our figure is\s+([\d][\d,\.]*\s*(?:mm|m|k)?)"]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            return _num(m.group(1).replace(" ", ""))
    return None


def _prev_bd(d, tools):
    return dt.date.fromisoformat(tools.get_calendar(d.isoformat())["previous_business_day"])


def _is_bd(d, tools):
    return tools.get_calendar(d.isoformat())["business_day"]


def _parse_date(body, sent, tools):
    """Return a date (before business-day adjustment) or None."""
    b = body
    low = b.lower()
    if re.search(r"yesterday", low):
        return sent - dt.timedelta(days=1)
    if re.search(r"(end of last month|last day of last month|month-end|month end|end of month)", low):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    # skip forwarded-header Date: line
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", b):
        pre = b[max(0, m.start() - 6):m.start()]
        if "Date:" in pre:
            continue
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]*(\d{4})\b", b)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})\b", b)
    if m and m.group(1).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def _resolve_account(req, tools):
    m = req.get("mentions") or {}
    txt = m.get("account_text")
    cands = []
    if txt:
        cands = tools.search_accounts(txt)
    if not cands and not txt:
        mm = re.search(r"\b(ACC-\d+|SA-\d+)\b", req["body"])
        if mm:
            cands = tools.search_accounts(mm.group(1))
    return cands


def _resolve_instrument(req, tools):
    txt = (req.get("mentions") or {}).get("instrument_text")
    if not txt:
        return []
    return tools.search_instruments(txt)


def _authorized(req, acct_id, sent, tools):
    c = tools.get_contact(req["from"])
    if not c:
        return False
    prof = tools.get_client_profile(acct_id) or {}
    dom = req["from"].split("@")[-1].lower()
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct_id and e["level"] >= 2 and e["expires"] >= sent.isoformat():
            return True
    return False


def _verified_sender(req, sent, tools):
    c = tools.get_contact(req["from"])
    if not c:
        return False
    return any(_authorized(req, e["account_id"], sent, tools) for e in tools.get_entitlements(c["contact_id"]))


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    out = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
           "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def done(o):
        out["outcome"] = o
        return out

    accs = _resolve_account(request, tools)
    if len(accs) > 1:
        return done("REQUEST_INFO")
    if not accs:
        return done("REQUEST_INFO" if _verified_sender(request, sent, tools) else "REQUEST_AUTHORIZATION")
    acct = accs[0]["id"]
    if not _authorized(request, acct, sent, tools):
        return done("REQUEST_AUTHORIZATION")
    ins = _resolve_instrument(request, tools)
    out["account_id"] = acct
    if len(ins) == 1:
        out["instrument_id"] = ins[0]["id"]
    prof = tools.get_client_profile(acct) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        if len(ins) == 1:
            return done("ESCALATE")
        return done("ESCALATE")
    if len(ins) != 1:
        return done("REQUEST_INFO")
    iid = ins[0]["id"]
    d = _parse_date(request["body"], sent, tools)
    if d is None:
        return done("REQUEST_INFO")
    if not _is_bd(d, tools):
        d = _prev_bd(d, tools)
    asof = d.isoformat()
    out["as_of"] = asof
    led = tools.get_ledger(acct, iid)
    splits = [s for s in tools.get_corporate_actions(iid) if s["date"] <= asof]
    total = 0
    for t in led:
        if t["date"] <= asof:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"]:
                    q *= s["ratio"]
            total += q
    pend = [x for x in tools.get_instructions(acct, iid) if x["status"] == "matched" and x["settle_date"] > asof]
    pq = sum(x["qty"] for x in pend)
    stated = _stated(request["body"])
    if stated is not None:
        ours = total + pq
        base = ours if ours else 1
        if abs(stated - ours) / base > TOL and abs(stated - total) / (total if total else 1) > TOL:
            out["settled"] = total
            return done("ESCALATE")
    if total == 0 and not pend:
        return done("NOT_HELD")
    out["settled"] = total
    if pend:
        out["pending"] = pq
        out["pending_date"] = max(x["settle_date"] for x in pend)
    return done("CONFIRMED")
