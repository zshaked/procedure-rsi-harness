import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+"


def _body(request):
    b = request.get("body") or ""
    lines = []
    for ln in b.split("\n"):
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|Sent|To|Subject):", s):
            continue
        if s.startswith("This email and any attachments"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month_end_before(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Return (date or None, found_any_marker)."""
    t = text
    low = t.lower()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), True
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})[a-z]*-(\d{4})\b", t)
    if m and m[2].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2].lower()], int(m[1])), True
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", t)
    if m and m[2][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), True
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m and m[1][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        d = _mk(y, a, b)
        if d is None:
            d = _mk(y, b, a)
        return d, True
    if re.search(r"end of last month|last day of last month|end of the last month|last month[- ]end", low):
        return _month_end_before(sent), True
    if re.search(r"month[- ]end|end of (the )?month|last day of (the )?month|end of last month", low):
        return _month_end_before(sent), True
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b", low):
        return sent, True
    return None, False


def parse_qty(s):
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(mm|m|k)?\b", s, re.I)
    if not m:
        return None
    n = float(m[1].replace(",", ""))
    suf = (m[2] or "").lower()
    if suf == "k":
        n *= 1000
    elif suf in ("m", "mm"):
        n *= 1000000
    return int(round(n))


def client_figure(body):
    m = re.search(r"(?:we show|our figure is|records show|we have|we hold|shows?)\s+(\d[\d,]*(?:\.\d+)?\s*(?:mm|m|k)?)(?![a-z])", body, re.I)
    if m:
        return parse_qty(m[1])
    return None


def _prev_bd(tools, d):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d
    return dt.date.fromisoformat(c["previous_business_day"])


def position(tools, acct, inst, as_of):
    led = tools.get_ledger(acct, inst)
    sp = tools.get_corporate_actions(inst)
    iso = as_of.isoformat()
    tot = 0
    for t in led:
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in sp:
            if s["date"] <= iso and t["date"] < s["date"]:
                q *= s["ratio"]
        tot += q
    return tot, bool(led)


def R(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    men = request.get("mentions") or {}
    sent = dt.date.fromisoformat(request["sent"])
    body = _body(request)
    at, it = men.get("account_text"), men.get("instrument_text")
    if not at or not it:
        return R("REQUEST_INFO")
    accs = tools.search_accounts(at)
    ins = tools.search_instruments(it)
    if len(accs) != 1 or len(ins) != 1:
        return R("REQUEST_INFO")
    aid, iid = accs[0]["id"], ins[0]["id"]

    d, found = parse_date(body, sent)
    assumed = False
    if d is None:
        d = sent
        assumed = True
    if d > sent:
        return R("REQUEST_INFO")
    asof = _prev_bd(tools, d)

    # authorization
    sender = (request.get("from") or "").lower()
    c = tools.get_contact(sender)
    prof = tools.get_client_profile(aid) or {}
    ok = False
    if c:
        for e in tools.get_entitlements(c["contact_id"]):
            if e["account_id"] == aid and e["level"] >= 2 and e["expires"] >= request["sent"]:
                ok = True
    dom = sender.split("@")[-1]
    if dom not in [x.lower() for x in prof.get("domains", [])]:
        ok = False
    if not ok:
        return R("REQUEST_AUTHORIZATION")

    if prof.get("legal_hold"):
        return R("ESCALATE", account_id=aid, instrument_id=iid)
    if prof.get("no_email_confirm"):
        return R("ESCALATE", account_id=aid, instrument_id=iid)

    settled, had = position(tools, aid, iid, asof)
    fig = client_figure(body)
    pend = [x for x in tools.get_instructions(aid, iid) if x["status"] == "matched" and x["settle_date"] > asof.isoformat()]
    ptot = sum(x["qty"] for x in pend)
    if fig is not None and fig != settled + ptot:
        return R("ESCALATE", account_id=aid, instrument_id=iid)
    if settled == 0 and ptot == 0:
        return R("NOT_HELD", account_id=aid, instrument_id=iid, as_of=asof.isoformat(), as_of_assumed=assumed)
    kw = {}
    if pend:
        kw["pending"] = sum(x["qty"] for x in pend)
        kw["pending_date"] = max(x["settle_date"] for x in pend)
    return R("CONFIRMED", account_id=aid, instrument_id=iid, as_of=asof.isoformat(),
             as_of_assumed=assumed, settled=settled, **kw)
