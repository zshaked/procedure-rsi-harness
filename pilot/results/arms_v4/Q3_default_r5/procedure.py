import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

CFG = {
    "roll_nonbusiness": False,      # non-business as_of -> previous business day
    "min_level": 3,
    "future_outcome": "REQUEST_INFO",
    "legal_hold_outcome": "ESCALATE",
    "no_email_outcome": "REQUEST_AUTHORIZATION",
    "mismatch_outcome": "ESCALATE",
    "pending_window_days": 90,
    "size_limit": 1_000_000,
    "tolerance": 0.05,
}


def _clean_body(body):
    lines = body.split("\n")
    out = []
    for l in lines:
        s = l.strip()
        if re.match(r"^(from|date|sent|to|subject):", s, re.I) or s.startswith("-----"):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        out.append(l)
    return "\n".join(out)


def _last_day_prev_month(sent):
    first = sent.replace(day=1)
    return first - dt.timedelta(days=1)


def parse_date(body, sent):
    """Returns date or None."""
    b = _clean_body(body)
    low = b.lower()
    # ISO
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # dd-Mon-yyyy / dd Mon yyyy / dd Month yyyy
    m = re.search(r"\b(\d{1,2})[\s-]+" + MON_RE + r"[\s-]+(\d{4})\b", low)
    if m:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    # Month d, yyyy
    m = re.search(MON_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low)
    if m:
        return dt.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    # m/d/yyyy
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    # Month d (no year)
    m = re.search(r"\b" + MON_RE + r"\s+(\d{1,2})\b(?!\s*,?\s*\d{4})", low)
    if m:
        return dt.date(sent.year, MONTHS[m.group(1)], int(m.group(2)))
    # relative
    if re.search(r"(last day of (the )?(last|previous) month|end of (the )?(last|previous) month|month[- ]end|end of month)", low):
        return _last_day_prev_month(sent)
    if "yesterday" in low:
        return sent - dt.timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return sent
    return None


def _claim(body):
    m = re.search(r"(?:we have|we show|our figure is|our records show|figure of|we hold)\s+(-?[\d][\d,]*(?:\.\d+)?)[ \t]?(mm|k|m)?\b", body, re.I)
    if not m:
        return None
    s = m.group(1).replace(",", "")
    mult = {"mm": 1_000_000, "m": 1_000_000, "k": 1000, None: 1}[(m.group(2) or "").lower() or None]
    return int(round(float(s) * mult))


TRACE = []


def respond(request, tools):
    try:
        return _respond(request, tools)
    except ValueError:
        return {"outcome": "REQUEST_INFO", "account_id": None, "instrument_id": None, "as_of": None,
                "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _respond(request, tools):
    del TRACE[:]
    r = request
    sent = dt.date.fromisoformat(r["sent"])
    men = r.get("mentions") or {}
    atext, itext = men.get("account_text"), men.get("instrument_text")

    def out(outcome, **kw):
        d = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
             "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
        d.update(kw)
        return d

    contact = tools.get_contact(r["from"])
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    valid = [e for e in ents if e["expires"] >= r["sent"]]

    # account
    acc = None
    if atext:
        hits = tools.search_accounts(atext)
        if len(hits) != 1:
            return out("REQUEST_INFO")
        acc = hits[0]["id"]
    else:
        ids = {e["account_id"] for e in valid}
        if len(ids) == 1:
            acc = next(iter(ids))
        else:
            return out("REQUEST_AUTHORIZATION" if not valid else "REQUEST_INFO")

    # authorization
    prof = tools.get_client_profile(acc) or {}
    lvl = max([e["level"] for e in valid if e["account_id"] == acc], default=0)
    if lvl < CFG["min_level"]:
        return out("REQUEST_AUTHORIZATION")
    # instrument
    ins = None
    if itext:
        hits = tools.search_instruments(itext)
        if len(hits) != 1:
            return out("REQUEST_INFO", account_id=acc)
        ins = hits[0]["id"]
    else:
        return out("REQUEST_INFO", account_id=acc)

    if prof.get("no_email_confirm"):
        TRACE.append("noemail")
        o = CFG["no_email_outcome"]
        return out(o, **({} if o == "REQUEST_AUTHORIZATION" else {"account_id": acc, "instrument_id": ins}))
    if prof.get("legal_hold"):
        TRACE.append("legalhold")
        return out(CFG["legal_hold_outcome"], account_id=acc, instrument_id=ins)

    # date
    d = parse_date(r["body"], sent)
    assumed = False
    if d is None:
        d = sent
        assumed = True
    elif d > sent:
        TRACE.append("future")
        return out(CFG["future_outcome"], account_id=acc, instrument_id=ins)
    cal = tools.get_calendar(d.isoformat())
    if not cal["business_day"]:
        if not CFG["roll_nonbusiness"]:
            TRACE.append("nonbiz")
            return out("REQUEST_INFO", account_id=acc, instrument_id=ins)
        if True:
            TRACE.append("nonbiz")
            d = dt.date.fromisoformat(cal["previous_business_day"])
    iso = d.isoformat()

    # position
    ledger = tools.get_ledger(acc, ins)
    splits = tools.get_corporate_actions(ins)
    qty = 0
    if splits and splits[0]["date"] <= iso:
        TRACE.append("split_applies")
    elif splits:
        TRACE.append("split_later")
    if any(t["date"] == iso for t in ledger):
        TRACE.append("txn_on_asof")
    for t in ledger:
        if t["date"] <= iso:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= iso:
                    q *= s["ratio"]
            qty += q
    if qty == 0:
        return out("NOT_HELD", account_id=acc, instrument_id=ins, as_of=iso, as_of_assumed=assumed)

    pend, pdate = None, None
    allpend = 0
    for x in tools.get_instructions(acc, ins):
        if x["status"] == "matched" and x["settle_date"] > iso:
            allpend += x["qty"]
            sd = dt.date.fromisoformat(x["settle_date"])
            if (sd - d).days <= CFG["pending_window_days"]:
                pend = (pend or 0) + x["qty"]
                pdate = x["settle_date"] if pdate is None else min(pdate, x["settle_date"])

    esc = dict(account_id=acc, instrument_id=ins, as_of=iso, as_of_assumed=assumed, settled=qty)
    if abs(qty) >= CFG["size_limit"]:
        TRACE.append("size")
        return out("ESCALATE", **esc)

    c = _claim(r["body"])
    if c is not None:
        TRACE.append("claim=%s qty=%s" % (c, qty))
        tol = CFG["tolerance"] * abs(qty)
        if abs(c - qty) > tol and c != qty + allpend:
            return out("ESCALATE", **esc)
    return out("CONFIRMED", account_id=acc, instrument_id=ins, as_of=iso, as_of_assumed=assumed,
               settled=qty, pending=pend, pending_date=pdate)
