"""Induced procedure for the custody position-confirmation desk."""
import datetime as dt
import re

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com",
             "icloud.com", "aol.com", "live.com", "msn.com", "mail.com", "gmx.com", "yandex.com"}
MIN_LEVEL = 2
TOLERANCE = 0.10  # relative difference tolerated between client's figure and ours

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DOW = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*,?\s+)?"


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_body(body):
    # drop forwarded-message header lines and the confidentiality footer
    lines = []
    for ln in body.splitlines():
        s = ln.strip().lower()
        if s.startswith("from:") or s.startswith("date:") or s.startswith("sent:") or "forwarded message" in s:
            continue
        if s.startswith("this email and any attachments"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _last_of_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _parse_date(text, sent):
    """Return (date, relative_flag) or (None, None)."""
    t = text.lower()
    # relative phrases
    if re.search(r"\byesterday\b", t):
        return sent - dt.timedelta(days=1), "yesterday"
    if re.search(r"\btoday\b|\bclose of business today\b", t):
        return sent, "today"
    if re.search(r"(end of last month|last day of (?:the )?(?:last|previous|prior) month|"
                 r"(?:last|previous|prior) month[- ]end|end of (?:the )?(?:previous|prior) month)", t):
        return _last_of_prev_month(sent), "lastmonth"
    if re.search(r"\bmonth[- ]?end\b|\bend of (?:the )?month\b", t):
        return _last_of_prev_month(sent), "monthend"
    # ISO
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, None
    # m/d/yyyy
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        a, b = int(m.group(1)), int(m.group(2))
        d = _mk(y, a, b) if a <= 12 else _mk(y, b, a)
        if d:
            return d, None
    # dd-Mon-yyyy
    m = re.search(r"\b(\d{1,2})[- ]" + MON_RE + r"[a-z]*[- ,]+(\d{4})\b", t)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))
        if d:
            return d, None
    # Month dd, yyyy
    m = re.search(r"\b" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2)))
        if d:
            return d, None
    # without year: "dd Mon" / "Mon dd"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON_RE + r"\b", t) or None
    if m:
        d = _mk(sent.year, MONTHS[m.group(2)[:3]], int(m.group(1)))
        if d and d > sent:
            d = _mk(sent.year - 1, d.month, d.day)
        if d:
            return d, "noyear"
    m = re.search(r"\b" + MON_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m:
        d = _mk(sent.year, MONTHS[m.group(1)[:3]], int(m.group(2)))
        if d and d > sent:
            d = _mk(sent.year - 1, d.month, d.day)
        if d:
            return d, "noyear"
    return None, None


NUM = r"(-?\d[\d,]*(?:\.\d+)?(?:(?:mm|bn|k|m)\b|\s?(?:mm|mn|bn)\b)?)"


def _parse_qty(body):
    pats = [r"our records show\s+" + NUM,
            r"our figure is\s+" + NUM,
            r"our position is\s+" + NUM,
            r"we (?:show|have|hold|record)\s+" + NUM,
            NUM + r"\s+(?:shares|units)\b"]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            return _num(m.group(1))
    return None


def _num(s):
    s = s.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    for suf, f in (("mm", 1_000_000), ("mn", 1_000_000), ("bn", 1_000_000_000), ("k", 1_000), ("m", 1_000_000)):
        if s.endswith(suf):
            s, mult = s[: -len(suf)], f
            break
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def _resolve_account(text, tools):
    if not text:
        return None, "missing"
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"], None
    if not hits:
        return None, "unknown"
    return None, "ambiguous"


def _resolve_instrument(text, tools):
    if not text:
        return None, "missing"
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"], None
    if not hits:
        return None, "unknown"
    return None, "ambiguous"


def _authorized(contact, account_id, sent):
    if not contact:
        return False
    for e in contact["_ents"]:
        if e["account_id"] == account_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent.isoformat():
            return True
    return False


def _business_day(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def _settled(account_id, instrument_id, as_of, tools):
    splits = tools.get_corporate_actions(instrument_id)
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s.get("type") == "split" and t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        total += q
    return total


def _pending(account_id, instrument_id, as_of, tools):
    qty, last = 0, None
    for x in tools.get_instructions(account_id, instrument_id):
        if x["status"] == "matched" and x["settle_date"] > as_of:
            qty += x["qty"]
            if last is None or x["settle_date"] > last:
                last = x["settle_date"]
    if qty == 0:
        return None, None
    return qty, last


def _close(claimed, ours):
    if claimed == ours:
        return True
    return ours != 0 and abs(claimed - ours) <= TOLERANCE * abs(ours)


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"][:10])
    sender = (request.get("from") or "").strip().lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    mentions = request.get("mentions") or {}
    body = _clean_body(request.get("body") or "")

    contact = tools.get_contact(sender) if sender else None
    if contact:
        contact["_ents"] = tools.get_entitlements(contact["contact_id"])

    # 1. sender must be a known contact on a corporate address
    if not contact or domain in FREE_MAIL:
        return _out("REQUEST_AUTHORIZATION")

    # 2. identify the account
    account_id, aerr = _resolve_account(mentions.get("account_text"), tools)
    if aerr:
        return _out("REQUEST_INFO")

    # 3. sender must hold a live entitlement of sufficient level on that account
    if not _authorized(contact, account_id, sent):
        return _out("REQUEST_AUTHORIZATION")

    # 4. identify instrument and date
    instrument_id, ierr = _resolve_instrument(mentions.get("instrument_text"), tools)
    if ierr:
        return _out("REQUEST_INFO")
    req_date, rel = _parse_date(body, sent)
    if req_date is None or req_date > sent:
        return _out("REQUEST_INFO")

    # 5. account restrictions
    prof = tools.get_client_profile(account_id) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    as_of_d = _business_day(req_date, tools)
    as_of = as_of_d.isoformat()
    assumed = as_of_d != req_date or rel == "monthend" or rel == "noyear"

    settled = _settled(account_id, instrument_id, as_of, tools)
    pending, pdate = _pending(account_id, instrument_id, as_of, tools)

    # 6. client's figure must agree with ours
    claimed = _parse_qty(body)
    if claimed is not None:
        ok = _close(claimed, settled)
        if not ok and pending:
            ok = _close(claimed, settled + pending)
        if not ok:
            return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    if settled <= 0:
        return _out("NOT_HELD", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
                    as_of_assumed=assumed, pending=pending, pending_date=pdate)
    return _out("CONFIRMED", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
                as_of_assumed=assumed, settled=settled, pending=pending, pending_date=pdate)
