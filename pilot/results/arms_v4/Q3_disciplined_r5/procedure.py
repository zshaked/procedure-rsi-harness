import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
FULLM = "January|February|March|April|May|June|July|August|September|October|November|December"
MON_RE = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"

# ---- tunable conventions -------------------------------------------------
LEVEL_REQUIRED = 3
QTY_TOLERANCE = 0.05         # relative tolerance for client-stated figure
PENDING_WINDOW_DAYS = 30     # matched instructions settling within this many days after `sent`
LARGE_POSITION = 1_000_000   # settled >= this always escalates (oracle Q3-0175)


def _d(s):
    return dt.date.fromisoformat(s)


def _num(tok):
    t = tok.strip().lower().replace(",", "")
    mult = 1
    if t.endswith("mm"):
        mult, t = 1_000_000, t[:-2]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    elif t.endswith("k"):
        mult, t = 1_000, t[:-1]
    try:
        return int(round(float(t) * mult))
    except ValueError:
        return None


def parse_claimed(body):
    pats = [r"(?:We have|Our records show|We show|our figure is|figure is)\s+([\d][\d,\.]*\s?(?:mm|MM|k|K|m)?)\b",
            r"([\d][\d,\.]*\s?(?:mm|MM|k|K|m)?)\s+(?:shares|units)\b"]
    for p in pats:
        m = re.search(p, body)
        if m:
            v = _num(m.group(1).rstrip(". "))
            if v is not None:
                return v
    return None


def parse_date(body, sent):
    """returns (date or None, kind) kind in explicit|relative|none|unparsed"""
    s = _d(sent)
    b = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", re.sub(r"Date: \d{4}-\d{2}-\d{2}", "", b))
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
    m = re.search(r"\b(\d{1,2})-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(\d{4})\b", b)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2])), "explicit"
    m = re.search(r"\b(\d{1,2}) (" + FULLM + r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec),? (\d{4})\b", b)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1])), "explicit"
    m = re.search(r"\b(" + FULLM + r") (\d{1,2}),? (\d{4})\b", b)
    if m:
        return dt.date(int(m[3]), MONTHS[m[1].lower()[:3]], int(m[2])), "explicit"
    if re.search(r"\byesterday\b", b, re.I):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"(end of last month|last day of last month|month-end|month end|end of the month|end of month)", b, re.I):
        first = s.replace(day=1)
        return first - dt.timedelta(days=1), "relative"
    return None, "none"


def _next_bd(tools, d):
    while not tools.get_calendar(d.isoformat())["business_day"]:
        d += dt.timedelta(days=1)
    return d


def _pending(tools, acc, ins, as_of, sent):
    tot, dates = 0, []
    for x in tools.get_instructions(acc, ins):
        if x["status"] != "matched":
            continue
        sd = _d(x["settle_date"])
        if sd > as_of and sd <= sent + dt.timedelta(days=PENDING_WINDOW_DAYS):
            tot += x["qty"]
            dates.append(x["settle_date"])
    return tot, (_next_bd(tools, _d(min(dates))).isoformat() if dates else None)


def _settled(tools, acc, ins, as_of):
    splits = tools.get_corporate_actions(ins)
    tot = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] > as_of.isoformat():
            continue
        q = t["qty"]
        for sp in splits:
            if t["date"] < sp["date"] <= as_of.isoformat():
                q *= sp["ratio"]
        tot += q
    return tot


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def decide(request, tools):
    sent = request["sent"]
    body = request["body"]
    m = request.get("mentions") or {}
    at, it = m.get("account_text"), m.get("instrument_text")

    # account resolution
    if not at:
        return _blank("REQUEST_AUTHORIZATION"), "no_account"
    accs = tools.search_accounts(at)
    if len(accs) == 0:
        return _blank("REQUEST_INFO"), "account_unknown"
    if len(accs) > 1:
        return _blank("REQUEST_INFO"), "account_ambiguous"
    acc = accs[0]["id"]

    # authorization
    contact = tools.get_contact(request["from"])
    ok = False
    if contact:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= LEVEL_REQUIRED and e["expires"] >= sent:
                ok = True
    if not ok:
        return _blank("REQUEST_AUTHORIZATION"), "auth_level"

    # instrument
    if not it:
        return _blank("REQUEST_INFO", account_id=acc), "instrument_missing"
    inss = tools.search_instruments(it)
    if len(inss) != 1:
        return _blank("REQUEST_INFO", account_id=acc), "instrument_unresolved"
    ins = inss[0]["id"]

    # date
    d, kind = parse_date(body, sent)
    assumed = False
    if d is None:
        d, assumed = _d(sent), True
    if not tools.get_calendar(d.isoformat())["business_day"]:
        return _blank("REQUEST_INFO", account_id=acc, instrument_id=ins), "non_business_day"
    as_of = d

    if as_of > _d(sent):
        return _blank("REQUEST_INFO", account_id=acc, instrument_id=ins), "future_date"

    prof = tools.get_client_profile(acc) or {}
    if prof.get("legal_hold"):
        return _blank("ESCALATE", account_id=acc, instrument_id=ins), "legal_hold"
    if prof.get("no_email_confirm"):
        return _blank("REQUEST_AUTHORIZATION"), "no_email_confirm"

    settled = _settled(tools, acc, ins, as_of)
    if settled == 0:
        return _blank("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of.isoformat(),
                      as_of_assumed=assumed), "not_held"
    if settled >= LARGE_POSITION:
        return _blank("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of.isoformat(),
                      as_of_assumed=assumed, settled=settled), "large_position"
    claimed = parse_claimed(body)
    claim_branch = None
    if claimed is not None:
        allpend = sum(x["qty"] for x in tools.get_instructions(acc, ins)
                      if x["status"] == "matched" and _d(x["settle_date"]) > as_of)

        def close(f):
            return abs(claimed - f) <= QTY_TOLERANCE * max(abs(f), 1) and not (f == 0 and claimed != 0)
        if close(settled):
            claim_branch = "claim_match"
        elif allpend and close(settled + allpend):
            claim_branch = "claim_incl_pending"
        else:
            br = "zero_vs_claim" if settled == 0 else "qty_mismatch"
            return _blank("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of.isoformat(),
                          as_of_assumed=assumed, settled=settled), br

    pend, pdate = _pending(tools, acc, ins, as_of, _d(sent))
    return _blank("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of.isoformat(),
                  as_of_assumed=assumed, settled=settled, pending=pend or None,
                  pending_date=pdate), (claim_branch or ("confirm_pending" if pend else "confirmed"))


def respond(request, tools):
    return decide(request, tools)[0]
