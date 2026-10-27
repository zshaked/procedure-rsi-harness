"""Induced procedure for the holding-confirmation desk. Deterministic, stdlib only."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 3
FIGURE_TOLERANCE = 0.05  # oracle: 2% ok, 7% escalates (Q3-0012)
LARGE_POSITION = 1_000_000  # oracle: 1,056,400 escalated; 855,399 confirmed
MIN_PENDING_QTY = 1000  # oracle: 684 and 656 not reported; 4,632+ reported

FWD_RE = re.compile(r"-+ ?Forwarded message ?-+\s*\nFrom:[^\n]*\n(Date:[^\n]*\n)?(Subject:[^\n]*\n)?(To:[^\n]*\n)?", re.I)


def _clean_body(body):
    b = FWD_RE.sub("", body or "")
    b = re.sub(r"(?im)^\s*(from|date|sent|to|cc|subject)\s*:.*$", "", b)
    b = re.sub(r"-+ ?(forwarded|original) message ?-+", "", b, flags=re.I)
    b = re.sub(r"This email and any attachments are confidential[^\n]*", "", b)
    return b


def _month_end(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(body, sent):
    """Return (date|None, found_text: bool, ambiguous: bool)."""
    s = dt.date.fromisoformat(sent)
    t = body
    low = t.lower()
    cands = []
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        cands.append(_mk(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})\b", t):
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        a, b2 = int(m.group(1)), int(m.group(2))
        if a > 12 >= b2:  # clearly day-first
            a, b2 = b2, a
        cands.append(_mk(y, a, b2))
    mon = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + mon + r"[\s\-,]+(\d{4})\b", low):
        cands.append(_mk(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1))))
    for m in re.finditer(r"\b" + mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low):
        cands.append(_mk(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2))))
    # day + month without year / month + day without year -> most recent such date not after sent
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + mon + r"(?![\s\-,]*\d{4})(?![a-z])", low):
        c = _mk(s.year, MONTHS[m.group(2)[:3]], int(m.group(1)))
        if c and c > s:
            c = _mk(s.year - 1, c.month, c.day)
        cands.append(c)
    for m in re.finditer(r"\b" + mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!,?\s+\d{4})(?![\d:])", low):
        c = _mk(s.year, MONTHS[m.group(1)[:3]], int(m.group(2)))
        if c and c > s:
            c = _mk(s.year - 1, c.month, c.day)
        cands.append(c)
    if re.search(r"\b(year[- ]end|end of last year|end of (the )?previous year|last year[- ]end)\b", low):
        cands.append(dt.date(s.year - 1, 12, 31))
    if re.search(r"\byesterday\b", low):
        cands.append(s - dt.timedelta(days=1))
    if re.search(r"\btoday\b", low):
        cands.append(s)
    if re.search(r"(end of last month|last day of last month|month[- ]end|end of (the )?previous month|last month[- ]end)", low):
        first = s.replace(day=1)
        cands.append(first - dt.timedelta(days=1))
    cands = [c for c in cands if c is not None]
    uniq = sorted(set(cands))
    if not uniq:
        return None, False, False
    if len(uniq) > 1:
        return None, True, True
    return uniq[0], True, False


def parse_qty(body):
    """Client's stated figure, if any."""
    low = body.lower()
    pats = [r"(?:we have|we show|we hold|we see|we expect|we believe (?:we hold|it is|it's)?|records show|our figure is|our figure|books show|our position is|we record|we calculate)\s*:?\s*(?:a (?:position|holding) of\s*)?(-?[\d,]*\d(?:\.\d+)?\s*(?:k|mm|mn|m|million|thousand)?)\b"]
    for p in pats:
        m = re.search(p, low)
        if m:
            return _num(m.group(1))
    return None


def _num(s):
    s = s.strip().replace(",", "").replace(" ", "")
    mult = 1
    for suf, k in (("million", 10**6), ("thousand", 10**3), ("mm", 10**6), ("mn", 10**6), ("m", 10**6), ("k", 10**3)):
        if s.endswith(suf):
            s = s[: -len(suf)]; mult = k; break
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_mention(text):
    if not text:
        return None
    t = text.strip().strip(".,;:()[]\"'")
    t = re.sub(r"(?i)^(our |the )?(a/c|acct\.?|account|fund|portfolio)\s+", "", t).strip()
    return t or None


def resolve_account(text, tools):
    t = _clean_mention(text)
    if not t:
        return None, "missing"
    hits = tools.search_accounts(t)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if len(hits) == 0:
        return None, "notfound"
    return None, "ambiguous"


def resolve_instrument(text, tools):
    text = _clean_mention(text)
    if not text:
        return None, "missing"
    hits = tools.search_instruments(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if not hits:
        return None, "notfound"
    # prefer current-ticker / id / name exact match over former ticker
    t = text.strip().lower()
    cur = [h for h in hits if t in (h["ticker"].lower(), h["id"].lower(), h["name"].lower())]
    if len(cur) == 1:
        return cur[0]["id"], "ok"
    return None, "ambiguous"


def settled_qty(tools, acc, ins, as_of):
    splits = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for sp in splits:
            if t["date"] < sp["date"] <= as_of:
                q = q * sp["ratio"]
        total += q
    return total


def respond(request, tools):
    m = request.get("mentions") or {}
    sent = request["sent"]
    body = _clean_body(request.get("body", ""))
    sender = (request.get("from") or "").strip().lower()

    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # 1. account
    acc_text = m.get("account_text")
    if not acc_text:
        ids = sorted(set(re.findall(r"\b(?:ACC|SA)-\d+\b", body, flags=re.I)))
        if len(ids) == 1:
            acc_text = ids[0]
    acc, ast = resolve_account(acc_text, tools)
    if ast == "missing":
        live = sorted({e["account_id"] for e in ents})
        if len(live) == 1:
            acc, ast = live[0], "ok"
    if ast != "ok":
        if ast == "missing" and not contact:
            return _resp("REQUEST_AUTHORIZATION")
        return _resp("REQUEST_INFO")

    # 3. authorization
    if not contact:
        return _resp("REQUEST_AUTHORIZATION")
    ok = [e for e in ents if e["account_id"] == acc and e["level"] >= MIN_LEVEL and e["expires"] >= sent]
    if not ok:
        return _resp("REQUEST_AUTHORIZATION")

    # 4. instrument
    ins_text = m.get("instrument_text")
    if not ins_text:
        isins = sorted(set(re.findall(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", body)))
        if len(isins) == 1:
            ins_text = isins[0]
    ins, ist = resolve_instrument(ins_text, tools)
    if ist != "ok":
        return _resp("REQUEST_INFO")

    # 2. date validity (desk asks for a usable date before anything else)
    d, found, amb = parse_date(body, sent)
    if amb:
        return _resp("REQUEST_INFO")
    assumed = False
    if d is None:
        d = dt.date.fromisoformat(sent); assumed = True
    if d > dt.date.fromisoformat(sent):
        return _resp("REQUEST_INFO")
    if not tools.get_calendar(d.isoformat())["business_day"]:
        return _resp("REQUEST_INFO")
    as_of = d.isoformat()

    # 5. client-level controls
    prof = tools.get_client_profile(acc) or {}
    if prof.get("no_email_confirm"):
        return _resp("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)

    settled = settled_qty(tools, acc, ins, as_of)

    if settled <= 0:
        if settled < 0:
            return _resp("ESCALATE", account_id=acc, instrument_id=ins)
        return _resp("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed)

    # 6. client figure check
    claimed = parse_qty(body)
    if claimed is not None and abs(claimed - settled) > FIGURE_TOLERANCE * abs(settled):
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)
    if settled >= LARGE_POSITION:
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)


    pend, pdate = None, None
    pi = [x for x in tools.get_instructions(acc, ins)
          if x["status"] == "matched" and x["settle_date"] > as_of and x["qty"] >= MIN_PENDING_QTY]
    if pi:
        pi.sort(key=lambda x: (x["settle_date"], x["id"]))
        pend = sum(x["qty"] for x in pi)
        pdate = pi[-1]["settle_date"]
    return _resp("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed,
                 settled=settled, pending=pend, pending_date=pdate)
