import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

MISMATCH_TOL = 0.10  # relative tolerance for client-stated figure


def _clean_body(body):
    b = body
    b = re.sub(r"This email and any attachments.*", "", b, flags=re.S)
    if "Forwarded message" in b:
        # drop forwarded header block (From:/Date: lines)
        b = re.sub(r"-+ Forwarded message -+\s*\n(From:.*\n)?(Date:.*\n)?", "", b)
    return b


def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date, found). Date is the literal date requested (not business-day adjusted)."""
    s = dt.date.fromisoformat(sent)
    t = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2]))
    mon = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + mon + r",?[\s\-]+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    m = re.search(r"\b" + mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[1].lower()], int(m[2]))
    tl = t.lower()
    if re.search(r"(last day of (the )?(last|previous) month|end of (the )?(last|previous) month|"
                 r"month[- ]end|end of month|end of the month)", tl):
        return _last_day_prev_month(s)
    if re.search(r"(end of (the )?(last|previous) quarter|last day of (the )?(last|previous) quarter|quarter[- ]end)", tl):
        qm = ((s.month - 1) // 3) * 3 + 1
        return dt.date(s.year, qm, 1) - dt.timedelta(days=1)
    if re.search(r"(end of (the )?(last|previous) week)", tl):
        d = s - dt.timedelta(days=(s.weekday() + 3) % 7 or 7)
        return d
    m = re.search(r"last (mon|tue|wed|thu|fri|sat|sun)[a-z]*", tl)
    if m:
        wd = WEEKDAYS[m[1]]
        d = s - dt.timedelta(days=1)
        while d.weekday() != wd:
            d -= dt.timedelta(days=1)
        return d
    if "yesterday" in tl:
        return s - dt.timedelta(days=1)
    if re.search(r"\b(today|current(ly)?|latest|right now|as of now)\b", tl):
        return s
    return None


def parse_qty(text):
    m = re.search(r"(?:records show|figure is|we have|we show|our books show|books show)\s+(-?[\d,\.]*\d)(k|mm|m)?\b", text, re.I)
    if not m:
        return None
    num = m[1].rstrip(".,")
    suf = (m[2] or "").lower()
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    if suf == "k":
        v *= 1000
    elif suf in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def _resolve_account(tools, text):
    if not text:
        return []
    r = tools.search_accounts(text)
    return r


def respond(request, tools):
    body = _clean_body(request["body"])
    sent = request["sent"]
    men = request.get("mentions") or {}
    out = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
           "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def done(o, **kw):
        out["outcome"] = o
        out.update(kw)
        return out

    domain = request["from"].split("@")[-1].lower()
    contact = tools.get_contact(request["from"])
    if not contact:
        return done("REQUEST_AUTHORIZATION")
    ents = tools.get_entitlements(contact["contact_id"])

    def doms(aid):
        return [d.lower() for d in (tools.get_client_profile(aid) or {}).get("domains", [])]

    accs = tools.search_accounts(men["account_text"]) if men.get("account_text") else []
    if len(accs) != 1:
        # account missing / unknown / ambiguous: ask for info if the sender is a recognised party
        known = set(a["id"] for a in accs) | set(e["account_id"] for e in ents)
        if any(domain in doms(a) for a in known):
            return done("REQUEST_INFO")
        return done("REQUEST_AUTHORIZATION")
    aid = accs[0]["id"]
    prof = tools.get_client_profile(aid) or {}
    ok = any(e["account_id"] == aid and e["level"] >= 2 and e["expires"] >= sent for e in ents)
    if ok and domain not in doms(aid):
        ok = False
    if not ok:
        return done("REQUEST_AUTHORIZATION")

    insts = tools.search_instruments(men["instrument_text"]) if men.get("instrument_text") else []
    if len(insts) != 1:
        return done("REQUEST_INFO")
    iid = insts[0]["id"]

    d = parse_date(body, sent)
    if d is None:
        return done("REQUEST_INFO", account_id=aid, instrument_id=iid)
    s = dt.date.fromisoformat(sent)
    assumed = False
    if d > s:
        return done("REQUEST_INFO", account_id=aid, instrument_id=iid)
    if d == s:
        d = dt.date.fromisoformat(tools.get_calendar(sent)["previous_business_day"])
        assumed = True

    # roll to previous business day if not a business day
    cal = tools.get_calendar(d.isoformat())
    if not cal["business_day"]:
        d = dt.date.fromisoformat(cal["previous_business_day"])
    as_of = d.isoformat()

    ledger = tools.get_ledger(aid, iid)
    splits = tools.get_corporate_actions(iid)
    total = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for sp in splits:
            if sp["date"] <= as_of and t["date"] < sp["date"]:
                q *= sp["ratio"]
        total += q

    if prof.get("legal_hold"):
        return done("ESCALATE", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed, settled=total)

    if total == 0:
        return done("NOT_HELD", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed)

    pend = [x for x in tools.get_instructions(aid, iid) if x["status"] == "matched" and x["settle_date"] > as_of]
    pq = sum(x["qty"] for x in pend)
    pending = pq or None
    pdate = max(x["settle_date"] for x in pend) if pend else None

    stated = parse_qty(body)
    if stated is not None:
        good = any(abs(stated - ref) <= MISMATCH_TOL * abs(ref) for ref in (total, total + pq))
        if not good:
            return done("ESCALATE", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed, settled=total)

    return done("CONFIRMED", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed,
                settled=total, pending=pending, pending_date=pdate)
