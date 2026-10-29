import re, datetime as dt

# ---- tunables / conventions ----
LARGE_POSITION = 1_000_000  # oracle Q3-0145: positions "that size" always escalate (2.79M); history confirms up to 855k
PEND_WINDOW_DAYS = 30        # matched instruction reported as pending if settle_date <= sent + this (no history evidence)
QTY_TOL = 0.05               # relative tolerance on stated vs settled (oracle Q3-0132: 2% off is fine; history Q3-0012: 7% off escalates)
MIN_LEVEL = 3
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"


def _d(s):
    return dt.date.fromisoformat(s)


def _body(request):
    b = request.get("body") or ""
    b = re.sub(r"-+ Forwarded message -+\s*\nFrom:.*\nDate:.*\n", "", b)
    return b


def parse_date(text, sent):
    """returns (date or None, kind) kind in explicit|relative|none"""
    s = _d(sent)
    t = text
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})-" + MON + r"-(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2])), "explicit"
    m = re.search(r"\b(\d{1,2})\s+" + MON + r"\s+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])), "explicit"
    m = re.search(r"\b" + MON + r"\s+(\d{1,2}),?\s+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[1].lower()], int(m[2])), "explicit"
    low = t.lower()
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"(end of last month|last day of (the )?last month|last day of (the )?previous month|end of (the )?previous month|month[- ]end|last day of last month)", low):
        return s.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", low):
        return s, "relative"
    return None, "none"


def parse_qty(text):
    """stated quantity from body or None"""
    m = re.search(r"(?:records show|have|show|figure is|We show|We have)\s+(-?[\d,]*\.?\d+)\s*(k|mm|m)?\b", text, re.I)
    if not m:
        return None
    raw = m[1].replace(",", "")
    v = float(raw)
    u = (m[2] or "").lower()
    if u == "k":
        v *= 1e3
    elif u in ("mm", "m"):
        v *= 1e6
    return int(round(v))


def strip_sig(text):
    return text.split("\n\nThis email and any attachments")[0]


def holdings(tools, acct, inst, as_of):
    led = tools.get_ledger(acct, inst)
    acts = [a for a in tools.get_corporate_actions(inst) if a["date"] <= as_of]
    tot = 0
    for t in led:
        if t["date"] <= as_of:
            q = t["qty"]
            for a in acts:
                if t["date"] < a["date"]:
                    q *= a["ratio"]
            tot += q
    return tot, bool(led)


def decide(request, tools):
    m = request.get("mentions") or {}
    sent = request["sent"]
    body = strip_sig(_body(request))
    base = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def out(o, br, **kw):
        r = dict(base); r["outcome"] = o; r.update(kw); return r, br

    # account resolution
    at = m.get("account_text")
    c = tools.get_contact(request["from"])
    ents = tools.get_entitlements(c["contact_id"]) if c else []
    inferred = False
    if at:
        accts = tools.search_accounts(at)
        if len(accts) != 1:
            return out("REQUEST_INFO", "account_ambiguous" if len(accts) > 1 else "account_unknown")
        acct = accts[0]["id"]
    else:
        # no account named ("our fund"): infer from the sender's sole entitlement (oracle Q3-0062)
        ids = sorted({e["account_id"] for e in ents})
        if len(ids) == 1:
            acct = ids[0]; inferred = True
        elif len(ids) > 1:
            return out("REQUEST_INFO", "account_missing_multi")
        else:
            return out("REQUEST_AUTHORIZATION", "no_account")

    # authorization
    ok = False
    for e in ents:
        if e["account_id"] == acct and e["level"] >= MIN_LEVEL and e["expires"] >= sent:
            ok = True
    if not ok:
        return out("REQUEST_AUTHORIZATION", "auth_level_inferred" if inferred else "auth_level")

    it = m.get("instrument_text")
    insts = tools.search_instruments(it) if it else []
    if len(insts) != 1:
        return out("REQUEST_INFO", "instrument_missing" if not it else ("instrument_ambiguous" if insts else "instrument_unknown"), account_id=acct)
    inst = insts[0]["id"]

    # date (oracle Q3-0076 + history Q3-0022: a non-business-day date -> ask which date they want)
    d, kind = parse_date(body, sent)
    assumed = False
    if d is None:
        d = _d(sent); assumed = True
    asof = d.isoformat()
    if not tools.get_calendar(asof)["business_day"]:
        return out("REQUEST_INFO", "date_nonbusiness", account_id=acct)

    prof = tools.get_client_profile(acct) or {}
    if prof.get("legal_hold"):
        return out("ESCALATE", "legal_hold", account_id=acct, instrument_id=inst)
    if prof.get("no_email_confirm"):
        return out("REQUEST_AUTHORIZATION", "no_email_confirm")

    settled, has = holdings(tools, acct, inst, asof)
    if settled == 0:
        return out("NOT_HELD", "not_held_stated" if parse_qty(body) is not None else "not_held",
                   account_id=acct, instrument_id=inst, as_of=asof, as_of_assumed=assumed)
    stated = parse_qty(body)
    allp = [x for x in tools.get_instructions(acct, inst)
            if x["status"] == "matched" and x["settle_date"] > asof]
    total = settled + sum(x["qty"] for x in allp)
    if stated is not None and abs(stated - settled) > QTY_TOL * abs(settled):
        matches_total = allp and abs(stated - total) <= QTY_TOL * abs(total)
        if not matches_total:
            br = "qty_mismatch"
            return out("ESCALATE", br, account_id=acct, instrument_id=inst, as_of=asof,
                       as_of_assumed=assumed, settled=settled)
        qbr = "_totalmatch"
    else:
        qbr = ""
    if settled == 0:
        return out("NOT_HELD", "not_held", account_id=acct, instrument_id=inst, as_of=asof, as_of_assumed=assumed)
    if settled >= LARGE_POSITION:
        return out("ESCALATE", "large_position", account_id=acct, instrument_id=inst, as_of=asof,
                   as_of_assumed=assumed, settled=settled)
    pend = [x for x in allp if _d(x["settle_date"]) <= _d(sent) + dt.timedelta(days=PEND_WINDOW_DAYS)]
    pq = sum(x["qty"] for x in pend) or None
    pd_ = min(x["settle_date"] for x in pend) if pend else None
    return out("CONFIRMED", ("confirmed_pending" if pend else "confirmed") + qbr, account_id=acct, instrument_id=inst,
               as_of=asof, as_of_assumed=assumed, settled=settled, pending=pq, pending_date=pd_)


def respond(request, tools):
    return decide(request, tools)[0]
