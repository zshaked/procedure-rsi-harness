"""Holding-confirmation desk procedure (see spec.md). Standard library only; state via `tools`."""
import datetime as dt
import re

SIZE_LIMIT = 1_000_000      # settled positions at/above this are escalated
TOLERANCE = 0.05            # client-stated figure must be within 5% of ours
PENDING_WINDOW_DAYS = 60    # matched instructions settling after as_of and within this many days of the email

_MON = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MONRX = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


def _empty():
    return {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _mk(outcome, **kw):
    r = _empty()
    r["outcome"] = outcome
    r.update(kw)
    return r


def _clean_body(body):
    # drop forwarded-message headers so their Date: line is not read as the position date
    lines = []
    for ln in body.splitlines():
        if re.match(r"\s*(From|Date|Sent|To|Subject|Cc)\s*:", ln, re.I):
            continue
        if re.match(r"\s*-{3,}.*forwarded", ln, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _safe_date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _last_day_prev_month(s):
    return s.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Returns (date|None, found_flag). found_flag False => no date given."""
    s = dt.date.fromisoformat(sent)
    b = _clean_body(body)
    low = b.lower()
    if re.search(r"\bday before yesterday\b", low):
        return s - dt.timedelta(days=2), True
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), True
    if re.search(r"\b(today|close of business today|cob today)\b", low):
        return s, True
    if re.search(r"(end of last month|last day of (the )?(last|previous|prior) month|"
                 r"end of (the )?(previous|prior) month|month-end|month end|last month-end|"
                 r"last month end)", low):
        return _last_day_prev_month(s), True
    if re.search(r"end of (last|previous|prior) year|year-end|year end", low):
        return dt.date(s.year - 1, 12, 31), True
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", b)
    if m:
        d = _safe_date(m[1], m[2], m[3])
        if d:
            return d, True
    m = re.search(r"\b(\d{1,2})[-/ ]" + _MONRX + r"[-/ ,]*(\d{4})\b", low)
    if m:
        d = _safe_date(m[3], _MON[m[2][:3]], m[1])
        if d:
            return d, True
    m = re.search(r"\b" + _MONRX + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low)
    if m:
        d = _safe_date(m[3], _MON[m[1][:3]], m[2])
        if d:
            return d, True
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONRX + r",?\s+(\d{4})\b", low)
    if m:
        d = _safe_date(m[3], _MON[m[2][:3]], m[1])
        if d:
            return d, True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", b)
    if m:
        y = int(m[3])
        if y < 100:
            y += 2000
        a, c = int(m[1]), int(m[2])
        d = _safe_date(y, a, c) if a <= 12 else _safe_date(y, c, a)  # US M/D/Y; D/M only if forced
        if d:
            return d, True
    # a date-like phrase we could not read
    if re.search(r"\b(as at|as of|position date)\b", low):
        tail = re.search(r"\b(as at|as of|position date)\b\s*([^\n?.]*)", low)
        if tail and re.search(r"\d", tail.group(2)):
            return None, True
    return None, False


def parse_qty(body):
    b = _clean_body(body)
    m = re.search(r"(?:our figure is|figure is|we have|records show|we show|our books show|"
                  r"we hold|our position is|we record)\s+(-?\(?[\d][\d,]*(?:\.\d+)?)\s*(mm|m|k|mn|million|thousand)?\b",
                  b, re.I)
    if not m:
        return None
    raw = m[1].replace(",", "").replace("(", "-")
    try:
        v = float(raw)
    except ValueError:
        return None
    u = (m[2] or "").lower()
    v *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6}.get(u, 1)
    return int(round(v))


_ACC_PREFIX = r"^(?:our\s+|the\s+)?(?:a/c|acct\.?|account|fund|portfolio|sub-account|subaccount)\s*(?:no\.?|number|#)?\s*:?\s*"


def _resolve_accounts(text, tools):
    cands = [text, re.sub(_ACC_PREFIX, "", text.strip(), flags=re.I)]
    for c in cands:
        c = c.strip().strip(".,;:()'\"")
        if not c:
            continue
        hits = tools.search_accounts(c)
        if hits:
            return sorted({h["id"] for h in hits})
    return []


def _resolve_instruments(text, tools):
    cands = [text, re.sub(r"^(?:our\s+)?(?:position in|holdings? (?:of|in)|shares of|isin|ticker)\s*:?\s*", "",
                          text.strip(), flags=re.I)]
    for c in cands:
        c = c.strip().strip(".,;:()'\"")
        if not c:
            continue
        hits = tools.search_instruments(c)
        if hits:
            return sorted({h["id"] for h in hits})
    return []


def _figure(tools, account_id, instrument_id, as_of):
    splits = tools.get_corporate_actions(instrument_id)
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for ca in splits:
            if ca.get("type") == "split" and t["date"] < ca["date"] <= as_of:
                q *= ca["ratio"]
        total += q
    return int(total)


def respond(request, tools):
    sent = request["sent"]
    body = request.get("body") or ""
    mentions = request.get("mentions") or {}
    acct_text = mentions.get("account_text")
    inst_text = mentions.get("instrument_text")

    contact = tools.get_contact(request.get("from") or "")
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    active = [e for e in ents if (e.get("expires") or "9999-12-31") >= sent]

    # 1. account
    if acct_text and acct_text.strip():
        accs = _resolve_accounts(acct_text, tools)
        if len(accs) != 1:
            return _mk("REQUEST_INFO")
    else:
        m = re.search(r"\b(ACC-\d+|SA-\d+)\b", body)
        if m:
            accs = _resolve_accounts(m[1], tools)
            if len(accs) != 1:
                return _mk("REQUEST_INFO")
        else:
            accs = sorted({e["account_id"] for e in active})
            if not accs:
                return _mk("REQUEST_AUTHORIZATION")
            if len(accs) != 1:
                return _mk("REQUEST_INFO")
    account_id = accs[0]

    # 2. authorization
    if not any(e["account_id"] == account_id and e.get("level", 0) >= 3 for e in active):
        return _mk("REQUEST_AUTHORIZATION")

    # 3. instrument
    if inst_text and inst_text.strip():
        ins = _resolve_instruments(inst_text, tools)
    else:
        ins = []
        m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", body)
        if m:
            ins = _resolve_instruments(m[1], tools)
    if len(ins) != 1:
        return _mk("REQUEST_INFO")
    instrument_id = ins[0]

    # 4. client profile restrictions
    prof = tools.get_client_profile(account_id) or {}
    if prof.get("legal_hold"):
        return _mk("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    if prof.get("no_email_confirm"):
        return _mk("REQUEST_AUTHORIZATION")

    # 5. date
    d, found = parse_date(body, sent)
    if found and d is None:
        return _mk("REQUEST_INFO")
    assumed = not found
    as_of = (d or dt.date.fromisoformat(sent)).isoformat()
    if as_of > sent:
        return _mk("REQUEST_INFO")
    if not tools.get_calendar(as_of)["business_day"]:
        return _mk("REQUEST_INFO")

    # 6. figure
    settled = _figure(tools, account_id, instrument_id, as_of)
    pend = [x for x in tools.get_instructions(account_id, instrument_id)
            if x.get("status") == "matched" and x["settle_date"] > as_of
            and x["settle_date"] <= (dt.date.fromisoformat(sent) + dt.timedelta(days=PENDING_WINDOW_DAYS)).isoformat()]
    pending = sum(x["qty"] for x in pend) if pend else None
    pending_date = max(x["settle_date"] for x in pend) if pend else None

    if settled < 0 or settled >= SIZE_LIMIT:
        return _mk("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    stated = parse_qty(body)
    if stated is not None:
        ok = False
        for ref in (settled, settled + (pending or 0)):
            if ref == stated or (ref != 0 and abs(stated - ref) <= TOLERANCE * abs(ref)):
                ok = True
        if not ok:
            return _mk("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    if settled == 0:
        return _mk("NOT_HELD", account_id=account_id, instrument_id=instrument_id,
                   as_of=as_of, as_of_assumed=assumed)
    return _mk("CONFIRMED", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
               as_of_assumed=assumed, settled=settled, pending=pending, pending_date=pending_date)
