import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
TOL = 0.10


def _d(s):
    return dt.date.fromisoformat(s)


def _parse_qty(s):
    s = s.replace(",", "").strip().lower()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(k|mm|m)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"k": 1e3, "m": 1e6, "mm": 1e6}.get(m.group(2), 1)
    return int(round(v * mult))


def _stated_figure(body):
    pats = [r"our records show\s+([\d][\d.,]*(?:k|mm|m)?\b)\s*(?:units|shares)?",
            r"we have\s+([\d][\d.,]*(?:k|mm|m)?\b)\s*(?:units|shares)",
            r"our figure is\s+([\d][\d.,]*(?:k|mm|m)?\b)",
            r"we show\s+([\d][\d.,]*(?:k|mm|m)?\b)"]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            t = m.group(1).strip().rstrip(".,")
            q = _parse_qty(t)
            if q is not None:
                return q
    return None


def _prev_bd(tools, d):
    c = tools.get_calendar(d.isoformat())
    return c["previous_business_day"]


def _adjust(tools, d):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d.isoformat()
    return c["previous_business_day"]


def _parse_date(body, sent):
    sent_d = _d(sent)
    t = body
    low = t.lower()
    # relative phrases
    if re.search(r"(last day of last month|end of last month|month[- ]end|end of month|last day of the month)", low):
        first = sent_d.replace(day=1)
        return first - dt.timedelta(days=1)
    if re.search(r"\byesterday\b", low):
        return sent_d - dt.timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return sent_d
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", t)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", t)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]*(20\d\d)\b", t)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", t)
    if m and m.group(1).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def _strip_fwd(body):
    out = []
    for ln in body.split("\n"):
        if re.match(r"^\s*(-{3,}.*|From:.*|Date:.*|Sent:.*|To:.*)$", ln):
            continue
        out.append(ln)
    return "\n".join(out)


def _ent_ok(e, sent):
    return e["level"] >= 2 and e["expires"] >= sent


def _resolve_account(tools, text):
    if not text:
        return []
    hits = tools.search_accounts(text)
    return [h["id"] for h in hits]


def _resolve_instrument(tools, text):
    if not text:
        return []
    return [i["id"] for i in tools.search_instruments(text)]


def _base(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    sent = request["sent"]
    body = request["body"]
    ment = request.get("mentions") or {}
    sender = request["from"].lower()
    dom = sender.split("@")[-1]
    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    accs = _resolve_account(tools, ment.get("account_text"))
    insts = _resolve_instrument(tools, ment.get("instrument_text"))

    def dom_ok(acc):
        p = tools.get_client_profile(acc)
        return bool(p) and dom in [x.lower() for x in p["domains"]]

    if len(accs) == 1:
        acc = accs[0]
        okent = any(e["account_id"] == acc and _ent_ok(e, sent) for e in ents)
        if not contact or not okent or not dom_ok(acc):
            return _base("REQUEST_AUTHORIZATION")
    else:
        acc = None
        cands = None
        if not any(dom_ok(e["account_id"]) and e["expires"] >= sent
                   and (cands is None or e["account_id"] in cands) for e in ents):
            return _base("REQUEST_AUTHORIZATION")
        return _base("REQUEST_INFO")

    if len(insts) != 1:
        return _base("REQUEST_INFO", account_id=acc)
    ins = insts[0]

    d = _parse_date(_strip_fwd(body), sent)
    if d is None:
        return _base("REQUEST_INFO", account_id=acc, instrument_id=ins)
    as_of = _adjust(tools, d)

    prof = tools.get_client_profile(acc)
    if prof and (prof.get("legal_hold") or prof.get("no_email_confirm")):
        return _base("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of)

    splits = tools.get_corporate_actions(ins)
    settled = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q *= s["ratio"]
        settled += q

    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    pending = sum(x["qty"] for x in pend) or None
    pdate = max(x["settle_date"] for x in pend) if pend else None

    stated = _stated_figure(body)
    if stated is not None:
        devs = [abs(stated - v) / max(abs(v), 1) for v in (settled, settled + (pending or 0))]
        if min(devs) > TOL:
            return _base("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of, settled=settled)

    if settled == 0:
        return _base("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of)

    return _base("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, settled=settled,
                 pending=pending, pending_date=pdate)
