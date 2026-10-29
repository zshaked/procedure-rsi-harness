import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 3
NO_DATE_POLICY = "info"
WEEKEND_POLICY = "info"
EMPTY_POLICY = "not_held"      # not_held | info
FUTURE_POLICY = "info"


def _out(outcome, **kw):
    d = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    d.update(kw)
    return d


def _last_dom(y, m):
    n = dt.date(y + (m == 12), m % 12 + 1, 1)
    return (n - dt.timedelta(days=1)).day


def parse_date(body, sent):
    """Return (date or None, kind). kind: 'explicit' | 'relative' | None."""
    s = dt.date.fromisoformat(sent)
    t = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t.split("Date:")[-1] if False else _strip_fwd(t))
    tt = _strip_fwd(t)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", tt)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), "explicit"
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", tt)
    if m and m[2].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2].lower()], int(m[1])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", tt)
    if m:
        return _mk(int(m[3]), int(m[1]), int(m[2])), "explicit"
    m = re.search(r"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", tt)
    if m and m[2][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), "explicit"
    m = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", tt)
    if m and m[1][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), "explicit"
    low = tt.lower()
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"(last day of last month|end of last month|month[- ]end|end of the month)", low):
        first = s.replace(day=1)
        return first - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", low):
        return s, "relative"
    return None, None


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _strip_fwd(t):
    out = []
    for l in t.split("\n"):
        if l.startswith(("From:", "Date:", "----------")):
            continue
        out.append(l)
    return "\n".join(out)


def _resolve_account(req, tools):
    m = req.get("mentions") or {}
    txt = m.get("account_text")
    cands = []
    if txt:
        cands = tools.search_accounts(txt)
    if not txt:
        for pat in (r"ACC-\d+", r"SA-\d+"):
            f = re.findall(pat, req.get("body", ""))
            if f:
                cands = tools.search_accounts(f[0])
                break
    if len(cands) == 1:
        return cands[0]["id"]
    return None


def _resolve_instrument(req, tools):
    m = req.get("mentions") or {}
    txt = m.get("instrument_text")
    if not txt:
        return None
    c = tools.search_instruments(txt)
    if len(c) == 1:
        return c[0]["id"]
    return None


def _authorized(req, acct, tools):
    c = tools.get_contact(req["from"])
    if not c:
        return False
    prof = tools.get_client_profile(acct)
    if not prof:
        return False
    dom = req["from"].split("@")[-1].lower()
    if dom not in [d.lower() for d in prof["domains"]]:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct and e["level"] >= MIN_LEVEL and e["expires"] >= req["sent"]:
            return True
    return False


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _out("REQUEST_INFO")


def _respond(request, tools):
    acct = _resolve_account(request, tools)
    if not acct:
        return _out("REQUEST_INFO")
    if not _authorized(request, acct, tools):
        return _out("REQUEST_AUTHORIZATION")
    prof = tools.get_client_profile(acct)
    inst = _resolve_instrument(request, tools)
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", account_id=acct, instrument_id=inst)
    if not inst:
        return _out("REQUEST_INFO", account_id=acct)
    sent = request["sent"]
    d, kind = parse_date(request["body"], sent)
    assumed = False
    if d is None:
        if NO_DATE_POLICY == "info":
            return _out("REQUEST_INFO", account_id=acct, instrument_id=inst)
        d = dt.date.fromisoformat(tools.get_calendar(sent)["previous_business_day"])
        assumed = True
    else:
        if d > dt.date.fromisoformat(sent) and FUTURE_POLICY == "info":
            return _out("REQUEST_INFO", account_id=acct, instrument_id=inst)
        cal = tools.get_calendar(d.isoformat())
        if not cal["business_day"]:
            if WEEKEND_POLICY == "info":
                return _out("REQUEST_INFO", account_id=acct, instrument_id=inst)
            d = dt.date.fromisoformat(cal["previous_business_day"])
    as_of = d.isoformat()
    ledger = tools.get_ledger(acct, inst)
    if not ledger and EMPTY_POLICY == "info":
        return _out("REQUEST_INFO", account_id=acct, instrument_id=inst, as_of=as_of)
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for sp in splits:
            if sp["date"] <= as_of and t["date"] < sp["date"]:
                q *= sp["ratio"]
        total += q
    if total <= 0:
        return _out("NOT_HELD", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed)
    pend = [x for x in tools.get_instructions(acct, inst)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    pq = sum(x["qty"] for x in pend) or None
    pdt = max(x["settle_date"] for x in pend) if pend else None
    return _out("CONFIRMED", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
                settled=total, pending=pq, pending_date=pdt if pq else None)
