"""Induced procedure for the position-confirmation desk. Standard library only; state via `tools`."""
import calendar
import datetime as dt
import re

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WD_RE = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+)?"
PENDING_WINDOW_BDAYS = 10
MIN_LEVEL = 3


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- body cleanup
def _clean_body(body):
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if re.match(r"^-+\s*(forwarded|original) message", s, re.I):
            continue
        if re.match(r"^(from|to|cc|date|sent|subject)\s*:", s, re.I):
            continue
        if re.match(r"^this email and any attachments", s, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


# ---------------------------------------------------------------- dates
def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _last_day(y, m):
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def _prev_month_end(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Return (date|None, found_any_date_phrase)."""
    t = text.lower()
    t = re.sub(r"\s+", " ", t)
    # explicit absolute dates
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), True
    m = re.search(r"\b(\d{1,2})[-/ ]" + MON_RE + r"[a-z]*\.?[-/ ,]+(\d{2,4})\b", t)
    if m:
        return _mk(_year(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1))), True
    m = re.search(MON_RE + r"[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m:
        return _mk(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2))), True
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?" + MON_RE + r"[a-z]*,? (\d{4})\b", t)
    if m:
        return _mk(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1))), True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if a > 12 and b <= 12:  # clearly D/M
            return _mk(y, b, a), True
        return _mk(y, a, b), True  # default US M/D
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t)
    if m:
        return _mk(int(m.group(3)), int(m.group(2)), int(m.group(1))), True
    # month + day without year
    m = re.search(r"\b" + MON_RE + r"[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?\b(?!,? \d)", t)
    if m:
        d = _mk(sent.year, MONTHS[m.group(1)[:3]], int(m.group(2)))
        if d and d > sent:
            d = _mk(sent.year - 1, d.month, d.day)
        return d, True
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?" + MON_RE + r"\b(?! \d)", t)
    if m:
        d = _mk(sent.year, MONTHS[m.group(2)[:3]], int(m.group(1)))
        if d and d > sent:
            d = _mk(sent.year - 1, d.month, d.day)
        return d, True
    # relative phrases
    if re.search(r"\b(end|last day|close) of (the )?(last|previous|prior) month\b|\b(last|previous|prior) month[- ]end\b|\blast month end\b", t):
        return _prev_month_end(sent), True
    if re.search(r"\b(end|last day|close) of (the )?(last|previous|prior) (year|calendar year)\b|\b(last|previous|prior) year[- ]end\b", t):
        return dt.date(sent.year - 1, 12, 31), True
    if re.search(r"\b(end|last day|close) of (the )?(last|previous|prior) quarter\b|\b(last|previous|prior) quarter[- ]end\b", t):
        q_start_month = 3 * ((sent.month - 1) // 3) + 1
        return dt.date(sent.year, q_start_month, 1) - dt.timedelta(days=1), True
    m = re.search(r"\b(end|last day|close) of " + MON_RE + r"[a-z]*(?: (\d{4}))?\b", t)
    if m:
        mo = MONTHS[m.group(2)[:3]]
        y = int(m.group(3)) if m.group(3) else sent.year
        d = _last_day(y, mo)
        if not m.group(3) and d > sent:
            d = _last_day(y - 1, mo)
        return d, True
    if re.search(r"\b(month[- ]end|end of (the )?month)\b", t):
        return _prev_month_end(sent), True
    if re.search(r"\b(year[- ]end|end of (the )?year)\b", t):
        return dt.date(sent.year - 1, 12, 31), True
    if re.search(r"\bday before yesterday\b", t):
        return sent - dt.timedelta(days=2), True
    if re.search(r"\byesterday\b|\b(previous|prior|last) (business|working) day\b", t):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b|\bclose of business today\b|\bthis morning\b|\bas of now\b|\bas at now\b", t):
        return sent, True
    m = re.search(r"\blast (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(m.group(1))
        delta = (sent.weekday() - wd) % 7 or 7
        return sent - dt.timedelta(days=delta), True
    m = re.search(r"\b(\d+) (business |working )?days? ago\b", t)
    if m:
        return sent - dt.timedelta(days=int(m.group(1))), True
    return None, False


# ---------------------------------------------------------------- quantities
def _qty(tok):
    s = tok.lower().replace(",", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(k|thousand|m|mm|mn|mio|million|bn|b|billion)?", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {None: 1, "k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "mio": 1e6,
            "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}[m.group(2)]
    return int(round(v * mult))


NUM = r"(\d[\d,]*(?:\.\d+)?\s*(?:k|thousand|mm|mn|mio|million|bn|billion|m|b)?)\b"


DATE_PATTERNS = [
    r"\b\d{4}-\d{1,2}-\d{1,2}\b",
    r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b",
    r"\b\d{1,2}(?:st|nd|rd|th)?[-/ ](?:of )?" + MON_RE + r"[a-z]*\.?(?:[-/ ,]+\d{2,4})?\b",
    MON_RE + r"[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?(?:,? \d{4})?\b",
]


def client_figure(text):
    t = re.sub(r"\s+", " ", text)
    for p in DATE_PATTERNS:
        t = re.sub(p, " <DATE> ", t, flags=re.I)
    t = re.sub(r"\b[A-Z]{2,}-\d+\b", " <ID> ", t)
    t = re.sub(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", " <ID> ", t)
    num = r"(?<![\w.-])" + NUM
    pats = [
        r"\b(?:we have|we show|we hold|we see|we expect|we record|we've got|we carry|showing|shows?|show|"
        r"figure is|figure of|our figure|our records|our books|our position is|our holding is|our balance is|"
        r"reconciles? to|reconciled to|recorded as|per our records|according to our records)\b[^<>\d]{0,40}?" + num,
        num + r"\s*(?:shares|units|shs|sh|bonds)\b[^.?!]{0,30}(?:our books|our records|our side|we have|we hold)",
    ]
    for p in pats:
        for m in re.finditer(p, t, re.I):
            q = _qty(m.group(1))
            if q is not None and q > 0:
                return q
    return None


# ---------------------------------------------------------------- resolution
def _strip_acct(s):
    s = s.strip().strip(".,;:()[]\"'")
    s = re.sub(r"^(our|the|my)\s+", "", s, flags=re.I)
    s = re.sub(r"^(a/c|acct\.?|account|fund|portfolio|client)\s*(no\.?|number|#)?\s*[:#]?\s*", "", s, flags=re.I)
    return s.strip().strip(".,;:()[]\"'")


def resolve_account(text, tools):
    if not text:
        return None
    cands = [text, _strip_acct(text)]
    for m in re.finditer(r"\b(ACC-\d+|SA-\d+)\b", text, re.I):
        cands.append(m.group(1))
    seen = set()
    for c in cands:
        c = c.strip()
        if not c or c.lower() in seen:
            continue
        seen.add(c.lower())
        hits = tools.search_accounts(c)
        if hits:
            return hits
    return []


def _strip_inst(s):
    s = s.strip().strip(".,;:()[]\"'")
    s = re.sub(r"^(the|our)\s+", "", s, flags=re.I)
    s = re.sub(r"\s+(shares|stock|equity|position|holdings?|units|ordinary shares|common stock)$", "", s, flags=re.I)
    s = re.sub(r"^(isin|ticker|cusip)\s*[:#]?\s*", "", s, flags=re.I)
    return s.strip().strip(".,;:()[]\"'")


def resolve_instrument(text, body, tools):
    cands = []
    if text:
        cands += [text, _strip_inst(text), re.sub(r"\.$", "", _strip_inst(text))]
        m = re.search(r"\(([^)]+)\)", text)
        if m:
            cands.append(m.group(1))
        cands += re.findall(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", text)
    else:
        cands += re.findall(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", body or "")
    seen = set()
    for c in cands:
        c = c.strip()
        if not c or c.lower() in seen:
            continue
        seen.add(c.lower())
        hits = tools.search_instruments(c)
        if hits:
            return hits
    return []


def _active_level(ents, account_id, on):
    best = 0
    for e in ents:
        if e.get("account_id") != account_id:
            continue
        exp = e.get("expires")
        if exp and exp < on:
            continue
        best = max(best, int(e.get("level") or 0))
    return best


# ---------------------------------------------------------------- figures
def _business_as_of(d, tools):
    c = tools.get_calendar(d.isoformat())
    return d.isoformat() if c["business_day"] else c["previous_business_day"]


def settled_qty(account_id, instrument_id, as_of, tools):
    splits = [s for s in tools.get_corporate_actions(instrument_id) if s.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        total += q
    return int(total)


def _add_bdays(d, n, tools):
    cur = d
    k = 0
    while k < n:
        cur += dt.timedelta(days=1)
        if tools.get_calendar(cur.isoformat())["business_day"]:
            k += 1
    return cur


def pending_qty(account_id, instrument_id, as_of, sent, tools):
    horizon = _add_bdays(sent, PENDING_WINDOW_BDAYS, tools).isoformat()
    items = [x for x in tools.get_instructions(account_id, instrument_id)
             if x.get("status") == "matched" and as_of < x["settle_date"] <= horizon]
    if not items:
        return None, None
    return sum(int(x["qty"]) for x in items), max(x["settle_date"] for x in items)


# ---------------------------------------------------------------- main
def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    mentions = request.get("mentions") or {}
    body = _clean_body(request.get("body") or "")
    sender = (request.get("from") or "").strip().lower()

    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # 1. account
    acct_text = mentions.get("account_text")
    if acct_text:
        hits = resolve_account(acct_text, tools)
        if len(hits) != 1:
            return _out("REQUEST_INFO")
        account_id = hits[0]["id"]
    else:
        live = sorted({e["account_id"] for e in ents if not (e.get("expires") and e["expires"] < sent.isoformat())})
        if len(live) != 1:
            return _out("REQUEST_INFO")
        account_id = live[0]

    # 2. authorization: known contact with a live level-3 entitlement on that account
    if not contact or _active_level(ents, account_id, sent.isoformat()) < MIN_LEVEL:
        return _out("REQUEST_AUTHORIZATION")

    # 3. instrument
    ihits = resolve_instrument(mentions.get("instrument_text"), body, tools)
    if len(ihits) != 1:
        return _out("REQUEST_INFO")
    instrument_id = ihits[0]["id"]

    # 4. date
    d, found = parse_date(body, sent)
    if found and d is None:
        return _out("REQUEST_INFO")
    assumed = d is None
    if assumed:
        d = sent
    if d > sent:
        return _out("REQUEST_INFO")
    as_of = _business_as_of(d, tools)

    # 5. client profile restrictions
    prof = tools.get_client_profile(account_id) or {}
    if prof.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    # 6. figure
    settled = settled_qty(account_id, instrument_id, as_of, tools)
    if settled < 0:
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    claim = client_figure(body)
    if claim is not None and claim != settled:
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    pend, pdate = pending_qty(account_id, instrument_id, as_of, sent, tools)
    if settled == 0:
        return _out("NOT_HELD", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
                    as_of_assumed=assumed, settled=None, pending=pend, pending_date=pdate)
    return _out("CONFIRMED", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
                as_of_assumed=assumed, settled=settled, pending=pend, pending_date=pdate)
