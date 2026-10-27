"""Induced procedure for the position-confirmation desk (standard library only)."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
OPENING_DATE = "2025-12-15"  # date of the opening-balance load in the ledger
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WD_RE = r"(?:(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


def _clean_body(body):
    # drop forwarded-message header lines (they carry the email date, not the position date)
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith("---------- Forwarded message") or re.match(r"^(From|Date|Sent|To|Subject):", s):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _no_year(m, d, sent):
    x = _mk(sent.year, m, d)
    if x and x > sent:
        x = _mk(sent.year - 1, m, d)
    return x


def parse_date(body, sent):
    """Return (date|None, found_any_date_expression:bool, inconsistent:bool)."""
    t = body.lower()
    cands = []  # (pos, date, weekday_given)

    def add(pos, d, wd=None):
        cands.append((pos, d, wd))

    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        add(m.start(), _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t):
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        a, b = int(m.group(1)), int(m.group(2))
        us = _mk(y, a, b)
        eu = _mk(y, b, a)
        d = us if us else eu  # desk/client convention is US M/D/Y; fall back if impossible
        add(m.start(), d)
    for m in re.finditer(r"\b" + WD_RE + r"(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?" + MON_RE + r"[a-z]*\.?(?:[\s\-,]+(\d{4}))?\b", t):
        mon = MONTHS[m.group(3)[:3]]; day = int(m.group(2))
        d = _mk(int(m.group(4)), mon, day) if m.group(4) else _no_year(mon, day, sent)
        add(m.start(), d, m.group(1))
    for m in re.finditer(r"\b" + WD_RE + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", t):
        mon = MONTHS[m.group(2)[:3]]; day = int(m.group(3))
        d = _mk(int(m.group(4)), mon, day) if m.group(4) else _no_year(mon, day, sent)
        add(m.start(), d, m.group(1))

    first_of_month = sent.replace(day=1)
    last_month_end = first_of_month - dt.timedelta(days=1)
    rel = [
        (r"\b(end of last month|last day of (?:the )?(?:last|previous|prior) month|(?:last|previous|prior) month[\s-]?end|end of (?:the )?(?:previous|prior) month)\b", last_month_end),
        (r"\bmonth[\s-]?end\b", last_month_end),
        (r"\byesterday\b", sent - dt.timedelta(days=1)),
        (r"\btoday\b", sent),
        (r"\b(end of last year|(?:last|previous|prior) year[\s-]?end|year[\s-]?end)\b", dt.date(sent.year - 1, 12, 31)),
        (r"\b(end of last quarter|(?:last|previous|prior) quarter[\s-]?end|quarter[\s-]?end)\b",
         dt.date(sent.year, ((sent.month - 1) // 3) * 3 + 1, 1) - dt.timedelta(days=1)),
    ]
    used = set()
    for pat, d in rel:
        for m in re.finditer(pat, t):
            if any(abs(m.start() - u) < 3 for u in used):
                continue
            used.add(m.start())
            add(m.start(), d)

    if not cands:
        return None, False, False
    # weekday cross-check
    for _, d, wd in cands:
        if d is None:
            return None, True, True
        if wd and d.weekday() != WEEKDAYS[wd]:
            return None, True, True
    dates = {d for _, d, _ in cands}
    # month-end phrase overlapping with another candidate at same pos is deduped by set
    if len(dates) > 1:
        return None, True, True
    return dates.pop(), True, False


def _num(s, suffix):
    v = float(s.replace(",", ""))
    suffix = (suffix or "").lower()
    if suffix == "k":
        v *= 1_000
    elif suffix in ("m", "mm", "mn", "mio"):
        v *= 1_000_000
    elif suffix in ("bn", "b"):
        v *= 1_000_000_000
    return int(round(v))


def parse_client_figure(body):
    t = body.lower()
    pats = [
        r"our figure is",
        r"we have",
        r"we show",
        r"we hold",
        r"our records show",
        r"our books show",
        r"our records indicate",
        r"we record",
        r"our position is",
        r"we believe (?:we|the account) (?:hold|holds?)",
        r"our (?:books|records) (?:have|reflect)",
    ]
    for p in pats:
        m = re.search(p + r"\s+(?:a (?:position|holding) of\s+|approximately\s+|about\s+)?(-?\d[\d,]*(?:\.\d+)?)\s*(k|mm|mn|mio|m|bn|b)?\b", t)
        if m:
            return _num(m.group(1), m.group(2))
    return None


def _resolve_account(request, tools, contact):
    text = (request.get("mentions") or {}).get("account_text")
    if text and text.strip():
        hits = tools.search_accounts(text)
        if len(hits) == 1:
            return hits[0]["id"]
        return None
    # no account named ("our fund"): infer from the sender's entitlements if unambiguous
    if contact:
        accs = sorted({e["account_id"] for e in tools.get_entitlements(contact["contact_id"])})
        if len(accs) == 1:
            return accs[0]
    return None


def _entitled(tools, contact, acc, sent):
    if not contact:
        return False
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] == acc and e["level"] >= 3 and (not e.get("expires") or e["expires"] >= sent):
            return True
    return False


def _settled(tools, acc, ins, as_of):
    splits = tools.get_corporate_actions(ins)
    total = 0
    for tx in tools.get_ledger(acc, ins):
        if tx["date"] > as_of:
            continue
        q = tx["qty"]
        for s in splits:
            if s.get("type") == "split" and tx["date"] < s["date"] <= as_of:
                q = q * s["ratio"]
        total += q
    return int(total)


def respond(request, tools):
    sent_s = request["sent"]
    sent = dt.date.fromisoformat(sent_s)
    body = _clean_body(request.get("body") or "")
    contact = tools.get_contact(request.get("from") or "")

    # 1. account must be identifiable unambiguously
    acc = _resolve_account(request, tools, contact)
    if acc is None:
        return _out("REQUEST_INFO")

    # 2. sender must hold a current level-3 entitlement on the account
    if not _entitled(tools, contact, acc, sent_s):
        return _out("REQUEST_AUTHORIZATION")

    # 3. instrument must be identifiable
    itext = (request.get("mentions") or {}).get("instrument_text")
    if not itext or not itext.strip():
        return _out("REQUEST_INFO")
    ihits = tools.search_instruments(itext)
    if len(ihits) != 1:
        return _out("REQUEST_INFO")
    ins = ihits[0]["id"]

    # 4. date
    d, found, bad = parse_date(body, sent)
    if bad:
        return _out("REQUEST_INFO")
    assumed = False
    if d is None:
        d = sent
        assumed = True
    if d > sent:
        return _out("REQUEST_INFO")

    # 5. client-level restrictions
    prof = tools.get_client_profile(acc) or {}
    if prof.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _out("ESCALATE", acc, ins)

    # 6. figure is given for the requested day, rolled back to a business day
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    # records start with the opening balances; earlier dates cannot be confirmed from the ledger
    if as_of < _ledger_start(tools, acc, ins):
        return _out("ESCALATE", acc, ins)

    settled = _settled(tools, acc, ins, as_of)
    if settled < 0:
        return _out("ESCALATE", acc, ins)

    # matched (not cancelled / unmatched) instructions settling after the as-of date
    pend_all = [x for x in tools.get_instructions(acc, ins)
                if x["status"] == "matched" and x["settle_date"] > as_of]
    horizon = (sent + dt.timedelta(days=14)).isoformat()
    pend = [x for x in pend_all if x["settle_date"] <= horizon]

    claimed = parse_client_figure(body)
    if claimed is not None and claimed != settled:
        # a client figure that includes pending settlements is explained, not a break
        if pend_all and claimed == settled + sum(x["qty"] for x in pend_all):
            pend = pend_all
        else:
            return _out("ESCALATE", acc, ins)

    if settled == 0:
        return _out("NOT_HELD", acc, ins, as_of, assumed)

    pending, pdate = None, None
    if pend:
        pending = sum(x["qty"] for x in pend)
        pdate = max(x["settle_date"] for x in pend)
    return _out("CONFIRMED", acc, ins, as_of, assumed, settled, pending, pdate)


def _ledger_start(tools, acc, ins):
    # opening balances were all loaded on one migration date; nothing earlier is on record
    return OPENING_DATE
