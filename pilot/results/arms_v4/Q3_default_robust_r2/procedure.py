import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
D = dt.date
PEND_DAYS = 30


def _strip_forward(body):
    return re.sub(r"-{3,}\s*Forwarded message\s*-{3,}\s*\nFrom:[^\n]*\nDate:[^\n]*\n", "", body)


def _mon(s):
    return MONTHS.get(s[:3].lower())


def parse_date(body, sent):
    """Return (date|None, found_phrase_bool)."""
    b = _strip_forward(body)
    s = D.fromisoformat(sent)
    low = b.lower()
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), True
    if re.search(r"(end of last month|last day of last month|month-end|month end|end of the previous month|last day of the previous month)", low):
        first = s.replace(day=1)
        return first - dt.timedelta(days=1), True
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    if m:
        try:
            return D(int(m[1]), int(m[2]), int(m[3])), True
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[-\s]([A-Za-z]{3,9})[-,\s]+(\d{4})\b", b)
    if m and _mon(m[2]):
        try:
            return D(int(m[3]), _mon(m[2]), int(m[1])), True
        except ValueError:
            pass
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b)
    if m and _mon(m[1]):
        try:
            return D(int(m[3]), _mon(m[1]), int(m[2])), True
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        a, c, y = int(m[1]), int(m[2]), int(m[3])
        try:
            if a > 12:
                return D(y, c, a), True
            return D(y, a, c), True
        except ValueError:
            pass
    return None, False


def parse_qty(body):
    b = _strip_forward(body)
    m = re.search(r"(?:we have|we show|records show|our figure is|figure of)\s+(-?[\d][\d,]*(?:\.\d+)?)\s*(k|mm|m)?\b", b, re.I)
    if not m:
        return None
    n = float(m[1].replace(",", ""))
    suf = (m[2] or "").lower()
    if suf == "k":
        n *= 1000
    elif suf in ("mm", "m"):
        n *= 1000000
    return int(round(n))


def split_adjust(ledger, splits, as_of):
    tot = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for sp in splits:
            if t["date"] < sp["date"] <= as_of:
                q *= sp["ratio"]
        tot += q
    return tot


def resolve_account(text, tools):
    if not text:
        return []
    return [a["id"] for a in tools.search_accounts(text)]


def resolve_instrument(text, tools):
    if not text:
        return []
    return [i["id"] for i in tools.search_instruments(text)]


def base(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return base("REQUEST_INFO")


def _respond(request, tools):
    m = request.get("mentions") or {}
    sent = request["sent"]
    accs = resolve_account(m.get("account_text"), tools)
    contact = tools.get_contact(request["from"])
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    valid = [e for e in ents if e["expires"] >= sent]
    if not m.get("account_text"):
        cand = {e["account_id"] for e in ents}
        accs = sorted(cand) if len(cand) == 1 else []
    if len(accs) > 1:
        return base("REQUEST_INFO")
    if not accs:
        return base("REQUEST_INFO")
    acc = accs[0]
    prof = tools.get_client_profile(acc) or {}
    ent = [e for e in valid if e["account_id"] == acc]
    if not ent or max(e["level"] for e in ent) < 3:
        return base("REQUEST_AUTHORIZATION")
    insts = resolve_instrument(m.get("instrument_text"), tools)
    if len(insts) != 1:
        return base("REQUEST_INFO", account_id=acc)
    inst = insts[0]
    d, found = parse_date(request["body"], sent)
    assumed = False
    if d is None:
        d = D.fromisoformat(sent)
        assumed = True
    as_of = d.isoformat()
    if not tools.get_calendar(as_of)["business_day"]:
        return base("REQUEST_INFO", account_id=acc, instrument_id=inst)
    if prof.get("no_email_confirm"):
        return base("REQUEST_AUTHORIZATION", account_id=acc, instrument_id=inst, as_of=as_of,
                    as_of_assumed=assumed)
    if prof.get("legal_hold"):
        return base("ESCALATE", account_id=acc, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
                    settled=split_adjust(tools.get_ledger(acc, inst), tools.get_corporate_actions(inst), as_of))
    led = tools.get_ledger(acc, inst)
    splits = tools.get_corporate_actions(inst)
    settled = split_adjust(led, splits, as_of)
    if settled == 0:
        return base("NOT_HELD", account_id=acc, instrument_id=inst, as_of=as_of, as_of_assumed=assumed)
    stated = parse_qty(request["body"])
    ao = D.fromisoformat(as_of)
    sd = D.fromisoformat(sent)
    open_m = [x for x in sorted(tools.get_instructions(acc, inst), key=lambda x: x["settle_date"])
              if x["status"] == "matched" and D.fromisoformat(x["settle_date"]) > ao]
    if stated is not None and stated != settled and stated != settled + sum(x["qty"] for x in open_m):
        return base("ESCALATE", account_id=acc, instrument_id=inst, as_of=as_of,
                    as_of_assumed=assumed, settled=settled)
    pend = pdate = None
    for x in open_m:
        if D.fromisoformat(x["settle_date"]) <= sd + dt.timedelta(days=PEND_DAYS):
            pend = (pend or 0) + x["qty"]
            pdate = pdate or x["settle_date"]
    return base("CONFIRMED", account_id=acc, instrument_id=inst, as_of=as_of,
                as_of_assumed=assumed, settled=settled, pending=pend, pending_date=pdate)
