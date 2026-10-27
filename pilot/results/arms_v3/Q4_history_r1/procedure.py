"""Induced procedure for the position-confirmation desk (see NOTES.md).

 1. sender must be a known contact, not on a free-mail domain        -> REQUEST_AUTHORIZATION
 2. account text must resolve to exactly one account                 -> REQUEST_INFO
 3. live entitlement (level >= 2, not expired) on that account and
    sender domain registered in the client profile                   -> REQUEST_AUTHORIZATION
 4. legal hold / no-email-confirm client flag                        -> ESCALATE
 5. instrument resolves uniquely; a usable, non-future date is given -> REQUEST_INFO
 6. settled = ledger over ALL sub-accounts, dated <= as-of (rolled back to a business
    day), split-adjusted; a stated client figure must be within 10% of settled or of
    settled + matched pending                                        -> ESCALATE
 7. settled == 0 -> NOT_HELD, else CONFIRMED (+ matched instructions settling after as-of)
"""
import datetime as dt
import re

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com",
             "live.com", "msn.com", "protonmail.com", "proton.me", "gmx.com", "mail.com",
             "yahoo.co.uk", "googlemail.com", "me.com"}
MIN_LEVEL = 2
TOLERANCE = 0.10  # relative break tolerance (see NOTES.md)

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _base(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- text helpers
def _clean_body(body):
    """Drop forwarded-header lines and the confidentiality footer."""
    out = []
    for line in (body or "").splitlines():
        s = line.strip()
        if re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if s.startswith("----------"):
            continue
        if "confidential and intended solely" in s.lower():
            continue
        out.append(line)
    return "\n".join(out)


def _mdate(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Return (date, assumed) or (None, False)."""
    t = text.lower()
    # explicit dates
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mdate(*m.groups()), False
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if a > 12 >= b:
            return _mdate(y, b, a), False
        return _mdate(y, a, b), False
    m = re.search(r"\b(\d{1,2})[- ]" + MON_RE + r"[a-z]*[- ,]+(\d{4})\b", t)
    if m:
        return _mdate(m.group(3), MONTHS[m.group(2)[:3]], m.group(1)), False
    m = re.search(r"\b" + MON_RE + r"[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m:
        return _mdate(m.group(3), MONTHS[m.group(1)[:3]], m.group(2)), False
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?" + MON_RE + r"[a-z]*,? (\d{4})\b", t)
    if m:
        return _mdate(m.group(3), MONTHS[m.group(2)[:3]], m.group(1)), False
    # day and month without a year: the sent year (previous year if that is >6 months ahead)
    m = (re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ](?:of )?" + MON_RE + r"\b", t)
         or re.search(r"\b" + MON_RE + r"[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?\b", t))
    if m:
        g = m.groups()
        day, mon = (g[0], g[1]) if g[0].isdigit() else (g[1], g[0])
        d = _mdate(sent.year, MONTHS[mon[:3]], day)
        if d and (d - sent).days > 183:
            d = _mdate(sent.year - 1, MONTHS[mon[:3]], day)
        if d:
            return d, False
    # relative dates
    if re.search(r"\b(end of last month|last day of (the )?(last|previous|prior) month|"
                 r"(last|previous|prior) month[- ]end|end of (the )?(previous|prior) month)\b", t):
        return _last_day_prev_month(sent), False
    if re.search(r"\bday before yesterday\b", t):
        return sent - dt.timedelta(days=2), False
    if re.search(r"\byesterday\b", t):
        return sent - dt.timedelta(days=1), False
    if re.search(r"\b(month[- ]end|end of (the )?month)\b", t):
        return _last_day_prev_month(sent), True
    if re.search(r"\b(end of (the )?(last|previous|prior) year|(last|previous|prior) year[- ]end)\b", t):
        return dt.date(sent.year - 1, 12, 31), False
    if re.search(r"\b(year[- ]end|end of (the )?year)\b", t):
        return dt.date(sent.year - 1, 12, 31), True
    q_end = dt.date(sent.year, 3 * ((sent.month - 1) // 3) + 1, 1) - dt.timedelta(days=1)
    if re.search(r"\b(end of (the )?(last|previous|prior) quarter|(last|previous|prior) quarter[- ]end)\b", t):
        return q_end, False
    if re.search(r"\b(quarter[- ]end|end of (the )?quarter)\b", t):
        return q_end, True
    if re.search(r"\b(today|close of business today|cob today)\b", t):
        return sent, False
    return None, False


def parse_qty(s):
    s = s.strip().lower().replace(",", "").replace(" ", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)(k|m|mm|mn|mio|bn|b)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {None: 1, "k": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "mio": 1e6, "b": 1e9, "bn": 1e9}[m.group(2)]
    return int(round(v * mult))


QTY_RE = (r"(?:our figure is|our records show|records show|we show|we have|we hold|our books show|"
          r"our position is|showing)\s+(-?[\d,]*\d(?:\.\d+)?[ ]?(?:k|mm|mn|mio|m|bn)?)\b")


def stated_qty(text):
    m = re.search(QTY_RE, text, re.I)
    if not m:
        return None
    return parse_qty(m.group(1))


# ---------------------------------------------------------------- lookups
def _resolve_account(tools, text):
    if not text or not text.strip():
        return None, "missing"
    hits = tools.search_accounts(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], None
    return None, ("missing" if not hits else "ambiguous")


def _resolve_instrument(tools, text):
    if not text or not text.strip():
        return None, "missing"
    hits = tools.search_instruments(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], None
    return None, ("missing" if not hits else "ambiguous")


def _business_as_of(tools, d):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def settled_position(tools, account_id, instrument_id, as_of):
    a = as_of.isoformat()
    splits = [c for c in tools.get_corporate_actions(instrument_id) if c.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > a:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= a:
                q *= s["ratio"]
        total += q
    return total


def pending_settlement(tools, account_id, instrument_id, as_of):
    a = as_of.isoformat()
    xs = [x for x in tools.get_instructions(account_id, instrument_id)
          if x["status"] == "matched" and x["settle_date"] > a]
    if not xs:
        return None, None
    return sum(x["qty"] for x in xs), max(x["settle_date"] for x in xs)


# ---------------------------------------------------------------- main
def respond(request, tools):
    sender = (request.get("from") or "").strip().lower()
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    sent = dt.date.fromisoformat(request["sent"][:10])
    mentions = request.get("mentions") or {}
    body = _clean_body(request.get("body") or "")

    # 1. sender identity
    contact = tools.get_contact(sender) if sender else None
    if contact is None or domain in FREE_MAIL:
        return _base("REQUEST_AUTHORIZATION")

    # 2. account
    account_id, why = _resolve_account(tools, mentions.get("account_text"))
    if account_id is None:
        return _base("REQUEST_INFO")

    # 3. authorization for this account
    profile = tools.get_client_profile(account_id) or {}
    domains = {d.lower() for d in profile.get("domains", [])}
    ents = [e for e in tools.get_entitlements(contact["contact_id"])
            if e["account_id"] == account_id and e["level"] >= MIN_LEVEL
            and e["expires"] >= sent.isoformat()]
    if not ents or domain not in domains:
        return _base("REQUEST_AUTHORIZATION")

    instrument_id, why = _resolve_instrument(tools, mentions.get("instrument_text"))

    # 4. client restrictions: legal hold / no e-mail confirmations go to review
    if profile.get("legal_hold") or profile.get("no_email_confirm"):
        return _base("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    # 5. instrument and date
    if instrument_id is None:
        return _base("REQUEST_INFO")
    req_date, assumed = parse_date(body, sent)
    if req_date is None or req_date > sent:
        return _base("REQUEST_INFO")

    # 6. position
    as_of = _business_as_of(tools, req_date)
    settled = settled_position(tools, account_id, instrument_id, as_of)
    pend, pend_date = pending_settlement(tools, account_id, instrument_id, as_of)
    claim = stated_qty(body)
    if claim is not None:
        refs = [settled] + ([settled + pend] if pend else [])
        if not any(abs(claim - ref) <= TOLERANCE * abs(ref) for ref in refs):
            return _base("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    outcome = "CONFIRMED" if settled != 0 else "NOT_HELD"
    return _base(outcome, account_id=account_id, instrument_id=instrument_id,
                 as_of=as_of.isoformat(), as_of_assumed=bool(assumed),
                 settled=settled if outcome == "CONFIRMED" else None,
                 pending=pend, pending_date=pend_date)
