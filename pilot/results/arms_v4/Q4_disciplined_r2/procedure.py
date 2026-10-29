"""Operations-desk procedure: confirm a client's holding of a security.

decide(request, tools) -> (response_dict, branch); respond() returns decide()[0].
Standard library + `tools` only. Deterministic.
"""
import datetime as dt
import re

# ----------------------------------------------------------------- parameters
MIN_LEVEL = 2          # entitlement level needed to receive position data (level 1 is not enough)
QTY_TOLERANCE = 0.10   # relative gap between client's figure and ours that triggers ESCALATE
CLAIM_AGAINST = "either"  # client's figure may match settled or settled+pending

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
_MON_ABBR = {k[:3]: v for k, v in _MONTHS.items()}
_MON_ABBR["sept"] = 9


def _month(tok):
    t = tok.lower().rstrip(".")
    if t in _MONTHS:
        return _MONTHS[t]
    if t in _MON_ABBR:
        return _MON_ABBR[t]
    return None


# ----------------------------------------------------------------- text cleaning
def _clean_body(body):
    """Drop forwarded-message headers, quoted headers and disclaimers; keep the request text."""
    out = []
    for ln in body.splitlines():
        s = ln.strip()
        low = s.lower()
        if re.match(r"^-{3,}.*forwarded message.*-{3,}$", low):
            continue
        if re.match(r"^(from|to|cc|date|sent|subject):", low):
            continue
        if low.startswith("this email and any attachments"):
            continue
        out.append(ln)
    return "\n".join(out)


# ----------------------------------------------------------------- dates
def _valid(y, m, d):
    try:
        return dt.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent_iso):
    """Return (date or None, kind). kind in explicit|relative|none."""
    sent = dt.date.fromisoformat(sent_iso)
    t = text
    # ISO
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, "explicit"
    # numeric M/D/YYYY (US order; if first part cannot be a month treat as D/M)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _valid(y, a, b) if a <= 12 else _valid(y, b, a)
        if d:
            return d, "explicit"
    # D-Mon-YYYY / D Month YYYY
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s]+([A-Za-z]{3,9})\.?,?[-\s]+(\d{4})\b", t):
        mo = _month(m.group(2))
        if mo:
            d = _valid(int(m.group(3)), mo, int(m.group(1)))
            if d:
                return d, "explicit"
    # Month D, YYYY
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t):
        mo = _month(m.group(1))
        if mo:
            d = _valid(int(m.group(3)), mo, int(m.group(2)))
            if d:
                return d, "explicit"
    low = t.lower()
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", low):
        return sent, "relative"
    if re.search(r"(month[\s-]*end|end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|end of (the )?month)", low):
        return _last_day_prev_month(sent), "relative"
    return None, "none"


def resolve_as_of(d, tools):
    """Non-business days roll back to the previous business day."""
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


# ----------------------------------------------------------------- quantities
def _to_qty(tok):
    s = tok.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    for suf, mu in (("mm", 10 ** 6), ("bn", 10 ** 9), ("m", 10 ** 6), ("k", 10 ** 3)):
        if s.endswith(suf):
            s = s[: -len(suf)]
            mult = mu
            break
    try:
        v = float(s)
    except ValueError:
        return None
    return int(round(v * mult))


_CLAIM_RE = re.compile(
    r"(?:records\s+show|we\s+have|we\s+show|figure\s+is|our\s+figure|we\s+hold)\s+(?:is\s+)?"
    r"(-?\d[\d,]*(?:\.\d+)?\s*(?:mm|bn|m|k)?)(?![\w])", re.I)


def parse_claim(text):
    m = _CLAIM_RE.search(text)
    if not m:
        return None
    return _to_qty(m.group(1))


# ----------------------------------------------------------------- state helpers
def _sender_email(frm):
    m = re.search(r"<([^>]+)>", frm)
    return (m.group(1) if m else frm).strip().lower()


def _entitled(tools, email, account_id, sent):
    """Return (best valid level or 0, any entitlement row exists)."""
    c = tools.get_contact(email)
    if not c:
        return 0, False, False
    rows = [e for e in tools.get_entitlements(c["contact_id"]) if e["account_id"] == account_id]
    best = 0
    for e in rows:
        if e["expires"] >= sent:
            best = max(best, e["level"])
    return best, bool(rows), True


def position(tools, account_id, instrument_id, as_of_iso):
    """Settled position at as_of: all sub-accounts, split-adjusted."""
    splits = [a for a in tools.get_corporate_actions(instrument_id) if a["type"] == "split"]
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of_iso:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of_iso and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q
    return total


def pending_info(tools, account_id, instrument_id, as_of_iso):
    rows = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > as_of_iso]
    if not rows:
        return None, None
    return sum(x["qty"] for x in rows), max(x["settle_date"] for x in rows)


def _sender_verified_anywhere(tools, email, sent):
    c = tools.get_contact(email)
    if not c:
        return False
    dom = email.split("@")[-1]
    for e in tools.get_entitlements(c["contact_id"]):
        if e["expires"] < sent or e["level"] < MIN_LEVEL:
            continue
        prof = tools.get_client_profile(e["account_id"]) or {}
        if dom in [d.lower() for d in prof.get("domains", [])]:
            return True
    return False


# ----------------------------------------------------------------- decision
def _resp(outcome, account_id=None, instrument_id=None, as_of=None, assumed=False,
          settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


def decide(request, tools):
    sent = request["sent"]
    men = request.get("mentions") or {}
    body = _clean_body(request.get("body", ""))
    email = _sender_email(request.get("from", ""))

    # --- resolve account
    acct_text = men.get("account_text")
    accts = tools.search_accounts(acct_text) if acct_text else []
    if acct_text and len(accts) > 1:
        return _resp("REQUEST_INFO"), "ambiguous_account"
    if not accts:
        # No (resolvable) account named. If the sender cannot be verified for any account at all
        # the desk asks for authorization; otherwise it asks which account is meant.
        if _sender_verified_anywhere(tools, email, sent):
            return _resp("REQUEST_INFO"), "no_account_info"
        return _resp("REQUEST_AUTHORIZATION"), "no_account_auth"
    account_id = accts[0]["id"]

    # --- authorisation
    level, has_row, has_contact = _entitled(tools, email, account_id, sent)
    if not has_contact or not has_row:
        return _resp("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    if level == 0:
        return _resp("REQUEST_AUTHORIZATION"), "auth_expired"
    if level < MIN_LEVEL:
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"
    prof = tools.get_client_profile(account_id) or {}
    dom = email.split("@")[-1]
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return _resp("REQUEST_AUTHORIZATION"), "auth_domain"

    # --- instrument
    ins_text = men.get("instrument_text")
    insts = tools.search_instruments(ins_text) if ins_text else []
    if len(insts) != 1:
        return _resp("REQUEST_INFO", account_id), "missing_instrument"
    instrument_id = insts[0]["id"]

    # --- date
    d, kind = parse_date(body, sent)
    if d is None:
        return _resp("REQUEST_INFO", account_id, instrument_id), "no_date"
    if d > dt.date.fromisoformat(sent):
        # a position date after the day the email was sent cannot be confirmed
        return _resp("REQUEST_INFO", account_id, instrument_id), "future_date"
    as_of = resolve_as_of(d, tools)
    as_of_iso = as_of.isoformat()

    # --- figures
    settled = position(tools, account_id, instrument_id, as_of_iso)
    pend, pend_date = pending_info(tools, account_id, instrument_id, as_of_iso)
    claim = parse_claim(body)

    def _esc():
        return _resp("ESCALATE", account_id, instrument_id, as_of_iso, False, settled)

    # --- account flags
    if prof.get("legal_hold"):
        return _esc(), "legal_hold"
    if prof.get("no_email_confirm"):
        return _esc(), "no_email_confirm"

    if settled == 0 and not pend:
        return _resp("NOT_HELD", account_id, instrument_id, as_of_iso, False), "not_held"

    if claim is not None:
        cands = [settled]
        if pend:
            cands.append(settled + pend)
        ok = any(c != 0 and abs(claim - c) / abs(c) <= QTY_TOLERANCE for c in cands) or claim == settled
        if not ok:
            return _esc(), "qty_mismatch"

    br = "confirm_pending" if pend else "confirm"
    return _resp("CONFIRMED", account_id, instrument_id, as_of_iso, False, settled, pend, pend_date), br


def respond(request, tools):
    try:
        return decide(request, tools)[0]
    except Exception:
        return _resp("REQUEST_INFO")
