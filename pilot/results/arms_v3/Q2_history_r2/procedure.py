"""Induced procedure for the holding-confirmation desk.

Order of checks:
 1. Resolve account and instrument (exactly one each), else REQUEST_INFO.
 2. Resolve the as-of date; a date after the email was sent -> REQUEST_INFO.
 3. Client restrictions (legal hold / no e-mail confirmation) -> ESCALATE.
 4. Sender authorization: known contact, live entitlement of level >= 2 on the account,
    sending from one of the client's registered domains; else REQUEST_AUTHORIZATION.
 5. Settled position = all custody sub-accounts, ledger entries dated <= as_of, adjusted
    for splits effective on/before as_of. Non-business as-of date rolls back to the previous
    business day.
 6. Client quoted a figure that differs from ours -> ESCALATE.
 7. Zero -> NOT_HELD, else CONFIRMED (+ matched pending instructions settling after as_of).
"""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
FREEMAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com",
            "icloud.com", "aol.com", "live.com", "mail.com", "gmx.com"}
MIN_LEVEL = 2


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _d(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _last_day_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _strip_quoted_headers(body):
    # drop forwarded-message header lines (From:/Date:) so their dates are not read as as-of dates
    lines = []
    for ln in body.splitlines():
        if re.match(r"\s*(from|date|sent|to|subject|cc)\s*:", ln, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


def parse_date(body, sent):
    """Return (date or None, found: bool)."""
    text = _strip_quoted_headers(body)
    low = text.lower()
    cands = []  # (position, date)

    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", low):
        cands.append((m.start(), _d(m.group(1), m.group(2), m.group(3))))
    for m in re.finditer(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b", low):
        cands.append((m.start(), _d(m.group(1), m.group(2), m.group(3))))
    for m in re.finditer(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", low):  # US m/d/y, else d/m/y
        cands.append((m.start(), _d(m.group(3), m.group(1), m.group(2)) or _d(m.group(3), m.group(2), m.group(1))))
    for m in re.finditer(r"\b(\d{1,2})[-\s]" + MON_RE + r"[a-z]*\.?[-\s,]+(\d{4})\b", low):
        cands.append((m.start(), _d(m.group(3), MONTHS[m.group(2)[:3]], m.group(1))))
    for m in re.finditer(r"\b" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low):
        cands.append((m.start(), _d(m.group(3), MONTHS[m.group(1)[:3]], m.group(2))))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)\s+(?:of\s+)?" + MON_RE + r"[a-z]*,?\s+(\d{4})\b", low):
        cands.append((m.start(), _d(m.group(3), MONTHS[m.group(2)[:3]], m.group(1))))

    rel = [
        (r"\bday before yesterday\b", lambda: sent - dt.timedelta(days=2)),
        (r"\byesterday\b", lambda: sent - dt.timedelta(days=1)),
        (r"\btoday\b|\bthis morning\b|\bcurrent(?:ly)?\b(?! month)", lambda: sent),
        (r"\b(?:end of|last day of|close of) (?:the )?(?:last|previous|prior) month\b|\b(?:last|previous|prior) month[- ]end\b|\bmonth[- ]end\b|\bend of (?:the )?month\b",
         lambda: _last_day_prev_month(sent)),
        (r"\b(?:end of|last day of) (?:the )?(?:last|previous|prior) (?:year|calendar year)\b|\byear[- ]end\b",
         lambda: dt.date(sent.year - 1, 12, 31)),
        (r"\b(?:end of|last day of) (?:the )?(?:last|previous|prior) quarter\b|\bquarter[- ]end\b",
         lambda: _last_quarter_end(sent)),
        (r"\blast (?:business|working) day\b|\bprevious (?:business|working) day\b|\bclose of business yesterday\b",
         lambda: sent - dt.timedelta(days=1)),
    ]
    for pat, fn in rel:
        m = re.search(pat, low)
        if m:
            cands.append((m.start(), fn()))
    cands = [c for c in cands if c[1] is not None]
    if not cands:
        return None, False
    # Prefer a date that follows an as-of cue; otherwise the first date in the text.
    cue = re.search(r"as (?:of|at)|position date|holdings? (?:on|at)|dated|valuation date|as on", low)
    if cue:
        after = [c for c in cands if c[0] >= cue.start()]
        if after:
            return min(after)[1], True
    return min(cands)[1], True


def _last_quarter_end(sent):
    q_start_month = 3 * ((sent.month - 1) // 3) + 1
    return dt.date(sent.year, q_start_month, 1) - dt.timedelta(days=1)


def parse_client_figure(body):
    low = _strip_quoted_headers(body).lower()
    pats = [r"(?:our figure is|we show|records show|we have|our books show|we hold|we record|our position is|our records indicate|we expect|we believe we hold)\s*:?\s*([\d][\d,]*(?:\.\d+)?)\s*(k|mm|m|mn|million|thousand)?\b",
            r"([\d][\d,]*(?:\.\d+)?)\s*(k|mm|m|mn|million|thousand)?\s*(?:shares|units)\b"]
    for p in pats:
        m = re.search(p, low)
        if m:
            num = m.group(1).rstrip(".,").replace(",", "")
            try:
                v = float(num)
            except ValueError:
                continue
            mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6}.get(m.group(2) or "", 1)
            return int(round(v * mult))
    return None


def resolve_account(req, tools):
    m = req.get("mentions") or {}
    texts = []
    if m.get("account_text"):
        texts.append(m["account_text"])
    else:
        body = req.get("body", "")
        for pat in (r"\bACC-\d+\b", r"\bSA-\d+\b"):
            for mm in re.finditer(pat, body, re.I):
                texts.append(mm.group(0))
    ids = set()
    for t in texts:
        t = re.sub(r"^(?:our\s+)?(?:account|acct|a/c|fund)\s+", "", t.strip(), flags=re.I)
        hits = tools.search_accounts(t)
        ids.update(h["id"] for h in hits)
    if len(ids) != 1:
        return None
    return ids.pop()


def resolve_instrument(req, tools):
    m = req.get("mentions") or {}
    texts = []
    if m.get("instrument_text"):
        texts.append(m["instrument_text"])
    else:
        for mm in re.finditer(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", req.get("body", "")):
            texts.append(mm.group(0))
    ids = set()
    for t in texts:
        ids.update(i["id"] for i in tools.search_instruments(t.strip()))
    if len(ids) != 1:
        return None
    return ids.pop()


def authorized(req, account_id, sent, tools):
    sender = (req.get("from") or "").strip().lower()
    if "@" not in sender:
        return False
    domain = sender.split("@", 1)[1]
    prof = tools.get_client_profile(account_id) or {}
    domains = [d.lower() for d in prof.get("domains", [])]
    if domain in FREEMAIL or domain not in domains:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] != account_id:
            continue
        if e.get("expires") and e["expires"] < sent.isoformat():
            continue
        if (e.get("level") or 0) >= MIN_LEVEL:
            return True
    return False


def business_as_of(d, tools):
    cal = tools.get_calendar(d.isoformat())
    return d.isoformat() if cal["business_day"] else cal["previous_business_day"]


def settled_qty(account_id, instrument_id, as_of, tools):
    led = tools.get_ledger(account_id, instrument_id)
    splits = [ca for ca in tools.get_corporate_actions(instrument_id) if ca.get("type") == "split"]
    total = 0
    for t in led:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q = q * s["ratio"]
        total += q
    return int(round(total))


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"][:10])
    body = request.get("body") or ""

    account_id = resolve_account(request, tools)
    instrument_id = resolve_instrument(request, tools)
    if not account_id or not instrument_id:
        return _out("REQUEST_INFO")

    d, found = parse_date(body, sent)
    assumed = False
    if not found:
        d = sent - dt.timedelta(days=1)
        assumed = True
    if d > sent:
        return _out("REQUEST_INFO")

    prof = tools.get_client_profile(account_id) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    if not authorized(request, account_id, sent, tools):
        return _out("REQUEST_AUTHORIZATION")

    as_of = business_as_of(d, tools)
    settled = settled_qty(account_id, instrument_id, as_of, tools)

    claimed = parse_client_figure(body)
    if claimed is not None and claimed != settled:
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    if settled <= 0:
        return _out("NOT_HELD", account_id=account_id, instrument_id=instrument_id,
                    as_of=as_of, as_of_assumed=assumed)

    pend = [x for x in tools.get_instructions(account_id, instrument_id)
            if x.get("status") == "matched" and x["settle_date"] > as_of]
    pending = pending_date = None
    if pend:
        pending = sum(x["qty"] for x in pend)
        pending_date = min(x["settle_date"] for x in pend)
    return _out("CONFIRMED", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
                as_of_assumed=assumed, settled=settled, pending=pending, pending_date=pending_date)
