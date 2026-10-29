import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
PENDING_HORIZON_DAYS = 10
LARGE_POSITION = 1000000


def _d(s):
    return dt.date.fromisoformat(s)


def _boiler(body):
    out = []
    for l in body.split("\n"):
        if l.startswith("This email and any attachments"):
            break
        out.append(l)
    return "\n".join(out)


def _parse_date(body, sent):
    """returns (date|None, found_phrase_bool)"""
    b = _boiler(body)
    # drop forwarded header lines (Date: ...)
    b = re.sub(r"(?m)^(From|Date):.*$", "", b)
    low = b.lower()
    if re.search(r"(last day of last month|end of last month|month-end|month end|end of the last month|end of previous month)", low):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1), True
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\b(today|end of day today)\b", low):
        return sent, True
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])), True
        except ValueError:
            return None, True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        try:
            return dt.date(int(m[3]), int(m[1]), int(m[2])), True
        except ValueError:
            return None, True
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]*(\d{4})\b", b)
    if m and m[2][:3].lower() in MONTHS:
        try:
            return dt.date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), True
        except ValueError:
            return None, True
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})\b", b)
    if m and m[1][:3].lower() in MONTHS:
        try:
            return dt.date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), True
        except ValueError:
            return None, True
    return None, False


def _num(s):
    s = s.strip().lower().replace(",", "")
    mult = 1
    if s.endswith("mm") or s.endswith("m"):
        mult = 1000000
        s = s.rstrip("m")
    elif s.endswith("k"):
        mult = 1000
        s = s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def _stated_qty(body):
    b = _boiler(body)
    m = re.search(r"(?:we have|we show|our records show|our figure is|figure is)\s+(-?[\d.,]+\s?(?:k|mm|m)?)\b", b, re.I)
    if m:
        return _num(m.group(1))
    return None


def _biz(date, tools):
    c = tools.get_calendar(date.isoformat())
    if c["business_day"]:
        return date
    return _d(c["previous_business_day"])


def _resolve_account(m, body, tools):
    txt = m.get("account_text")
    if not txt:
        mm = re.search(r"ACC-\d{5}", body)
        if mm:
            txt = mm.group(0)
    if not txt:
        return None, "none"
    hits = tools.search_accounts(txt)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if len(hits) == 0:
        return None, "none"
    return None, "ambiguous"


def _resolve_instrument(m, tools):
    txt = m.get("instrument_text")
    if not txt:
        return None, "none"
    hits = tools.search_instruments(txt)
    ids = sorted({h["id"] for h in hits})
    if len(ids) == 1:
        return ids[0], "ok"
    if not ids:
        return None, "none"
    return None, "ambiguous"


def _adjusted_total(account, instrument, as_of, tools):
    splits = [s for s in tools.get_corporate_actions(instrument) if s["date"] <= as_of.isoformat()]
    total = 0
    for t in tools.get_ledger(account, instrument):
        if t["date"] <= as_of.isoformat():
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"]:
                    q *= s["ratio"]
            total += q
    return total


def respond(request, tools):
    def out(outcome, **kw):
        r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
             "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
        r.update(kw)
        return r

    sent = _d(request["sent"])
    body = request["body"]
    m = request.get("mentions") or {}
    contact = tools.get_contact(request["from"])

    acc, astat = _resolve_account(m, body, tools)
    if astat == "none" and contact and not (m.get("account_text")):
        ents = tools.get_entitlements(contact["contact_id"])
        accs = sorted({e["account_id"] for e in ents})
        if len(accs) == 1:
            acc, astat = accs[0], "ok"
    if astat == "ambiguous":
        return out("REQUEST_INFO")
    if astat != "ok":
        return out("REQUEST_INFO")

    # authorization
    authorized = False
    if contact:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= 3 and e["expires"] >= sent.isoformat():
                authorized = True
    if not authorized:
        return out("REQUEST_AUTHORIZATION")
    prof = tools.get_client_profile(acc) or {}

    ins, istat = _resolve_instrument(m, tools)
    if istat != "ok":
        return out("REQUEST_INFO", account_id=acc)

    d, found = _parse_date(body, sent)
    assumed = False
    if d is None:
        if found:
            return out("REQUEST_INFO", account_id=acc, instrument_id=ins)
        d, assumed = sent, True
    if d > sent:
        return out("REQUEST_INFO", account_id=acc, instrument_id=ins)
    if not tools.get_calendar(d.isoformat())["business_day"]:
        return out("REQUEST_INFO", account_id=acc, instrument_id=ins)
    if prof.get("no_email_confirm"):
        return out("REQUEST_AUTHORIZATION")

    if prof.get("legal_hold"):
        return out("ESCALATE", account_id=acc, instrument_id=ins, as_of=d.isoformat(), as_of_assumed=assumed)

    total = _adjusted_total(acc, ins, d, tools)
    stated = _stated_qty(body)
    base = dict(account_id=acc, instrument_id=ins, as_of=d.isoformat(), as_of_assumed=assumed)
    if total < 0:
        return out("ESCALATE", **base)
    if stated is not None and stated != total:
        return out("ESCALATE", settled=total, **base)
    if total == 0:
        return out("NOT_HELD", **base)
    if total >= LARGE_POSITION:
        return out("ESCALATE", settled=total, **base)

    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and sent.isoformat() <= x["settle_date"] <= (sent + dt.timedelta(days=PENDING_HORIZON_DAYS)).isoformat()
            and x["settle_date"] > d.isoformat()]
    pq, pd = None, None
    if pend:
        pd = min(x["settle_date"] for x in pend)
        pq = sum(x["qty"] for x in pend if x["settle_date"] == pd)
    return out("CONFIRMED", settled=total, pending=pq, pending_date=pd, **base)
