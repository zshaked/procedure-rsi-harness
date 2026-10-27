"""Induced procedure for the holdings-confirmation desk. Standard library only; state via `tools`."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 3
MISMATCH_TOLERANCE = 0.05   # client figure may differ from ours by up to 5%
LARGE_POSITION = 1_000_000   # positions this size are always escalated
PENDING_MIN_QTY = 1000     # small matched instructions are not reported as pending (see NOTES)


def _out(outcome, account_id=None, instrument_id=None, as_of=None, as_of_assumed=False,
         settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": as_of_assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


def _strip_forward_header(body):
    lines = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s.startswith("---------- Forwarded") or re.match(r"^(From|Date|To|Subject|Sent):", s):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month_end_prev(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Return (date, found_flag). found_flag False means no date in text."""
    t = text
    tl = t.lower()
    # relative phrases
    if re.search(r"\byesterday\b", tl):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b|\bclose of business today\b", tl):
        return sent, True
    if re.search(r"(end of last month|last day of last month|month[- ]end|end of (the )?previous month|last month[- ]end)", tl):
        return _month_end_prev(sent), True
    # "end of December" -> last day of most recent such month not after sent
    m = re.search(r"\bend of ([A-Za-z]{3,9})\b(?:,? (\d{4}))?", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        mo = MONTHS[m.group(1)[:3].lower()]
        y = int(m.group(2)) if m.group(2) else (sent.year if mo <= sent.month else sent.year - 1)
        nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
        return nxt - dt.timedelta(days=1), True
    # ISO
    m = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), True
    # 31-Dec-2025
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ](\d{4})\b", t)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _mk(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1))), True
    # January 8, 2026
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        return _mk(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2))), True
    # 31 Dec 2025 handled above; Dec 31 2025 handled above; D.M.YYYY
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t)
    if m:
        return _mk(int(m.group(3)), int(m.group(2)), int(m.group(1))), True
    # US numeric M/D/YYYY
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _mk(int(m.group(3)), int(m.group(1)), int(m.group(2))), True
    return None, False


def parse_qty(text):
    """Client's own figure, if stated. Returns int or None."""
    pats = [r"we have\s+(-?\d[\d.,]*(?:[ ]?(?:k|mm|m)\b)?)\s+(?:shares|units)",
            r"our records show\s+(-?\d[\d.,]*(?:[ ]?(?:k|mm|m)\b)?)",
            r"our figure is\s+(-?\d[\d.,]*(?:[ ]?(?:k|mm|m)\b)?)",
            r"we show\s+(-?\d[\d.,]*(?:[ ]?(?:k|mm|m)\b)?)",
            r"(-?\d[\d.,]*(?:[ ]?(?:k|mm|m)\b)?)\s+(?:shares|units) on our books"]
    tl = text.lower()
    for p in pats:
        m = re.search(p, tl)
        if m:
            return _to_int(m.group(1))
    return None


def _to_int(s):
    s = s.strip().replace(",", "").replace(" ", "")
    mult = 1
    if s.endswith("mm"):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    s = s.rstrip(".")
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def _clean(span):
    if span is None:
        return None
    s = span.strip().strip(".,;:()?!\"'")
    s = re.sub(r"^(our |the )?(a/c|acct|account|fund)\s+", "", s, flags=re.I)
    return s.strip() or None


def settled_qty(tools, account_id, instrument_id, as_of):
    iso = as_of.isoformat()
    splits = [c for c in tools.get_corporate_actions(instrument_id) if c.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= iso:
                q *= s["ratio"]
        total += q
    return total


def respond(request, tools):
    sender = (request.get("from") or "").strip().lower()
    sent = dt.date.fromisoformat(request["sent"])
    body = _strip_forward_header(request.get("body") or "")
    mentions = request.get("mentions") or {}
    acct_text = _clean(mentions.get("account_text"))
    inst_text = _clean(mentions.get("instrument_text"))

    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # 1. Resolve the account
    if acct_text:
        hits = tools.search_accounts(acct_text)
        if len(hits) != 1:
            return _out("REQUEST_INFO")
        account_id = hits[0]["id"]
    else:
        # "our fund" etc.: infer only if the sender is tied to exactly one account
        live = sorted({e["account_id"] for e in ents if e["expires"] >= sent.isoformat()})
        if not live:
            return _out("REQUEST_AUTHORIZATION")
        if len(live) != 1:
            return _out("REQUEST_INFO")
        account_id = live[0]

    # 2. Sender authorization for that account
    ok = any(e["account_id"] == account_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent.isoformat()
             for e in ents)
    if not ok:
        return _out("REQUEST_AUTHORIZATION")

    # 3. Resolve the instrument
    if not inst_text:
        return _out("REQUEST_INFO")
    ihits = tools.search_instruments(inst_text)
    if len(ihits) != 1:
        return _out("REQUEST_INFO")
    instrument_id = ihits[0]["id"]

    # 4. Date
    as_of, found = parse_date(body, sent)
    assumed = False
    if not found:
        as_of, assumed = sent, True
    if as_of is None or as_of > sent:
        return _out("REQUEST_INFO")
    if not tools.get_calendar(as_of.isoformat())["business_day"]:
        return _out("REQUEST_INFO")   # desk asks which date they want

    # 5. Client restrictions
    prof = tools.get_client_profile(account_id) or {}
    if prof.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _out("ESCALATE", account_id, instrument_id)

    # 6. Figure
    settled = settled_qty(tools, account_id, instrument_id, as_of)
    if settled == 0:   # not held, whatever figure the client quotes
        return _out("NOT_HELD", account_id, instrument_id, as_of.isoformat(), assumed)
    claimed = parse_qty(body)
    if claimed is not None:
        base = abs(settled) if settled else abs(claimed)
        if base and abs(claimed - settled) > MISMATCH_TOLERANCE * base:
            return _out("ESCALATE", account_id, instrument_id)   # their number doesn't match closely enough
    if abs(settled) >= LARGE_POSITION:
        return _out("ESCALATE", account_id, instrument_id)       # large positions always reviewed


    pend = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and as_of.isoformat() < x["settle_date"]
            and abs(x["qty"]) >= PENDING_MIN_QTY]
    pending = pending_date = None
    if pend:
        pending = sum(x["qty"] for x in pend)
        pending_date = max(x["settle_date"] for x in pend)
    return _out("CONFIRMED", account_id, instrument_id, as_of.isoformat(), assumed,
                settled, pending, pending_date)
