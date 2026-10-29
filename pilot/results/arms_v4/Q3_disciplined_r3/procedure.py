"""Procedure for the confirmation desk. respond(request, tools) -> dict; decide() also returns the deciding branch."""
import re
import datetime as dt
import calendar

# ---- parameters / conventions -------------------------------------------------
MIN_LEVEL = 3            # entitlement level required to disclose
PEND_MATERIAL = 0.01     # matched-unsettled quantity is reported only if at least this fraction of settled (oracle: 6% reported, 0.37% not)
PEND_STATUS = "matched"
SIZE_ESCALATE = 2000000  # positions at least this large always go to escalation (oracle: 1.22M ok, 2.79M escalated)

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


# ---- text parsing ---------------------------------------------------------------
def _strip_noise(body, mentions):
    lines = body.split("\n")
    out = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if ln.strip().startswith("---------- Forwarded"):
            i += 1
            while i < n and lines[i].strip() != "":
                i += 1
            continue
        out.append(ln)
        i += 1
    text = "\n".join(out)
    text = re.sub(r"This email and any attachments are confidential[^\n]*", " ", text)
    for k in ("account_text", "instrument_text"):
        v = (mentions or {}).get(k)
        if v:
            text = text.replace(v, " ")
    return text


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _parse_date(text, sent):
    """Return (date|None, kind)."""
    s = dt.date.fromisoformat(sent)
    t = text
    low = t.lower()
    if re.search(r"(?:end of last month|last day of last month|last day of the previous month|end of the previous month|end of prior month|last month[- ]end|previous month[- ]end)", low):
        return s.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"\b(?:month[- ]end|end of (?:the )?month|end-of-month|last day of (?:the )?month)\b", low):
        return s.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"\b(?:today|close of business today)\b", low):
        return s, "relative"
    m = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", t)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, ("iso" if d else "bad")
    m = re.search(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[-\s/]+(" + MON + r")\.?[-\s,/]+(\d{4})(?!\d)", t, re.I)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        return d, ("text" if d else "bad")
    m = re.search(r"\b(" + MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)", t, re.I)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        return d, ("text" if d else "bad")
    m = re.search(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _mk(y, a, b) if a <= 12 else _mk(y, b, a)
        return d, ("text" if d else "bad")
    return None, "none"


_QTY_RE = re.compile(
    r"(?:we (?:have|hold|show)|our records show|records show|our figure is|figure is|our books show|books show|our records indicate)\s+(?:a (?:position|holding) of\s+)?(-?\d[\d,]*(?:\.\d+)?(?:k|mm|m)?)(?![a-z0-9])(?!\s*[-/]\d)",
    re.I)


def _parse_qty(text):
    """Return (value, tolerance) where tolerance is the rounding slack of an abbreviated figure."""
    m = _QTY_RE.search(text)
    if not m:
        return None, 0
    tok = m.group(1).replace(",", "")
    mm = re.match(r"^(-?[\d.]+)(k|mm|m)?$", tok, re.I)
    if not mm:
        return None, 0
    num = mm.group(1)
    suf = (mm.group(2) or "").lower()
    mult = 1000 if suf == "k" else (1000000 if suf in ("mm", "m") else 1)
    val = int(round(float(num) * mult))
    tol = 0
    if mult > 1:
        dec = len(num.split(".")[1]) if "." in num else 0
        tol = mult / (10 ** dec) / 2.0
    return val, tol


# ---- helpers ------------------------------------------------------------------------
def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _split_adjusted_settled(ledger, splits, as_of):
    """Sum of ledger rows dated <= as_of; each row multiplied by the ratio of every split with
    row.date < split.date <= as_of."""
    tot = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        tot += q
    return tot


def _pending(instrs, as_of, settled):
    """Matched instructions settling after as_of (even if already due by the email date); reported
    only when material relative to the settled position."""
    rows = [x for x in instrs if x["status"] == PEND_STATUS and x["settle_date"] > as_of]
    if not rows:
        return None, None
    total = sum(x["qty"] for x in rows)
    if total < PEND_MATERIAL * abs(settled):
        return None, None
    return total, min(x["settle_date"] for x in rows)


def _all_matched_after(instrs, as_of):
    """Everything matched but not yet settled at as_of (what a client's trade-date figure adds to settled)."""
    return sum(x["qty"] for x in instrs if x["status"] == PEND_STATUS and x["settle_date"] > as_of)


# ---- the procedure -------------------------------------------------------------------------
def decide(request, tools):
    """Return (response, branch). branch names the rule that decided the outcome; every case whose
    account had to be inferred from the sender's entitlements is branch 'implicit_account'."""
    resp, br = _decide(request, tools)
    if br.startswith("implicit_account:"):
        br = "implicit_account"
    return resp, br


def _decide(request, tools):
    m = request.get("mentions") or {}
    sent = request["sent"]
    sender = request["from"]

    # 1. account
    acc_text = m.get("account_text")
    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    account_id = None
    implicit = False
    if acc_text:
        hits = tools.search_accounts(acc_text)
        if len(hits) > 1:
            return _blank("REQUEST_INFO"), "ambiguous_account"
        if len(hits) == 0:
            return _blank("REQUEST_INFO"), "unknown_account"
        account_id = hits[0]["id"]
    else:
        accts = sorted(set(e["account_id"] for e in ents))
        if len(accts) != 1:
            return _blank("REQUEST_INFO"), "no_account"
        account_id = accts[0]
        implicit = True
    pre = "implicit_account:" if implicit else ""

    # 2. authorization
    if not contact:
        return _blank("REQUEST_AUTHORIZATION"), pre + "auth_unknown_sender"
    mine = [e for e in ents if e["account_id"] == account_id]
    if not mine:
        return _blank("REQUEST_AUTHORIZATION"), pre + "auth_no_entitlement"
    best = max(mine, key=lambda e: (e["level"], e["expires"]))
    if best["level"] < MIN_LEVEL:
        return _blank("REQUEST_AUTHORIZATION"), pre + "auth_level"
    if not any(e["level"] >= MIN_LEVEL and e["expires"] >= sent for e in mine):
        return _blank("REQUEST_AUTHORIZATION"), pre + "auth_expired"

    # 3. instrument
    ins_text = m.get("instrument_text")
    if not ins_text:
        return _blank("REQUEST_INFO"), pre + "missing_instrument"
    ih = tools.search_instruments(ins_text)
    if len(ih) == 0:
        return _blank("REQUEST_INFO"), pre + "unknown_instrument"
    if len(ih) > 1:
        return _blank("REQUEST_INFO"), pre + "ambiguous_instrument"
    instrument_id = ih[0]["id"]

    # 4. date (must be a past/current business day)
    text = _strip_noise(request["body"], m)
    d, kind = _parse_date(text, sent)
    assumed = False
    if d is None:
        if kind == "bad":
            return _blank("REQUEST_INFO"), pre + "bad_date"
        d, assumed = dt.date.fromisoformat(sent), True
    as_of = d.isoformat()
    if d > dt.date.fromisoformat(sent):
        return _blank("REQUEST_INFO"), pre + "future_date"
    if not tools.get_calendar(as_of)["business_day"]:
        return _blank("REQUEST_INFO"), pre + "non_business_day"

    # 5. client restrictions (account-level)
    prof = tools.get_client_profile(account_id) or {}
    if prof.get("no_email_confirm"):
        return _blank("REQUEST_AUTHORIZATION"), pre + "no_email_confirm"
    base = _blank("ESCALATE")
    base.update(account_id=account_id, instrument_id=instrument_id)
    if prof.get("legal_hold"):
        base.update(as_of=as_of, as_of_assumed=assumed)
        return base, pre + "legal_hold"

    # 6. figures
    ledger = tools.get_ledger(account_id, instrument_id)
    splits = tools.get_corporate_actions(instrument_id)
    settled = _split_adjusted_settled(ledger, splits, as_of)
    raw = _split_adjusted_settled(ledger, [], as_of)
    instrs = tools.get_instructions(account_id, instrument_id)
    pend, pend_date = _pending(instrs, as_of, settled)
    qty, tol = _parse_qty(text)

    # stated figure agrees if it equals settled, or settled plus everything matched-but-unsettled at as_of
    if qty is not None and abs(qty - settled) > tol and abs(qty - (settled + _all_matched_after(instrs, as_of))) > tol:
        base.update(as_of=as_of, as_of_assumed=assumed, settled=settled)
        return base, pre + "qty_mismatch"

    if abs(settled) >= SIZE_ESCALATE:
        base.update(as_of=as_of, as_of_assumed=assumed, settled=settled)
        return base, pre + "size_escalation"

    out = _blank("NOT_HELD")
    out.update(account_id=account_id, instrument_id=instrument_id, as_of=as_of, as_of_assumed=assumed)
    if settled == 0:
        return out, pre + "not_held"

    out["outcome"] = "CONFIRMED"
    out["settled"] = settled
    if pend:
        out["pending"] = pend
        out["pending_date"] = pend_date
    # branch: the least-evidenced convention that shaped the reply
    if settled != raw:
        br = "confirm_split"
    elif assumed:
        br = "confirm_assumed_date"
    elif qty is not None:
        br = "confirm_qty_match"
    elif pend:
        br = "confirm_pending"
    else:
        br = "confirm_plain"
    return out, pre + br


def respond(request, tools):
    try:
        return decide(request, tools)[0]
    except Exception:  # never crash on an unforeseen phrasing: ask the client to clarify
        return _blank("REQUEST_INFO")
