import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(k|mm|m)?\b"


def _qty(s, suf):
    v = float(s.replace(",", ""))
    suf = (suf or "").lower()
    if suf == "k":
        v *= 1000
    elif suf in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def _body(req):
    b = req.get("body") or ""
    b = re.sub(r"(?mi)^(from|date|sent|to|subject):.*$", "", b)
    return b


def stated_figure(req):
    b = _body(req)
    pats = [r"our figure is\s+" + NUM, r"we show\s+" + NUM, r"our records show\s+" + NUM,
            r"we have\s+" + NUM + r"\s*(?:shares|units)", r"our books show\s+" + NUM,
            r"(?:figure|position|balance) (?:of|is)\s+" + NUM]
    for p in pats:
        m = re.search(p, b, re.I)
        if m:
            return _qty(m.group(1), m.group(2))
    return None


def _safe(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(req):
    """returns (date or None)"""
    b = _body(req)
    sent = dt.date.fromisoformat(req["sent"])
    t = b
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", t)
    if m and m.group(2).lower() in MONTHS:
        return _safe(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, c, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            return _safe(y, c, a)
        return _safe(y, a, c)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", t)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _safe(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        return _safe(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    tl = t.lower()
    if re.search(r"end of (the )?last month|last day of (the )?last month|month[- ]end|end of (the )?previous month|last month[- ]end", tl):
        return sent.replace(day=1) - dt.timedelta(days=1)
    if "yesterday" in tl:
        return sent - dt.timedelta(days=1)
    if re.search(r"\btoday\b", tl):
        return sent
    return None


def respond(request, tools):
    def out(o, **k):
        r = {"outcome": o, "account_id": None, "instrument_id": None, "as_of": None,
             "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
        r.update(k)
        return r

    men = request.get("mentions") or {}
    at = (men.get("account_text") or "").strip()
    it = (men.get("instrument_text") or "").strip()
    if not at or not it:
        return out("REQUEST_INFO")
    accs = tools.search_accounts(at)
    ins = tools.search_instruments(it)
    if len(accs) != 1 or len(ins) != 1:
        return out("REQUEST_INFO")
    acc = accs[0]["id"]
    inst = ins[0]["id"]

    sent = request["sent"]
    # authorization
    sender = (request.get("from") or "").lower()
    prof = tools.get_client_profile(acc) or {}
    dom = sender.split("@")[-1]
    ok = dom in [d.lower() for d in prof.get("domains", [])]
    if ok:
        c = tools.get_contact(sender)
        ok = False
        if c:
            for e in tools.get_entitlements(c["contact_id"]):
                if e["account_id"] == acc and e["level"] >= 2 and e["expires"] >= sent:
                    ok = True
    if not ok:
        return out("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return out("ESCALATE", account_id=acc, instrument_id=inst)

    # date
    d = parse_date(request)
    assumed = False
    if d is None:
        d = dt.date.fromisoformat(sent)
        assumed = True
    cal = tools.get_calendar(d.isoformat())
    asof = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    # settled
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acc, inst):
        if t["date"] > asof:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= asof and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q

    raw = sum(t["qty"] for t in tools.get_ledger(acc, inst) if t["date"] <= asof)
    if total == 0:
        return out("NOT_HELD", account_id=acc, instrument_id=inst, as_of=asof, as_of_assumed=assumed)

    pend, pdate = None, None
    ms = [x for x in tools.get_instructions(acc, inst) if x["status"] == "matched" and x["settle_date"] > asof]
    if ms:
        pend = sum(x["qty"] for x in ms)
        pdate = max(x["settle_date"] for x in ms)

    stated = stated_figure(request)
    if stated is not None:
        if pend:
            good = stated in (total + pend, raw + pend)
        else:
            good = stated in (total, raw)
        if not good:
            return out("ESCALATE", account_id=acc, instrument_id=inst)
    return out("CONFIRMED", account_id=acc, instrument_id=inst, as_of=asof, as_of_assumed=assumed,
               settled=total, pending=pend, pending_date=pdate)
