"""Procedure for the confirmation desk (induced from histories; see NOTES.md).

respond(request, tools) -> dict ; decide(request, tools) -> (dict, branch)
Standard library + the `tools` argument only.  Deterministic.
"""
import re
import datetime as dt

# ---------------------------------------------------------------- parameters
MIN_LEVEL = 3             # entitlement level needed (histories: 3 ok, 1-2 not)
QTY_TOLERANCE = 0.03      # |claim - figure| / |figure| allowed before ESCALATE (oracle Q13: 4% escalates; Q12 (2%) unexplained)
PENDING_HORIZON_DAYS = 45  # matched instructions settling within this many days of the email are reported
#                            (history 7d yes, 81d no; oracle Q5: 20d yes; exact edge unknown, 45 = middle of [20, 81))

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _mnum(s):
    return _MONTHS.get(s.lower()[:3])


# ---------------------------------------------------------------- parsing
def _strip_headers(body):
    out = []
    for line in body.splitlines():
        if re.match(r"^\s*(From|Date|Sent|To|Cc|Subject):", line):
            continue
        out.append(line)
    return "\n".join(out)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except Exception:
        return None


def parse_date(body, sent):
    """Return (date|None, kind).  Relative phrases are relative to `sent`."""
    sent_d = dt.date.fromisoformat(sent)
    b = _strip_headers(body)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        d = _mk(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return d, "iso"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:  # month/day/year (US) - the histories use 1/16/2026 and 1/27/2026
        d = _mk(int(m[3]), int(m[1]), int(m[2]))
        if d:
            return d, "mdy"
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3,9})-(\d{4})\b", b)
    if m and _mnum(m[2]):
        d = _mk(int(m[3]), _mnum(m[2]), int(m[1]))
        if d:
            return d, "dmy-dash"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", b)
    if m and _mnum(m[2]):
        d = _mk(int(m[3]), _mnum(m[2]), int(m[1]))
        if d:
            return d, "dmy"
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b)
    if m and _mnum(m[1]):
        d = _mk(int(m[3]), _mnum(m[1]), int(m[2]))
        if d:
            return d, "mdy-text"
    low = b.lower()
    if re.search(r"\byesterday\b", low):
        return sent_d - dt.timedelta(days=1), "yesterday"
    if re.search(r"\b(last day of last month|end of last month|last day of the previous month|"
                 r"end of the previous month|end of prior month|month[- ]?end|end of month|"
                 r"last day of the month)\b", low):
        return sent_d.replace(day=1) - dt.timedelta(days=1), "month-end"
    if re.search(r"\b(today|this morning)\b", low):
        return sent_d, "today"
    if re.search(r"\b(year[- ]?end|end of (last )?year|last day of (last|the previous) year)\b", low):
        return dt.date(sent_d.year - 1, 12, 31), "year-end"
    if re.search(r"\b(quarter[- ]?end|end of (last|the previous) quarter)\b", low):
        q = (sent_d.month - 1) // 3  # quarters elapsed this year
        return (dt.date(sent_d.year - 1, 12, 31) if q == 0 else
                dt.date(sent_d.year, 3 * q + 1, 1) - dt.timedelta(days=1)), "quarter-end"
    m = re.search(r"\blast (mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", low)
    if m:
        target = _WEEKDAYS[m[1]]
        back = (sent_d.weekday() - target) % 7 or 7
        return sent_d - dt.timedelta(days=back), "last-weekday"
    return None, "none"


def parse_qty_token(tok):
    t = tok.replace(",", "").replace(" ", "").lower()
    mult = 1
    if t.endswith("mm"):
        mult, t = 1_000_000, t[:-2]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    elif t.endswith("k"):
        mult, t = 1_000, t[:-1]
    return int(round(float(t) * mult))


_CLAIM_RE = re.compile(
    r"(?:we have|we show|we hold|our records show|records show|our books show|our figure is|"
    r"our records indicate|we record)\s+(-?\d[\d,]*(?:\.\d+)?\s?(?:k|mm|m)?)\b", re.I)


def parse_claim(body):
    b = _strip_headers(body)
    m = _CLAIM_RE.search(b)
    if not m:
        return None
    try:
        return parse_qty_token(m[1])
    except Exception:
        return None


# ---------------------------------------------------------------- helpers
def _is_business_day(tools, d):
    return bool(tools.get_calendar(d.isoformat())["business_day"])


def _settled(tools, acct, inst, as_of):
    """Sum of the raw ledger over all sub-accounts up to and including as_of,
    restating pre-split quantities for splits effective on or before as_of."""
    led = tools.get_ledger(acct, inst)
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in led:
        td = dt.date.fromisoformat(t["date"])
        if td > as_of:
            continue
        q = t["qty"]
        for s in splits:
            sd = dt.date.fromisoformat(s["date"])
            if sd <= as_of and td < sd:
                q = q * s["ratio"]
        total += q
    return total, bool(led)


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- the decision
def decide(request, tools):
    sent = request["sent"]
    sent_d = dt.date.fromisoformat(sent)
    body = request.get("body", "")
    mentions = request.get("mentions") or {}
    acc_text = mentions.get("account_text")
    ins_text = mentions.get("instrument_text")

    # 1. account
    cands = tools.search_accounts(acc_text) if acc_text else []
    if acc_text and len(cands) > 1:
        return _blank("REQUEST_INFO"), "account_ambiguous"
    if acc_text and not cands:
        return _blank("REQUEST_INFO"), "account_not_found"
    acct = cands[0]["id"] if cands else None

    # 2. authorization (before anything about the instrument or the date)
    m_from = re.search(r"[\w.+'-]+@[\w.-]+", request.get("from") or "")
    contact = tools.get_contact(m_from.group(0)) if m_from else None
    if not contact:
        return _blank("REQUEST_AUTHORIZATION"), "auth_unknown_sender"
    if acct is None:
        # no account named ("our fund"): oracle Q3 - the desk infers it from the sender's entitlement
        accts = sorted({e["account_id"] for e in tools.get_entitlements(contact["contact_id"])})
        if not accts:
            return _blank("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
        if len(accts) > 1:
            return _blank("REQUEST_INFO"), "account_unspecified_multi"
        acct = accts[0]
    ents = [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == acct]
    if not ents:
        return _blank("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    if max(e["level"] for e in ents) < MIN_LEVEL:
        return _blank("REQUEST_AUTHORIZATION"), "auth_level"
    if not any(e["level"] >= MIN_LEVEL and e["expires"] >= sent for e in ents):
        return _blank("REQUEST_AUTHORIZATION"), "auth_expired"

    # 3. instrument
    if not ins_text:
        return _blank("REQUEST_INFO"), "no_instrument"
    insts = tools.search_instruments(ins_text)
    if len(insts) != 1:
        return _blank("REQUEST_INFO"), "instrument_unresolved"
    inst = insts[0]["id"]

    # 4. as-of date (oracle Q7: future date -> ask; oracle Q8: non-business date -> ask which date they want)
    d, kind = parse_date(body, sent)
    assumed = False
    if d is None:
        d, assumed = sent_d, True
    elif d > sent_d:
        return _blank("REQUEST_INFO"), "future_date"
    as_of = d
    if not _is_business_day(tools, as_of):
        return _blank("REQUEST_INFO"), "non_business_date"

    # 5. client profile flags (checked after the date: oracle Q8; no_email_confirm -> authorization: oracle Q4)
    prof = tools.get_client_profile(acct) or {}
    if prof.get("legal_hold"):
        return _blank("ESCALATE", account_id=acct, instrument_id=inst), "legal_hold"
    if prof.get("no_email_confirm"):
        return _blank("REQUEST_AUTHORIZATION"), "no_email_confirm"

    # 6. figure
    settled, _has = _settled(tools, acct, inst, as_of)
    claim = parse_claim(body)

    pend, pend_date = 0, None
    pend_list = []
    for x in tools.get_instructions(acct, inst):
        if x["status"] != "matched":
            continue
        sd = dt.date.fromisoformat(x["settle_date"])
        if sd > as_of:
            pend_list.append((sd, x["qty"]))
    rep = [(sd, q) for sd, q in pend_list
           if sent_d <= sd <= sent_d + dt.timedelta(days=PENDING_HORIZON_DAYS)]
    if rep:
        pend = sum(q for _, q in rep)
        pend_date = min(sd for sd, _ in rep).isoformat()

    base = dict(account_id=acct, instrument_id=inst, as_of=as_of.isoformat(), as_of_assumed=assumed)

    if settled == 0:
        return _blank("NOT_HELD", **base), "not_held"

    if settled < 0:
        return _blank("ESCALATE", settled=settled, **base), "negative_position"

    if claim is not None:
        def close(a, b):
            return abs(a - b) <= QTY_TOLERANCE * abs(b)
        all_pend = sum(q for _, q in pend_list)
        if not (close(claim, settled) or (all_pend and close(claim, settled + all_pend))):
            return _blank("ESCALATE", settled=settled, **base), "qty_mismatch"

    out = _blank("CONFIRMED", settled=settled, **base)
    if pend:
        out["pending"] = pend
        out["pending_date"] = pend_date
        return out, "confirmed_pending"
    return out, "confirmed"


def respond(request, tools):
    return decide(request, tools)[0]
