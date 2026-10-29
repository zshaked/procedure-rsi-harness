import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 2


def _date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def parse_date(body, sent):
    """Return (date|None, found_phrase_bool)."""
    s = dt.date.fromisoformat(sent)
    t = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    cands = []
    # restrict to the text after cue words to avoid the forwarded header date
    cue = re.search(r"(as of|as at|position date|, position date)", t, re.I)
    seg = t[cue.start():] if cue else t
    if not cue:
        # drop forwarded-header block
        seg = re.sub(r"^-+ Forwarded message -+\nFrom:.*\nDate:.*\n", "", t)
    if re.search(r"\byesterday\b", seg, re.I):
        return s - dt.timedelta(days=1)
    if re.search(r"end of last month|last day of last month|month-end|end of month", seg, re.I):
        return s.replace(day=1) - dt.timedelta(days=1)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", seg)
    if m:
        return _date(*m.groups())
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", seg)
    if m:
        return _date(m.group(3), m.group(1), m.group(2))
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]*(\d{4})\b", seg)
    if m and m.group(2).lower() in MONTHS:
        return _date(m.group(3), MONTHS[m.group(2).lower()], m.group(1))
    m = re.search(r"\b([A-Za-z]{3})[a-z]* (\d{1,2}),? (\d{4})\b", seg)
    if m and m.group(1).lower() in MONTHS:
        return _date(m.group(3), MONTHS[m.group(1).lower()], m.group(2))
    return None


def parse_qty(tok):
    tok = tok.strip().lower().replace(",", "")
    m = re.fullmatch(r"([\d.]+)\s*(k|mm|m)?", tok)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"k": 1e3, "mm": 1e6, "m": 1e6}.get(m.group(2), 1)
    return int(round(v * mult))


def stated_figure(body):
    pats = [r"(?:figure is|we show|we have|records show|our records show|show)\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m)?)(?=[\s\.,]|$)"]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            tok = m.group(1)
            return parse_qty(tok)
    return None


def prev_bd(tools, d):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d
    return dt.date.fromisoformat(c["previous_business_day"])


def blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def decide(request, tools):
    m = request.get("mentions") or {}
    sent = request["sent"]
    body = request["body"]
    # account
    at = m.get("account_text")
    if not at or not at.strip():
        return blank("REQUEST_INFO"), "account_missing"
    hits = tools.search_accounts(at)
    if len(hits) == 0:
        return blank("REQUEST_INFO"), "account_unresolved"
    if len(hits) > 1:
        return blank("REQUEST_INFO"), "account_ambiguous"
    acct = hits[0]["id"]
    # authorization
    sender = request["from"].lower()
    contact = tools.get_contact(sender)
    prof = tools.get_client_profile(acct) or {}
    if not contact:
        return blank("REQUEST_AUTHORIZATION"), "no_contact"
    ents = [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == acct]
    if not ents:
        return blank("REQUEST_AUTHORIZATION"), "no_entitlement"
    ok = [e for e in ents if e["expires"] >= sent]
    if not ok:
        return blank("REQUEST_AUTHORIZATION"), "entitlement_expired"
    if max(e["level"] for e in ok) < MIN_LEVEL:
        return blank("REQUEST_AUTHORIZATION"), "auth_level"
    dom = sender.split("@")[-1]
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return blank("REQUEST_AUTHORIZATION"), "domain_mismatch"
    # instrument
    it = m.get("instrument_text")
    if not it or not it.strip():
        return blank("REQUEST_INFO"), "instrument_missing"
    ih = tools.search_instruments(it)
    if len(ih) == 0:
        return blank("REQUEST_INFO"), "instrument_unresolved"
    if len(ih) > 1:
        return blank("REQUEST_INFO"), "instrument_ambiguous"
    inst = ih[0]["id"]
    if prof.get("legal_hold"):
        return blank("ESCALATE", account_id=acct, instrument_id=inst), "legal_hold"
    if prof.get("no_email_confirm"):
        return blank("ESCALATE", account_id=acct, instrument_id=inst), "no_email_confirm"
    # as of
    d = parse_date(body, sent)
    assumed = False
    if d is None:
        d = dt.date.fromisoformat(sent)
        assumed = True
    if d > dt.date.fromisoformat(sent):
        return blank("REQUEST_INFO"), "date_future"
    d = prev_bd(tools, d)
    asof = d.isoformat()
    # settled
    splits = tools.get_corporate_actions(inst)
    total = 0
    raw = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > asof:
            continue
        q = t["qty"]
        raw += q
        for s in splits:
            if t["date"] < s["date"] <= asof:
                q *= s["ratio"]
        total += q
    stated = stated_figure(body)
    if total == 0:
        return blank("NOT_HELD", account_id=acct, instrument_id=inst, as_of=asof,
                     as_of_assumed=assumed), "zero_position"
    pend = [x for x in tools.get_instructions(acct, inst)
            if x["status"] == "matched" and x["settle_date"] > asof]
    pq = sum(x["qty"] for x in pend) or None
    pd = min(x["settle_date"] for x in pend) if pend else None
    if stated is not None and stated not in (total, total + (pq or 0), raw):
        return blank("ESCALATE", account_id=acct, instrument_id=inst, as_of=asof,
                     as_of_assumed=assumed, settled=total), "figure_mismatch"
    return blank("CONFIRMED", account_id=acct, instrument_id=inst, as_of=asof,
                 as_of_assumed=assumed, settled=total, pending=pq, pending_date=pd), \
        ("pending" if pq else "confirm_plain")


def respond(request, tools):
    return decide(request, tools)[0]
