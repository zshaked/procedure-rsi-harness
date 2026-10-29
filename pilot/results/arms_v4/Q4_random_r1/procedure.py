import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
TOL = 0.10


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_body(body):
    lines = []
    for ln in body.splitlines():
        if re.match(r"\s*(from|date|sent|to|subject|cc)\s*:", ln, re.I):
            continue
        if "confidential and intended solely" in ln.lower():
            continue
        lines.append(ln)
    return "\n".join(lines)


def _parse_date(text, sent):
    t = text
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12:
            a, b = b, a
        return dt.date(y, a, b)
    mon = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + mon + r"[\s\-,]+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1]))
    m = re.search(r"\b" + mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[1].lower()[:3]], int(m[2]))
    low = t.lower()
    first = sent.replace(day=1)
    prev_end = first - dt.timedelta(days=1)
    if re.search(r"(last day of (the )?(last|previous) month|end of (the )?(last|previous) month|"
                 r"(last|previous) month[- ]?end|month[- ]?end|end of (the )?month|end of last month)", low):
        return prev_end
    if "yesterday" in low:
        return sent - dt.timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return sent
    return None


def _parse_num(s):
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
    m = re.search(r"(?:our figure is|we show|we have|records show|our records show|we hold)\s+"
                  r"(-?\s?[\d][\d,\.]*\s*(?:mm|k|m)?)\b", body, re.I)
    if m:
        return _parse_num(m[1].replace(" ", ""))
    return None


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"][:10])
    men = request.get("mentions") or {}
    atxt = (men.get("account_text") or "").strip()
    itxt = (men.get("instrument_text") or "").strip()
    sender = request["from"].strip().lower()
    sdom = sender.split("@")[-1]
    body = _clean_body(request["body"])

    # sender entitlements
    contact = tools.get_contact(sender)
    ents = []
    if contact:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["expires"] >= sent.isoformat() and e["level"] >= 2:
                ents.append(e)

    def dom_ok(acc_id):
        p = tools.get_client_profile(acc_id)
        return bool(p) and sdom in [d.lower() for d in p["domains"]]

    accs = tools.search_accounts(atxt) if atxt else []
    if len(accs) != 1:
        # unresolved / ambiguous account
        if not contact:
            return _blank("REQUEST_AUTHORIZATION")
        allents = tools.get_entitlements(contact["contact_id"])
        if not any(dom_ok(e["account_id"]) for e in allents):
            return _blank("REQUEST_AUTHORIZATION")
        return _blank("REQUEST_INFO")
    acc = accs[0]["id"]
    if not (contact and any(e["account_id"] == acc for e in ents) and dom_ok(acc)):
        return _blank("REQUEST_AUTHORIZATION")

    ins = tools.search_instruments(itxt) if itxt else []
    if len(ins) != 1:
        return _blank("REQUEST_INFO", account_id=acc)
    iid = ins[0]["id"]

    prof = tools.get_client_profile(acc)
    if prof and (prof.get("legal_hold") or prof.get("no_email_confirm")):
        return _blank("ESCALATE", account_id=acc, instrument_id=iid)

    d = _parse_date(body, sent)
    if d is None or d > sent:
        return _blank("REQUEST_INFO", account_id=acc, instrument_id=iid)
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    splits = tools.get_corporate_actions(iid)
    settled = 0
    rows = 0
    for t in tools.get_ledger(acc, iid):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if s["date"] <= as_of and t["date"] < s["date"]:
                    q *= s["ratio"]
            settled += q
            rows += 1

    pend, pdate = 0, None
    for x in tools.get_instructions(acc, iid):
        if x["status"] == "matched" and x["settle_date"] > as_of:
            pend += x["qty"]
            if pdate is None or x["settle_date"] > pdate:
                pdate = x["settle_date"]

    stated = _stated(body)
    if stated is not None:
        ref = settled + pend
        if abs(stated - ref) > TOL * max(abs(ref), 1):
            return _blank("ESCALATE", account_id=acc, instrument_id=iid, as_of=as_of, settled=settled)

    if rows == 0 or settled == 0:
        return _blank("NOT_HELD", account_id=acc, instrument_id=iid, as_of=as_of, as_of_assumed=False)
    return _blank("CONFIRMED", account_id=acc, instrument_id=iid, as_of=as_of, settled=settled,
                  pending=pend or None, pending_date=pdate if pend else None)
