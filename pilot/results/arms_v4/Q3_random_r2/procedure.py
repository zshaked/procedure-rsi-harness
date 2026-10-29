import re, datetime as dt

MON = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def _d(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def parse_date(body, sent):
    """Return (date or None, found_phrase_bool). Searches the body for an as-of date."""
    s = dt.date.fromisoformat(sent)
    t = body
    # ISO
    for m in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b', t):
        # skip forwarded header "Date: ..."
        pre = t[max(0, m.start() - 6):m.start()]
        if 'Date:' in pre:
            continue
        d = _d(*m.groups())
        if d:
            return d, True
    m = re.search(r'\b(\d{1,2})-([A-Za-z]{3})[a-z]*-(\d{4})\b', t)
    if m and m.group(2).lower() in MON:
        d = _d(m.group(3), MON[m.group(2).lower()], m.group(1))
        if d:
            return d, True
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b', t)
    if m and m.group(2)[:3].lower() in MON:
        d = _d(m.group(3), MON[m.group(2)[:3].lower()], m.group(1))
        if d:
            return d, True
    m = re.search(r'\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', t)
    if m and m.group(1)[:3].lower() in MON:
        d = _d(m.group(3), MON[m.group(1)[:3].lower()], m.group(2))
        if d:
            return d, True
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        d = _d(y, a, b) if a <= 12 else _d(y, b, a)
        if d:
            return d, True
    tl = t.lower()
    if re.search(r'\byesterday\b', tl):
        return s - dt.timedelta(days=1), True
    if re.search(r'\btoday\b', tl):
        return s, True
    if re.search(r'(end of (the )?last month|last day of (the )?last month|end of (the )?previous month|last month[- ]end|month[- ]end)', tl):
        return s.replace(day=1) - dt.timedelta(days=1), True
    return None, False


def parse_qty(txt):
    m = re.search(r'(?:figure is|records show|we show|we have|show)\s+(-?[\d,]*\.?\d+)\s*([kKmM]{1,2})?', txt, re.I)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(',', ''))
    except Exception:
        return None
    suf = (m.group(2) or '').lower()
    if suf == 'k':
        v *= 1e3
    elif suf in ('m', 'mm'):
        v *= 1e6
    return int(round(v))


def _resolve_account(tools, txt):
    if not txt:
        return []
    return [a['id'] for a in tools.search_accounts(txt)]


def _resolve_instr(tools, txt):
    if not txt:
        return []
    return [i['id'] for i in tools.search_instruments(txt)]


def respond(request, tools):
    out = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
           "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def done(o, **kw):
        out["outcome"] = o
        out.update(kw)
        return out

    m = request.get("mentions") or {}
    sent = request["sent"]
    accs = _resolve_account(tools, m.get("account_text"))
    if len(accs) != 1:
        return done("REQUEST_INFO")
    acc = accs[0]

    # authorization
    c = tools.get_contact(request["from"])
    ok = False
    if c:
        for e in tools.get_entitlements(c["contact_id"]):
            if e["account_id"] == acc and e["level"] >= 3 and e["expires"] >= sent:
                ok = True
    if not ok:
        return done("REQUEST_AUTHORIZATION")

    ins = _resolve_instr(tools, m.get("instrument_text"))
    if len(ins) != 1:
        return done("REQUEST_INFO")
    ins = ins[0]

    prof = tools.get_client_profile(acc) or {}
    if prof.get("legal_hold"):
        return done("ESCALATE", account_id=acc, instrument_id=ins)

    d, found = parse_date(request["body"], sent)
    assumed = False
    if not found:
        d = dt.date.fromisoformat(sent)
        assumed = True
    as_of = d.isoformat()
    if d > dt.date.fromisoformat(sent):
        return done("REQUEST_INFO")
    cal = tools.get_calendar(as_of)
    if not cal["business_day"]:
        return done("REQUEST_INFO")

    # position
    splits = tools.get_corporate_actions(ins)
    total = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] <= as_of:
            q = t["qty"]
            for sp in splits:
                if sp["date"] <= as_of and t["date"] < sp["date"]:
                    q *= sp["ratio"]
            total += q

    claimed = parse_qty(request["body"])
    if total == 0:
        if claimed:
            return done("ESCALATE", account_id=acc, instrument_id=ins)
        return done("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed)
    if claimed is not None and claimed != total:
        return done("ESCALATE", account_id=acc, instrument_id=ins)

    pend, pdate = None, None
    horizon = (dt.date.fromisoformat(sent) + dt.timedelta(days=30)).isoformat()
    ps = [x for x in tools.get_instructions(acc, ins)
          if x["status"] == "matched" and as_of < x["settle_date"] <= horizon]
    if ps:
        pend = sum(x["qty"] for x in ps)
        pdate = min(x["settle_date"] for x in ps)
    return done("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed,
                settled=total, pending=pend, pending_date=pdate)
