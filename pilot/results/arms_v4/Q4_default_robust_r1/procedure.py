import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

TOL = 0.10  # relative tolerance between the client's stated figure and ours


# ---------------------------------------------------------------- parsing
def _num(s):
    s = s.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    if s.endswith("mm"):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("bn") or s.endswith("b"):
        mult, s = 1_000_000_000, s.rstrip("bn")
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def parse_claimed(body):
    pats = [
        r"records show\s+(-?\d[\d,\.]*(?:mm|k|m)?)(?![A-Za-z])",
        r"figure is\s+(-?\d[\d,\.]*(?:mm|k|m)?)(?![A-Za-z])",
        r"\bwe (?:have|show|hold)\s+(-?\d[\d,\.]*(?:mm|k|m)?)(?![A-Za-z])",
        r"\bshow\s+(-?\d[\d,\.]*(?:mm|k|m)?)(?![A-Za-z])",
    ]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            t = m.group(1).rstrip(".,")
            v = _num(t)
            if v is not None:
                return v
    return None


def _last_day_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date or None). Dates relative to `sent`."""
    b = body
    # explicit ISO
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    # remove forwarded header 'Date: ...' line
    b2 = re.sub(r"(?m)^(From|Date|Sent|To|Subject):.*$", "", b)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b2)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # 27-Jan-2026 / 27 January 2026 / 3 Jan 2026
    m = re.search(r"\b(\d{1,2})[\s\-]([A-Za-z]{3,9})\.?,?[\s\-](\d{4})\b", b2)
    if m and m.group(2)[:3].lower() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        except ValueError:
            pass
    # January 27, 2026
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b2)
    if m and m.group(1)[:3].lower() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        except ValueError:
            pass
    # 1/23/2026
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b2)
    if m:
        a, c, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        for mo, d in ((a, c), (c, a)):
            try:
                return dt.date(y, mo, d)
            except ValueError:
                continue
    low = b2.lower()
    if re.search(r"(last day of (?:the )?last month|end of (?:the )?last month|last month[- ]end|end of (?:the )?previous month|last day of (?:the )?previous month|month[- ]end)", low):
        return _last_day_prev_month(sent)
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return sent
    return None


def find_account_text(req):
    t = (req.get("mentions") or {}).get("account_text")
    if t and t.strip():
        return t.strip()
    m = re.search(r"\b(ACC-\d+|SA-\d+)\b", req.get("body", ""))
    return m.group(1) if m else None


def find_instrument_text(req):
    t = (req.get("mentions") or {}).get("instrument_text")
    if t and t.strip():
        return t.strip()
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", req.get("body", ""))
    return m.group(1) if m else None


# ---------------------------------------------------------------- position
def compute_position(tools, acct, inst, as_of):
    iso = as_of.isoformat()
    splits = [c for c in tools.get_corporate_actions(inst) if c.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= iso and t["date"] < s["date"]:
                q = q * s["ratio"]
        total += q
    pend, pdate = 0, None
    for x in tools.get_instructions(acct, inst):
        if x["status"] == "matched" and x["settle_date"] > iso:
            pend += x["qty"]
            if pdate is None or x["settle_date"] > pdate:
                pdate = x["settle_date"]
    return total, pend, pdate


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- main
def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    body = request.get("body", "")
    sender = request.get("from", "").strip().lower()
    domain = sender.split("@")[-1]

    # --- resolve account
    at = find_account_text(request)
    accts = tools.search_accounts(at) if at else []
    # --- resolve instrument
    it = find_instrument_text(request)
    insts = tools.search_instruments(it) if it else []

    # --- authorization of sender
    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    def recognised(acc_id):
        """sender is a known contact, writing from a domain registered for the account,
        holding an unexpired entitlement on it (any level)."""
        prof = tools.get_client_profile(acc_id)
        if not prof or not contact:
            return None
        if domain not in [d.lower() for d in prof["domains"]]:
            return None
        for e in ents:
            if e["account_id"] == acc_id and e["expires"] >= sent.isoformat():
                return e
        return None

    if at is not None and accts:
        cands = [a["id"] for a in accts]
    else:
        cands = [e["account_id"] for e in ents]

    if not any(recognised(c) for c in cands):
        return _resp("REQUEST_AUTHORIZATION")

    # --- need unique account / instrument
    if len(accts) != 1 or len(insts) != 1:
        return _resp("REQUEST_INFO")
    acct = accts[0]["id"]
    inst = insts[0]["id"]

    if recognised(acct)["level"] < 2:
        return _resp("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(acct)
    as_of_raw = parse_date(body, sent)
    if as_of_raw is None:
        return _resp("REQUEST_INFO", account_id=acct, instrument_id=inst)
    if as_of_raw > sent:
        return _resp("REQUEST_INFO", account_id=acct, instrument_id=inst)
    as_of = as_of_raw
    cal = tools.get_calendar(as_of.isoformat())
    if not cal["business_day"]:
        as_of = dt.date.fromisoformat(cal["previous_business_day"])

    settled, pend, pdate = compute_position(tools, acct, inst, as_of)
    claimed = parse_claimed(body)

    base = dict(account_id=acct, instrument_id=inst, as_of=as_of.isoformat(), as_of_assumed=False)

    if prof and prof["legal_hold"]:
        return _resp("ESCALATE", settled=settled, **base)

    if settled == 0 and pend == 0:
        return _resp("NOT_HELD", **base)

    if claimed is not None:
        ref = settled + pend
        if ref == 0:
            mismatch = claimed != 0
        else:
            mismatch = abs(claimed - ref) / abs(ref) > TOL
        if mismatch:
            return _resp("ESCALATE", settled=settled, **base)

    return _resp("CONFIRMED", settled=settled,
                 pending=pend or None, pending_date=pdate if pend else None, **base)
