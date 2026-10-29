"""Operations desk procedure (induced from histories).  Deterministic, stdlib + tools only."""
import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}

MIN_LEVEL = 2          # entitlement level needed (level 1 -> request authorization)
FUTURE_DATE_OK = False  # an as-of date after the email was sent cannot be confirmed
SPLIT_APPLIES_ON_DATE = True   # split applies when split.date <= as_of
SETTLED_INCLUSIVE = True       # ledger rows dated == as_of count


# ---------------------------------------------------------------- parsing
def _strip_noise(body):
    b = re.sub(r"-{3,}\s*Forwarded message\s*-{3,}\s*\n(?:From:[^\n]*\n)?(?:Date:[^\n]*\n)?", "", body)
    b = re.sub(r"This email and any attachments are confidential[^\n]*", "", b)
    return b


def _mon(s):
    return MONTHS.get(s[:3].lower()) if s and s[:3].lower() in MONTHS else None


def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def _last_day_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date|None, kind).  kind in explicit|relative|none."""
    b = _strip_noise(body)
    cands = []  # (pos, date)
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", b):
        d = _mk(m.group(1), m.group(2), m.group(3))
        if d: cands.append((m.start(), d))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b):
        a, c = int(m.group(1)), int(m.group(2))
        d = _mk(m.group(3), a, c) if a <= 12 else _mk(m.group(3), c, a)
        if d: cands.append((m.start(), d))
    for m in re.finditer(r"\b(\d{1,2})-([A-Za-z]{3,9})-(\d{4})\b", b):
        mo = _mon(m.group(2))
        d = _mk(m.group(3), mo, m.group(1)) if mo else None
        if d: cands.append((m.start(), d))
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", b):
        mo = _mon(m.group(1))
        d = _mk(m.group(3), mo, m.group(2)) if mo else None
        if d: cands.append((m.start(), d))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]{3,9})\.?,? (\d{4})\b", b):
        mo = _mon(m.group(2))
        d = _mk(m.group(3), mo, m.group(1)) if mo else None
        if d: cands.append((m.start(), d))
    if cands:
        cands.sort(key=lambda x: x[0])
        return cands[0][1], "explicit"
    low = b.lower()
    s = sent
    if re.search(r"\b(last day of (the )?(last|previous) month|end of (the )?(last|previous) month|"
                 r"last day of (the )?month|end of (the )?month|month[- ]end)\b", low):
        return _last_day_prev_month(s), "relative"
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", low):
        return s, "relative"
    return None, "none"


def _num(tok):
    t = tok.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    if t.endswith("mm"):
        mult, t = 1_000_000, t[:-2]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    elif t.endswith("k"):
        mult, t = 1_000, t[:-1]
    try:
        return int(round(float(t) * mult))
    except Exception:
        return None


def parse_stated(body):
    b = _strip_noise(body)
    m = re.search(r"(?:figure is|records show|we show|we have|show)\s+(\d[\d,]*(?:\.\d+)?\s*(?:mm|k|m)?)(?![\w])", b, re.I)
    if not m:
        return None
    return _num(m.group(1))


# ---------------------------------------------------------------- lookups
def _sent(req):
    return dt.date.fromisoformat(req["sent"])


def _domain(email):
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def settled_qty(tools, acct, inst, as_of):
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if (t["date"] <= as_of) if SETTLED_INCLUSIVE else (t["date"] < as_of):
            q = t["qty"]
            for s in splits:
                eff = (s["date"] <= as_of) if SPLIT_APPLIES_ON_DATE else (s["date"] < as_of)
                if eff and t["date"] < s["date"]:
                    q *= s["ratio"]
            total += q
    return total


def pending_info(tools, acct, inst, as_of):
    ins = [x for x in tools.get_instructions(acct, inst)
           if x["status"] == "matched" and x["settle_date"] > as_of]
    if not ins:
        return None, None
    return sum(x["qty"] for x in ins), max(x["settle_date"] for x in ins)  # oracle (Q2-0089): latest date


# ---------------------------------------------------------------- decision
def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _figures(request, tools, acct, inst):
    """as_of, assumed, settled for resolvable acct/inst; None parts if the date is unusable."""
    sent = _sent(request)
    d, kind = parse_date(request["body"], sent)
    assumed = False
    if d is None:
        d, assumed = sent, True
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]
    return d, as_of, assumed, settled_qty(tools, acct, inst, as_of)


def _resolve_instrument(tools, mentions):
    it = (mentions.get("instrument_text") or "").strip()
    if not it:
        return None, "instrument_missing"
    ins = tools.search_instruments(it)
    if len(ins) == 0:
        return None, "instrument_unknown"
    if len(ins) > 1:
        return None, "instrument_ambiguous"
    return ins[0]["id"], None


def _decide(request, tools):
    mentions = request.get("mentions") or {}
    sent = _sent(request)

    # 1. account resolution (identifiers first: unresolved / ambiguous account -> ask)
    at = (mentions.get("account_text") or "").strip()
    if not at:
        return _blank("REQUEST_INFO"), "account_missing"
    accs = tools.search_accounts(at)
    if len(accs) == 0:
        return _blank("REQUEST_INFO"), "account_unknown"
    if len(accs) > 1:
        return _blank("REQUEST_INFO"), "account_ambiguous"
    acct = accs[0]["id"]

    # 2. authorization: known contact, live entitlement of sufficient level, sender domain on file
    contact = tools.get_contact(request["from"])
    profile = tools.get_client_profile(acct) or {}
    if not contact:
        return _blank("REQUEST_AUTHORIZATION"), "auth_no_contact"
    ents = [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == acct]
    if not ents:
        return _blank("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    live = [e for e in ents if e["expires"] >= request["sent"]]
    if not live:
        return _blank("REQUEST_AUTHORIZATION"), "auth_expired"
    if max(e["level"] for e in live) < MIN_LEVEL:
        return _blank("REQUEST_AUTHORIZATION"), "auth_level"
    if _domain(request["from"]) not in [d.lower() for d in profile.get("domains", [])]:
        return _blank("REQUEST_AUTHORIZATION"), "auth_domain"

    inst, inst_err = _resolve_instrument(tools, mentions)

    # 3. account-level flags: the desk does not confirm, a human takes over
    if profile.get("no_email_confirm"):  # oracle (Q2-0105): must go through authorization, not by email
        return _blank("REQUEST_AUTHORIZATION"), "no_email_confirm"
    if profile.get("legal_hold"):  # oracle (Q2-0096): escalate
        r = _blank("ESCALATE"); r.update(account_id=acct, instrument_id=inst)
        if inst:
            d, as_of, assumed, settled = _figures(request, tools, acct, inst)
            r.update(as_of=as_of, as_of_assumed=assumed, settled=settled)
        return r, "legal_hold"

    # 4. instrument resolution
    if inst is None:
        return _blank("REQUEST_INFO"), inst_err

    # 5. as-of date
    d, kind = parse_date(request["body"], sent)
    assumed = False
    if d is None:
        d, assumed = sent, True
    if d > sent and not FUTURE_DATE_OK:
        return _blank("REQUEST_INFO"), "future_date"
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    # 6. figures
    settled = settled_qty(tools, acct, inst, as_of)
    stated = parse_stated(request["body"])
    pend, pend_date = pending_info(tools, acct, inst, as_of)
    base = {"account_id": acct, "instrument_id": inst, "as_of": as_of, "as_of_assumed": assumed,
            "settled": settled, "pending": None, "pending_date": None}
    if settled == 0:  # oracle (Q2-0157): a stated figure does not turn "not held" into an escalation
        r = _blank("NOT_HELD"); r.update(base); r["settled"] = None
        return r, "not_held"
    # oracle (Q2-0097) + history Q2-0006: the client's figure is compared with settled + pending
    # (matched, not yet settled), not with settled alone
    if stated is not None and stated != settled + (pend or 0):
        r = _blank("ESCALATE"); r.update(base)
        return r, "qty_mismatch"
    r = _blank("CONFIRMED"); r.update(base)
    if pend:
        r["pending"], r["pending_date"] = pend, pend_date
        return r, "confirmed_pending"
    return r, "confirmed"


def decide(request, tools):
    try:
        return _decide(request, tools)
    except Exception:  # never crash: hand to a human
        return _blank("ESCALATE"), "error"


def respond(request, tools):
    return decide(request, tools)[0]
