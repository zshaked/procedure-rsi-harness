"""Induced procedure for the holdings-confirmation desk."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

MIN_LEVEL = 2


def _out(outcome, acct=None, inst=None, as_of=None, assumed=False, settled=None,
         pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": acct, "instrument_id": inst,
            "as_of": as_of, "as_of_assumed": assumed if as_of else False,
            "settled": settled, "pending": pending, "pending_date": pending_date}


# ---------------------------------------------------------------- text helpers
def _clean_body(body):
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if re.match(r"^-+\s*Forwarded message", s, re.I):
            continue
        if re.match(r"^(From|Date|Sent|To|Subject|Cc):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _month_end(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(body, sent):
    """Return (date|None, found_any_reference)."""
    t = body
    tl = t.lower()
    # ISO
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))), True
    # M/D/YYYY
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _safe_date(int(m.group(3)), int(m.group(1)), int(m.group(2))), True
    # D-Mon-YYYY
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]+(\d{4})\b", t)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _safe_date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1))), True
    # Month D, YYYY
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        return _safe_date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2))), True
    # year-less "March 3" / "3 March": most recent such date not after the email
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?\b", t)
    m2 = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\b", t)
    for mm, mi, di in ((m, 1, 2), (m2, 2, 1)):
        if mm and mm.group(mi)[:3].lower() in MONTHS:
            mon = MONTHS[mm.group(mi)[:3].lower()]
            d = _safe_date(sent.year, mon, int(mm.group(di)))
            if d and d > sent:
                d = _safe_date(sent.year - 1, mon, int(mm.group(di)))
            if d:
                return d, True
    if re.search(r"\byesterday\b", tl):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b", tl):
        return sent, True
    if re.search(r"(end of last month|last day of last month|month[- ]end|end of (the )?month|last month[- ]end|previous month[- ]end)", tl):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1), True
    return None, False


def parse_qty_str(s):
    """Return (value, rounding unit) or None."""
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.(\d+))?)\s*(mm|m|k|bn|b)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"k": 1e3, "m": 1e6, "mm": 1e6, "bn": 1e9, "b": 1e9}.get(m.group(3) or "", 1)
    decimals = len(m.group(2) or "")
    unit = mult / (10 ** decimals) if mult > 1 else 1
    return int(round(v * mult)), unit


TOLERANCE = 0.01


def _figures_agree(fig, ours):
    """fig is (value, precision) - precision is the rounding unit implied by k/mm notation."""
    val, unit = fig
    if unit > 1:
        if abs(ours - val) <= unit / 2.0:
            return True
    if ours == val:
        return True
    if ours == 0 or val == 0:
        return False
    return abs(val - ours) <= TOLERANCE * abs(ours)


def parse_client_figure(body):
    pats = [
        r"we show\s+(\d[\d,]*(?:\.\d+)?(?: ?(?:mm|k|m|bn)\b)?)",
        r"our figure is\s+(\d[\d,]*(?:\.\d+)?(?: ?(?:mm|k|m|bn)\b)?)",
        r"we have\s+(\d[\d,]*(?:\.\d+)?(?: ?(?:mm|k|m|bn)\b)?)\s*(?:shares|units)",
        r"our records show\s+(\d[\d,]*(?:\.\d+)?(?: ?(?:mm|k|m|bn)\b)?)",
        r"our books show\s+(\d[\d,]*(?:\.\d+)?(?: ?(?:mm|k|m|bn)\b)?)",
        r"we hold\s+(\d[\d,]*(?:\.\d+)?(?: ?(?:mm|k|m|bn)\b)?)",
        r"(?:figure|position|balance|holding) of\s+(\d[\d,]*(?:\.\d+)?(?: ?(?:mm|k|m|bn)\b)?)",
    ]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            q = parse_qty_str(m.group(1).rstrip("."))
            if q is not None:
                return q
    return None


# ---------------------------------------------------------------- resolution
_ACC_RE = re.compile(r"\b(ACC-\d+|SA-\d+)\b", re.I)
_ISIN_RE = re.compile(r"\b([A-Z]{2}\d{9}[0-9A-Z])\b")
_PREFIX_RE = re.compile(r"^(?:our|the|my)?\s*(?:account|acct|a/c|fund|portfolio)\s*[:#]?\s*", re.I)


def resolve_account(text, body, tools):
    cands = []
    if text:
        t = text.strip().strip(".,;:()")
        cands.append(t)
        t2 = _PREFIX_RE.sub("", t).strip()
        if t2 and t2 != t:
            cands.append(t2)
        m = _ACC_RE.search(t)
        if m:
            cands.insert(0, m.group(1).upper())
    else:
        m = _ACC_RE.search(body)
        if m:
            cands.append(m.group(1).upper())
    for c in cands:
        hits = tools.search_accounts(c)
        if hits:
            return hits
    return []


def resolve_instrument(text, body, tools):
    cands = []
    if text:
        t = text.strip().strip(".,;:()")
        cands.append(t)
        m = _ISIN_RE.search(t)
        if m:
            cands.insert(0, m.group(1))
    else:
        m = _ISIN_RE.search(body)
        if m:
            cands.append(m.group(1))
    for c in cands:
        hits = tools.search_instruments(c)
        if hits:
            # dedupe by id
            seen = {}
            for h in hits:
                seen[h["id"]] = h
            return list(seen.values())
    return []


# ---------------------------------------------------------------- authorization
def authorized(sender, account_id, sent, tools):
    contact = tools.get_contact(sender)
    if not contact:
        return False
    prof = tools.get_client_profile(account_id) or {}
    domain = sender.lower().rsplit("@", 1)[-1]
    if domain not in [d.lower() for d in prof.get("domains", [])]:
        return False
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] != account_id:
            continue
        if e.get("expires") and e["expires"] < sent.isoformat():
            continue
        if e.get("level", 0) >= MIN_LEVEL:
            return True
    return False


# ---------------------------------------------------------------- position
def settled_position(account_id, instrument_id, as_of, tools, adjust=True):
    led = tools.get_ledger(account_id, instrument_id)
    splits = [c for c in tools.get_corporate_actions(instrument_id) if c.get("type") == "split"]
    total = 0
    for t in led:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in (splits if adjust else []):
            if t["date"] < s["date"] <= as_of:
                q = q * s["ratio"]
        total += q
    return total


def pending_info(account_id, instrument_id, as_of, tools):
    pend = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    if not pend:
        return None, None
    qty = sum(x["qty"] for x in pend)
    date = max(x["settle_date"] for x in pend)
    return qty, date


# ---------------------------------------------------------------- main
def respond(request, tools):
    sender = request.get("from", "")
    sent = dt.date.fromisoformat(request["sent"][:10])
    body = _clean_body(request.get("body", ""))
    mentions = request.get("mentions") or {}

    accs = resolve_account(mentions.get("account_text"), body, tools)
    insts = resolve_instrument(mentions.get("instrument_text"), body, tools)
    if len(accs) != 1 or len(insts) != 1:
        return _out("REQUEST_INFO")
    acct = accs[0]["id"]
    inst = insts[0]["id"]

    if not authorized(sender, acct, sent, tools):
        return _out("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(acct) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", acct, inst)

    req_date, found = parse_date(body, sent)
    assumed = False
    if req_date is None:
        if found:
            return _out("REQUEST_INFO")
        req_date = sent
        assumed = True
    if req_date > sent:
        return _out("REQUEST_INFO")
    cal = tools.get_calendar(req_date.isoformat())
    as_of = req_date.isoformat() if cal["business_day"] else cal["previous_business_day"]
    if assumed:
        # no date given: last business day before the email
        as_of = tools.get_calendar(sent.isoformat())["previous_business_day"]

    settled = settled_position(acct, inst, as_of, tools)
    pq, pd = pending_info(acct, inst, as_of, tools)
    total = settled + (pq or 0)
    if settled == 0:
        # nothing held: say so, regardless of any figure the client quotes
        return _out("NOT_HELD", acct, inst, as_of, assumed)

    figure = parse_client_figure(body)
    if figure is not None and not _figures_agree(figure, total):
        # a client quoting the pre-split quantity is not a real break
        raw = settled_position(acct, inst, as_of, tools, adjust=False)
        explained = raw != settled and (_figures_agree(figure, raw + (pq or 0))
                                        or _figures_agree(figure, raw))
        if not explained:
            return _out("ESCALATE", acct, inst)
    return _out("CONFIRMED", acct, inst, as_of, assumed, settled, pq, pd)
