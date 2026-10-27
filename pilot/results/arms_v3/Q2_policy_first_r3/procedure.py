"""Induced procedure for the holdings-confirmation desk. Deterministic, stdlib only."""
import calendar
import datetime as dt
import re

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9

MIN_LEVEL = 2
PENDING_MIN_QTY = 1000  # matched instructions below this are immaterial and not reported


def _out(outcome, account_id=None, instrument_id=None, as_of=None, as_of_assumed=False,
         settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": as_of_assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


# ---------------------------------------------------------------- parsing helpers
def _body(request):
    return request.get("body") or ""


def _parse_qty(s):
    s = s.strip().lower().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(mm|m|k)?", s)
    if not m:
        return None
    v = float(m.group(1))
    suf = m.group(2)
    if suf == "k":
        v *= 1_000
    elif suf in ("mm", "m"):
        v *= 1_000_000
    return int(round(v))


_NUM = r"(\d[\d,]*(?:\.\d+)?\s?(?:mm|m|k)?)\b"
_FIG_PATTERNS = [
    r"our figure is\s+" + _NUM,
    r"we show\s+" + _NUM,
    r"(?:our )?records show\s+" + _NUM,
    r"we have\s+" + _NUM,
    r"we hold\s+" + _NUM,
    r"our (?:position|holding|balance) is\s+" + _NUM,
    r"we (?:see|record|carry)\s+" + _NUM,
    r"our (?:books|records) (?:show|have)\s+" + _NUM,
    r"(?:figure|balance|position) of\s+" + _NUM,
]


def client_figure(body):
    low = body.lower()
    for p in _FIG_PATTERNS:
        m = re.search(p, low)
        if m:
            q = _parse_qty(m.group(1))
            if q is not None:
                return q
    return None


def _last_day_prev_month(d):
    first = d.replace(day=1)
    return first - dt.timedelta(days=1)


def _mk(y, mo, d):
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def parse_date(body, sent):
    """Return (date or None, found_flag). found_flag True if the body contained a date phrase."""
    low = body.lower()
    # strip forwarded-header 'Date:' lines so they are not taken as the position date
    low = re.sub(r"^\s*date:.*$", "", low, flags=re.M)
    low = re.sub(r"^\s*sent:.*$", "", low, flags=re.M)

    if re.search(r"\bend of last month\b|\bmonth[- ]end\b|\blast day of (?:the )?last month\b|"
                 r"\blast day of (?:the )?previous month\b|\bend of (?:the )?previous month\b|"
                 r"\blast month[- ]end\b|\bprior month[- ]end\b", low):
        return _last_day_prev_month(sent), True
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b", low):
        return sent, True

    # ISO 2026-01-15
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", low)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, True
    # 2026/01/15
    m = re.search(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b", low)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, True
    # US numeric 12/17/2025
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", low)
    if m:
        y = int(m.group(3))
        if y < 100:
            y += 2000
        d = _mk(y, int(m.group(1)), int(m.group(2)))
        if d:
            return d, True
    # 27-Jan-2026 / 27 Jan 2026 / Thu 25 Dec 2025 / 5 January 2026
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s]([a-z]{3,9})\.?[-\s,]+(\d{4})\b", low)
    if m and m.group(2) in MONTHS:
        d = _mk(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        if d:
            return d, True
    # December 29, 2025 / Jan 8 2026
    m = re.search(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low)
    if m and m.group(1) in MONTHS:
        d = _mk(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        if d:
            return d, True
    return None, False


def _clean_account_text(t):
    t = t.strip().strip(".,;:()[]\"'")
    t = re.sub(r"^(?:our\s+)?(?:account|acct|a/c|fund|the fund)\s*[:#]?\s*", "", t, flags=re.I)
    return t.strip().strip(".,;:()[]\"'")


def resolve_account(request, tools):
    """Return (status, account_id). status in ok|none|ambiguous."""
    m = request.get("mentions") or {}
    txt = m.get("account_text")
    cands = []
    if txt:
        t = _clean_account_text(txt)
        ids = re.findall(r"\b(?:ACC|SA)-\d+\b", t, flags=re.I)
        if ids:
            cands = [ids[0]]
        else:
            cands = [t]
    else:
        ids = re.findall(r"\b(?:ACC|SA)-\d+\b", _body(request), flags=re.I)
        if len(set(i.upper() for i in ids)) == 1:
            cands = [ids[0]]
    if not cands:
        return "none", None
    hits = tools.search_accounts(cands[0])
    if len(hits) == 1:
        return "ok", hits[0]["id"]
    if not hits:
        return "none", None
    return "ambiguous", None


def resolve_instrument(request, tools):
    m = request.get("mentions") or {}
    txt = m.get("instrument_text")
    if not txt:
        return "none", None
    t = txt.strip().strip(".,;:()[]\"'")
    t = re.sub(r"\s+(?:shares|units|stock|common stock|ordinary shares)$", "", t, flags=re.I).strip()
    hits = tools.search_instruments(t)
    if len(hits) == 1:
        return "ok", hits[0]["id"]
    if not hits:
        return "none", None
    return "ambiguous", None


def authorized(request, account_id, sent, tools):
    sender = (request.get("from") or "").strip().lower()
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    prof = tools.get_client_profile(account_id) or {}
    if domain not in [d.lower() for d in prof.get("domains", [])]:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent.isoformat():
            return True
    return False


def business_day_on_or_before(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def settled_position(account_id, instrument_id, as_of, tools, adjust=True):
    """Settled holding across ALL custody sub-accounts at close of as_of, split-adjusted
    (a split multiplies holdings recorded before its date). Not get_position_summary,
    which only covers the primary sub-account and the previous business day."""
    splits = tools.get_corporate_actions(instrument_id) if adjust else []
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s.get("type") == "split" and t["date"] < s["date"] <= as_of:
                q = q * s["ratio"]
        total += q
    return total


def pending_position(account_id, instrument_id, as_of, tools):
    pend = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > as_of
            and abs(x["qty"]) >= PENDING_MIN_QTY]
    if not pend:
        return None, None
    return sum(x["qty"] for x in pend), min(x["settle_date"] for x in pend)


# ---------------------------------------------------------------- main
def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    body = _body(request)

    a_status, account_id = resolve_account(request, tools)
    i_status, instrument_id = resolve_instrument(request, tools)
    if a_status != "ok" or i_status != "ok":
        return _out("REQUEST_INFO")

    if not authorized(request, account_id, sent, tools):
        return _out("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(account_id) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", account_id, instrument_id)

    req_date, found = parse_date(body, sent)
    assumed = False
    if not found:
        req_date = sent  # no date given: current position as of the day the email was sent
        assumed = True
    if req_date > sent:
        return _out("REQUEST_INFO")
    as_of = business_day_on_or_before(req_date, tools).isoformat()

    settled = settled_position(account_id, instrument_id, as_of, tools)
    pending, pdate = pending_position(account_id, instrument_id, as_of, tools)
    if settled <= 0:
        return _out("NOT_HELD", account_id, instrument_id, as_of, assumed, None)

    fig = client_figure(body)
    # the desk compares the client's figure with settled + (material) matched pending
    if fig is not None:
        raw = settled_position(account_id, instrument_id, as_of, tools, adjust=False)
        # a client figure that simply predates a split (unadjusted) is still a match
        ok = {settled + (pending or 0), raw + (pending or 0)}
        if fig not in ok:
            return _out("ESCALATE", account_id, instrument_id)

    return _out("CONFIRMED", account_id, instrument_id, as_of, assumed, settled, pending, pdate)
