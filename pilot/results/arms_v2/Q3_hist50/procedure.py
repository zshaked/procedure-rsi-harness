"""Induced procedure for the position-confirmation desk (stdlib only, state via `tools`)."""
import datetime as dt
import re

PENDING_MIN_QTY = 1000

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
for _k, _v in list(MONTHS.items()):
    MONTHS[_k[:3]] = _v
MONTHS["sept"] = 9
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WD_RE = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*,?\s+)?"


def _out(outcome, acct=None, inst=None, as_of=None, assumed=False, settled=None,
         pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": acct, "instrument_id": inst,
            "as_of": as_of, "as_of_assumed": assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


# ---------------------------------------------------------------- text cleanup
def _clean_body(body):
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if re.match(r"^-+\s*forwarded message", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if re.search(r"confidential and intended solely", s, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month_end(y, m):
    nxt = (dt.date(y, m, 28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def _prev_month_end(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _infer_year(m, d, sent):
    c = _mk(sent.year, m, d)
    if c and c > sent + dt.timedelta(days=7):
        c = _mk(sent.year - 1, m, d)
    return c


def _parse_date(text, sent):
    """Return (date, found). found=False if no date expression in text."""
    t = text.lower()
    t = re.sub(r"\b(c\.?o\.?b\.?|close of business|end of day|eod)\b", " ", t)
    pats = []
    # ISO
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        pats.append((m.start(), _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
    # d-Mon-yyyy / d Mon yyyy / d Month, yyyy
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/.]+" + MON_RE + r"\.?,?[\s\-/.]+(\d{2,4})\b", t):
        pats.append((m.start(), _mk(_year(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))))
    # Month d, yyyy
    for m in re.finditer(r"\b" + MON_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t):
        pats.append((m.start(), _mk(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2)))))
    # numeric m/d/yyyy (US)
    for m in re.finditer(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b", t):
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        d = _mk(y, a, b) if a <= 12 else _mk(y, b, a)
        pats.append((m.start(), d))
    if pats:
        pats.sort(key=lambda x: x[0])
        return pats[0][1], True
    # without year: "d Month" / "Month d"
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON_RE + r"\b", t):
        return _infer_year(MONTHS[m.group(2)[:3]], int(m.group(1)), sent), True
    for m in re.finditer(r"\b" + MON_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*(?:shares|units))", t):
        return _infer_year(MONTHS[m.group(1)[:3]], int(m.group(2)), sent), True
    # relative expressions
    if re.search(r"\b(day before yesterday)\b", t):
        return sent - dt.timedelta(days=2), True
    if re.search(r"\byesterday\b", t):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\b(today|as of now|as at now|this morning)\b", t):
        return sent, True
    if re.search(r"\b(end of last year|last year[- ]end|year[- ]end|end of (?:the )?(?:previous|prior) year|end of \d{4})\b", t):
        m = re.search(r"end of (\d{4})", t)
        y = int(m.group(1)) if m else sent.year - 1
        return dt.date(y, 12, 31), True
    if re.search(r"\b(end of (?:the )?last quarter|last quarter[- ]end|quarter[- ]end|end of (?:the )?(?:previous|prior) quarter)\b", t):
        q_start = dt.date(sent.year, 3 * ((sent.month - 1) // 3) + 1, 1)
        return q_start - dt.timedelta(days=1), True
    if re.search(r"\b((?:the )?(?:end|last (?:business |calendar )?day) of (?:the )?(?:last|previous|prior) month|last month[- ]end|(?:previous|prior) month[- ]end|month[- ]end|end of (?:the )?month)\b", t):
        return _prev_month_end(sent), True
    m = re.search(r"\b(?:end of|last day of)\s+" + MON_RE + r"\b(?:\s+(\d{4}))?", t)
    if m:
        mo = MONTHS[m.group(1)[:3]]
        y = int(m.group(2)) if m.group(2) else (sent.year if mo <= sent.month else sent.year - 1)
        return _month_end(y, mo), True
    m = re.search(r"\b(?:last|this past|previous)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(m.group(1))
        delta = (sent.weekday() - wd) % 7 or 7
        return sent - dt.timedelta(days=delta), True
    if re.search(r"\b(end of last week|last week[- ]end|end of (?:the )?(?:previous|prior) week)\b", t):
        delta = (sent.weekday() - 4) % 7 or 7
        return sent - dt.timedelta(days=delta), True
    m = re.search(r"\b(\d+)\s+days?\s+ago\b", t)
    if m:
        return sent - dt.timedelta(days=int(m.group(1))), True
    return None, False


def _parse_qty(s):
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mm|mn|m|k|thousand|million)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"mm": 1e6, "mn": 1e6, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}.get(m.group(2) or "", 1)
    return int(round(v * mult))


QTY_TOKEN = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(mm|mn|million|thousand|k|m)?\b"


def _client_figure(text):
    t = text
    t = re.sub(r"\b(ACC|SA)[- ]?\d+\b", " ", t, flags=re.I)
    t = re.sub(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", " ", t)
    t = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", " ", t)
    t = re.sub(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b", " ", t)
    t = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?[\s\-]+" + MON_RE + r"\b[\s\-,]*\d{0,4}", " ", t, flags=re.I)
    t = re.sub(r"\b" + MON_RE + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4}", " ", t, flags=re.I)
    kw = re.compile(r"(our (?:figure|records?|books?|position|holding|number|count)|we (?:have|show|hold|see|record|believe|expect)|"
                    r"on our books|records show|figure is|reconcil|should be|shows?|holding of|position of|expect)", re.I)
    for sent in re.split(r"(?<=[.!?])\s+|\n", t):
        if not kw.search(sent):
            continue
        for m in re.finditer(QTY_TOKEN, sent, re.I):
            raw = m.group(1) + (m.group(2) or "")
            v = _parse_qty(raw)
            if v is None:
                continue
            if m.group(2) is None and "," not in m.group(1) and 1900 <= v <= 2100:
                continue
            return v
    return None


# ---------------------------------------------------------------- resolution
def _acct_variants(s):
    s = (s or "").strip()
    out = [s]
    c = re.sub(r"^(?:our\s+|the\s+)?(?:a/c|acct\.?|account|fund|portfolio|sub[- ]?account|client)\s*(?:no\.?|number|#|:)?\s*", "", s, flags=re.I)
    out.append(c)
    c2 = c.strip(" .,:;'\"()[]")
    out.append(c2)
    m = re.search(r"\b(ACC|SA)[\s\-_]?(\d{5,6})\b", c2, re.I)
    if m:
        out.insert(0, m.group(1).upper() + "-" + m.group(2))
    return [x for i, x in enumerate(out) if x and x not in out[:i]]


def _resolve_account(text, tools):
    """Returns (account_id, status) status in ok|ambiguous|notfound."""
    best = None
    for v in _acct_variants(text):
        hits = tools.search_accounts(v)
        if len(hits) == 1:
            return hits[0]["id"], "ok"
        if len(hits) > 1 and best is None:
            best = "ambiguous"
    return None, best or "notfound"


def _inst_variants(s):
    s = (s or "").strip()
    out = [s]
    c = re.sub(r"^(?:isin|ticker|cusip|security|stock|shares? (?:of|in))\s*:?\s*", "", s, flags=re.I)
    c = re.sub(r"\s+(?:shares|stock|common(?: stock)?|equity|ordinary shares|us equity|us)$", "", c, flags=re.I)
    out.append(c)
    out.append(c.strip(" .,:;'\"()[]"))
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", s.upper())
    if m:
        out.insert(0, m.group(1))
    m = re.search(r"\(([A-Za-z]{1,6})\)", s)
    if m:
        out.append(m.group(1))
    return [x for i, x in enumerate(out) if x and x not in out[:i]]


def _resolve_instrument(text, tools):
    amb = False
    for v in _inst_variants(text):
        hits = tools.search_instruments(v)
        ids = sorted({h["id"] for h in hits})
        if len(ids) == 1:
            return ids[0], "ok"
        if len(ids) > 1:
            cur = [h for h in hits if h["ticker"].lower() == v.strip().lower()]
            if len(cur) == 1:
                return cur[0]["id"], "ok"
            amb = True
    return None, "ambiguous" if amb else "notfound"


def _authorized(contact, account_id, sent, tools):
    if not contact:
        return False
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] != account_id:
            continue
        if int(e.get("level") or 0) < 3:
            continue
        exp = e.get("expires")
        if exp and exp < sent.isoformat():
            continue
        return True
    return False


# ---------------------------------------------------------------- figures
def _settled(tools, account_id, inst_id, as_of):
    splits = [c for c in tools.get_corporate_actions(inst_id) if c.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(account_id, inst_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q = q * s["ratio"]
        total += q
    return int(total)


def _pending(tools, account_id, inst_id, as_of):
    xs = [x for x in tools.get_instructions(account_id, inst_id)
          if x.get("status") == "matched" and x["settle_date"] > as_of and x["qty"] >= PENDING_MIN_QTY]
    if not xs:
        return None, None
    return sum(x["qty"] for x in xs), max(x["settle_date"] for x in xs)


# ---------------------------------------------------------------- main
def respond(request, tools):
    sent = dt.date.fromisoformat(str(request.get("sent"))[:10])
    body = _clean_body(request.get("body") or "")
    ment = request.get("mentions") or {}
    acct_text = ment.get("account_text")
    inst_text = ment.get("instrument_text")
    sender = (request.get("from") or "").strip()
    m = re.search(r"<([^>]+)>", sender)
    if m:
        sender = m.group(1)
    contact = tools.get_contact(sender) if sender else None

    # 1. account
    acct = None
    if acct_text:
        acct, st = _resolve_account(acct_text, tools)
        if st != "ok":
            return _out("REQUEST_INFO")
    else:
        ids = sorted({x.group(1).upper() + "-" + x.group(2) for x in re.finditer(r"\b(ACC|SA)[\s\-]?(\d{5,6})\b", body, re.I)})
        cands = set()
        for i in ids:
            for h in tools.search_accounts(i):
                cands.add(h["id"])
        if len(cands) == 1:
            acct = cands.pop()
        elif len(cands) > 1:
            return _out("REQUEST_INFO")
        elif contact:
            ents = [e for e in tools.get_entitlements(contact["contact_id"])
                    if not e.get("expires") or e["expires"] >= sent.isoformat()]
            accs = sorted({e["account_id"] for e in ents})
            if len(accs) == 1:
                acct = accs[0]
        if acct is None:
            return _out("REQUEST_INFO")

    # 2. authorization of the sender for this account
    if not _authorized(contact, acct, sent, tools):
        return _out("REQUEST_AUTHORIZATION")

    # 3. instrument
    inst = None
    if inst_text:
        inst, st = _resolve_instrument(inst_text, tools)
    else:
        isins = sorted(set(re.findall(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", body)))
        if len(isins) == 1:
            inst, st = _resolve_instrument(isins[0], tools)
    if inst is None:
        return _out("REQUEST_INFO")

    # 4. date
    d, found = _parse_date(body, sent)
    assumed = False
    if found:
        if d is None or d > sent:
            return _out("REQUEST_INFO")
        if not tools.get_calendar(d.isoformat())["business_day"]:
            return _out("REQUEST_INFO")
        as_of = d.isoformat()
    else:
        assumed = True
        cal = tools.get_calendar(sent.isoformat())
        as_of = sent.isoformat() if cal["business_day"] else cal["previous_business_day"]

    # 5. client restrictions
    prof = tools.get_client_profile(acct) or {}
    if prof.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _out("ESCALATE", acct, inst)

    # 6. figures
    settled = _settled(tools, acct, inst, as_of)
    if settled < 0:
        return _out("ESCALATE", acct, inst)
    claim = _client_figure(body)
    if claim is not None and claim != settled:
        return _out("ESCALATE", acct, inst)
    pend, pdate = _pending(tools, acct, inst, as_of)
    if settled == 0:
        return _out("NOT_HELD", acct, inst, as_of, assumed, 0, pend, pdate)
    return _out("CONFIRMED", acct, inst, as_of, assumed, settled, pend, pdate)
