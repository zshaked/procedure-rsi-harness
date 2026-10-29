import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _mon(s):
    return MONTHS.get(s[:3].lower())


def _num(s):
    s = s.replace(",", "").strip().lower()
    mult = 1
    if s.endswith("mm"):
        mult, s = 1000000, s[:-2]
    elif s.endswith("m"):
        mult, s = 1000000, s[:-1]
    elif s.endswith("k"):
        mult, s = 1000, s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def _stated(body):
    m = re.search(r"(?:we show|figure is|records show|we have|our books show|we hold)\s+([\d][\d,\.]*\s?(?:mm|k|m)?)\b", body, re.I)
    if not m:
        return None
    return _num(m.group(1).replace(" ", ""))


def _prev_bd(tools, d):
    iso = d.isoformat()
    c = tools.get_calendar(iso)
    if c["business_day"]:
        return d
    return dt.date.fromisoformat(c["previous_business_day"])


def _parse_date(text, sent):
    """returns date or None (None -> not found)"""
    t = text.strip().rstrip(".").strip()
    tl = t.lower()
    tl = re.sub(r"^(?:close of business|cob|the close of business|end of day|eod)\s+", "", tl)
    if re.search(r"\byesterday\b", tl):
        return sent - dt.timedelta(days=1)
    if re.search(r"\btoday\b", tl):
        return sent
    if re.search(r"(end of last month|last day of last month|month[- ]?end|end of the month|last day of the month|end of previous month|end of prior month)", tl):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", tl)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", tl)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12:
            return dt.date(y, b, a)
        return dt.date(y, a, b)
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[- ]+([a-z]{3,9})\.?,?[- ]+(\d{4})", tl)
    if m and _mon(m[2]):
        return dt.date(int(m[3]), _mon(m[2]), int(m[1]))
    m = re.search(r"([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", tl)
    if m and _mon(m[1]):
        return dt.date(int(m[3]), _mon(m[1]), int(m[2]))
    return None


def _find_date(body, sent):
    for m in re.finditer(r"(?:as of|as at|position date|positions? as of|valuation date)[,:]?\s+([^\n]*)", body, re.I):
        d = _parse_date(m.group(1)[:60], sent)
        if d:
            return d
    return None


def _clean(s):
    return s.strip().strip(".,;:()\"'").strip()


def respond(request, tools):
    body = request.get("body", "") or ""
    sent = dt.date.fromisoformat(request["sent"])
    men = request.get("mentions") or {}

    def info():
        return {"outcome": "REQUEST_INFO", "account_id": None, "instrument_id": None, "as_of": None,
                "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def auth():
        r = info()
        r["outcome"] = "REQUEST_AUTHORIZATION"
        return r

    at, it = men.get("account_text"), men.get("instrument_text")
    if not at:
        return info()
    accs = tools.search_accounts(_clean(at))
    if len(accs) != 1:
        return info()
    acc = accs[0]["id"]

    # authorization
    sender = request["from"].strip().lower()
    ok = False
    prof = tools.get_client_profile(acc) or {}
    contact = tools.get_contact(sender)
    if contact:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= 2 and e["expires"] >= sent.isoformat():
                ok = True
    domain = sender.split("@")[-1]
    if domain not in [d.lower() for d in prof.get("domains", [])]:
        ok = False
    if prof.get("no_email_confirm"):
        ok = False
    if not ok:
        return auth()

    if not it:
        return info()
    inss = tools.search_instruments(_clean(it))
    if len(inss) != 1:
        return info()
    ins = inss[0]["id"]

    # as-of date
    d = _find_date(body, sent)
    assumed = False
    if d is None:
        d, assumed = sent, True
    d = _prev_bd(tools, d)
    asof = d.isoformat()

    # settled quantity
    ledger = [t for t in tools.get_ledger(acc, ins) if t["date"] <= asof]
    splits = tools.get_corporate_actions(ins)
    total = 0
    for t in ledger:
        q = t["qty"]
        for s in splits:
            if s.get("type") == "split" and t["date"] < s["date"] <= asof:
                q *= s["ratio"]
        total += q

    if prof.get("legal_hold"):
        return {"outcome": "ESCALATE", "account_id": acc, "instrument_id": ins, "as_of": asof,
                "as_of_assumed": assumed, "settled": total, "pending": None, "pending_date": None}

    pend = [x for x in tools.get_instructions(acc, ins) if x["status"] == "matched" and x["settle_date"] > asof]
    pq = sum(x["qty"] for x in pend) or None
    pdate = max(x["settle_date"] for x in pend) if pend else None

    if total == 0 and not pq:
        return {"outcome": "NOT_HELD", "account_id": acc, "instrument_id": ins, "as_of": asof,
                "as_of_assumed": assumed, "settled": None, "pending": None, "pending_date": None}

    stated = _stated(body)
    if stated is not None and stated != total and stated != total + (pq or 0):
        return {"outcome": "ESCALATE", "account_id": acc, "instrument_id": ins, "as_of": asof,
                "as_of_assumed": assumed, "settled": total, "pending": None, "pending_date": None}

    return {"outcome": "CONFIRMED", "account_id": acc, "instrument_id": ins, "as_of": asof,
            "as_of_assumed": assumed, "settled": total, "pending": pq, "pending_date": pdate}
