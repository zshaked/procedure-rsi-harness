"""Operations-desk procedure: confirm a client's holding of a security.

Deterministic; standard library + the `tools` argument only.

Order of decisions (first that applies wins):
  1. account / instrument must each resolve to exactly one record      -> REQUEST_INFO
  2. sender authorised: known contact, sender domain on the client's
     profile, unexpired entitlement of level >= 2 for that account      -> REQUEST_AUTHORIZATION
  3. account under legal hold (or flagged no_email_confirm - a guess)   -> ESCALATE
  4. requested date in the future                                      -> REQUEST_INFO
  5. figure = ledger over ALL sub-accounts up to and including as_of,
     split-adjusted; non-positive                                       -> NOT_HELD
  6. stated client figure disagrees with settled + matched pending      -> ESCALATE
  7. otherwise                                                          -> CONFIRMED (+ pending)
"""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

MIN_LEVEL = 2          # entitlement level needed to receive a confirmation
REL_TOL = 0.01         # a stated figure within 1% of ours counts as agreeing


# --------------------------------------------------------------------------- text helpers
def _clean_body(body):
    """Drop forwarded-message header lines and boilerplate footers."""
    out = []
    for ln in (body or "").split("\n"):
        s = ln.strip()
        if re.match(r"^-{3,}\s*forwarded message\s*-{3,}$", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if re.match(r"^this email and any attachments", s, re.I):
            continue
        out.append(ln)
    return "\n".join(out)


def _mon(s):
    return MONTHS.get(s[:3].lower())


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _last_day_of_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _find_dates(text, sent):
    """Return sorted list of (start, end, date, kind) for date expressions found in text."""
    found = []
    taken = []

    def add(m, d, kind):
        if d is None:
            return
        for (a, b) in taken:
            if m.start() < b and m.end() > a:
                return
        taken.append((m.start(), m.end()))
        found.append((m.start(), m.end(), d, kind))

    for m in re.finditer(r"(?<![\d/-])(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?![\d/])", text):
        add(m, _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "abs")
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])", text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _safe_date(y, a, b)          # US order first (M/D/Y)
        if d is None:
            d = _safe_date(y, b, a)
        add(m, d, "abs")
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2})(?![\d/])", text):
        a, b, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
        d = _safe_date(y, a, b)
        if d is None:
            d = _safe_date(y, b, a)
        add(m, d, "abs")
    for m in re.finditer(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[-\s]+(?:of\s+)?([A-Za-z]{3,9})\.?,?[-\s]+(\d{4})(?!\d)", text):
        mo = _mon(m.group(2))
        if mo and m.group(2).lower()[:3] in MONTHS:
            add(m, _safe_date(int(m.group(3)), mo, int(m.group(1))), "abs")
    for m in re.finditer(r"(?<!\d)(\d{1,2})[-\s]([A-Za-z]{3,9})\.?[-\s](\d{2})(?![\d/])", text):
        mo = _mon(m.group(2))
        if mo:
            add(m, _safe_date(2000 + int(m.group(3)), mo, int(m.group(1))), "abs")
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)", text):
        mo = _mon(m.group(1))
        if mo and m.group(1).lower()[:3] in MONTHS:
            add(m, _safe_date(int(m.group(3)), mo, int(m.group(2))), "abs")

    low = text.lower()
    rel = [
        (r"\b(?:the\s+)?(?:last|final)\s+(?:calendar\s+|business\s+)?day\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+month\b", "prev_month_end"),
        (r"\bend\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+month\b", "prev_month_end"),
        (r"\b(?:last|previous|prior)\s+month[\s-]*end\b", "prev_month_end"),
        (r"\bmonth[\s-]*end\b", "prev_month_end"),
        (r"\b(?:end\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+quarter|(?:last|previous|prior)\s+quarter[\s-]*end|quarter[\s-]*end)\b", "prev_quarter_end"),
        (r"\b(?:end\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+year|year[\s-]*end)\b", "prev_year_end"),
        (r"\b(?:end\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+week)\b", "prev_week_end"),
        (r"\b(?:last|previous|prior)\s+business\s+day\b", "prev_bday"),
        (r"\b(?:last|previous)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "last_weekday"),
        (r"\byesterday\b", "yesterday"),
        (r"\btoday\b", "today"),
    ]
    for pat, kind in rel:
        for m in re.finditer(pat, low):
            if any(m.start() < b and m.end() > a for (a, b) in taken):
                continue
            if sent is None:
                continue
            if kind == "prev_month_end":
                d = _last_day_of_prev_month(sent)
            elif kind == "prev_quarter_end":
                qstart = dt.date(sent.year, 3 * ((sent.month - 1) // 3) + 1, 1)
                d = qstart - dt.timedelta(days=1)
            elif kind == "prev_year_end":
                d = dt.date(sent.year - 1, 12, 31)
            elif kind == "prev_week_end":
                d = sent - dt.timedelta(days=sent.weekday() + 3)  # Friday of previous week
            elif kind == "prev_bday":
                d = "PREV_BDAY"
            elif kind == "last_weekday":
                wd = WEEKDAYS.index(m.group(1)[:3])
                delta = (sent.weekday() - wd) % 7
                d = sent - dt.timedelta(days=delta or 7)
            elif kind == "yesterday":
                d = sent - dt.timedelta(days=1)
            else:
                d = sent
            taken.append((m.start(), m.end()))
            found.append((m.start(), m.end(), d, "rel"))
    found.sort(key=lambda x: x[0])
    return found


_UNIT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mln": 1e6, "million": 1e6,
         "b": 1e9, "bn": 1e9, "billion": 1e9}

_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(mm|mln|million|thousand|bn|billion|k|m|b)?"


def _parse_num(num, unit):
    num = num.replace(",", "").rstrip(".")
    unit = (unit or "").lower()
    try:
        val = float(num)
    except ValueError:
        return None
    tol = 0.0
    if unit:
        mult = _UNIT[unit]
        dec = len(num.split(".")[1]) if "." in num else 0
        tol = 0.5 * mult * (10 ** -dec)
        val = val * mult
    return int(round(val)), tol


def _find_claim(text):
    """Quantity the client says they hold: (value:int, tolerance:float) or None."""
    lead = (r"(?:\bwe\s+show|\bwe\s+have|\bour\s+figure\s+is|\bfigure\s+is|\bour\s+records\s+show|"
            r"\brecords\s+show|\bour\s+books\s+show|\bbooks\s+show|\bwe\s+hold|\bwe\s+are\s+holding|"
            r"\bour\s+records\s+indicate|\bwe\s+record|\bwe\s+see|\bour\s+(?:position|balance|holding)\s+is)")
    pat = re.compile(lead + r"\s*:?\s*(?:approximately\s+|approx\.?\s+|about\s+|circa\s+|c\.\s*)?" + _NUM + r"\b", re.I)
    m = pat.search(text)
    if m:
        return _parse_num(m.group(1), m.group(2))
    pat2 = re.compile(_NUM + r"\s+(?:shares|units)\b", re.I)
    m = pat2.search(text)
    if m:
        return _parse_num(m.group(1), m.group(2))
    return None


# --------------------------------------------------------------------------- core logic
def _prev_bday(tools, d):
    return dt.date.fromisoformat(tools.get_calendar(d.isoformat())["previous_business_day"])


def _is_bday(tools, d):
    return tools.get_calendar(d.isoformat())["business_day"]


def _resolve_account(tools, text):
    if not text or not text.strip():
        return None, "no_account"
    t = text.strip()
    hits = tools.search_accounts(t)
    if not hits:
        hits = tools.search_accounts(re.sub(r"\s+", " ", t))
    if not hits and re.match(r"(?i)^(acc|sa)[\s_]?-?\s?\d+$", t):
        hits = tools.search_accounts(re.sub(r"(?i)^(acc|sa)[\s_]?-?\s?", lambda m: m.group(1).upper() + "-", t))
    ids = sorted({h["id"] for h in hits})
    if len(ids) == 1:
        return ids[0], None
    return None, ("ambiguous_account" if ids else "unknown_account")


def _resolve_instrument(tools, text):
    if not text or not text.strip():
        return None, "no_instrument"
    hits = tools.search_instruments(text.strip())
    ids = sorted({h["id"] for h in hits})
    if len(ids) == 1:
        return ids[0], None
    return None, ("ambiguous_instrument" if ids else "unknown_instrument")


def _sender(request):
    s = (request.get("from") or "").strip()
    m = re.search(r"<([^>]+)>", s)
    if m:
        s = m.group(1).strip()
    return s.lower()


def _domain(email):
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in (email or "") else ""


def _authorized(tools, request, account_id, sent):
    sender = _sender(request)
    contact = tools.get_contact(sender)
    if not contact:
        return False, "no_contact"
    prof = tools.get_client_profile(account_id) or {}
    doms = [d.lower() for d in prof.get("domains", [])]
    if _domain(sender) not in doms:
        return False, "domain_mismatch"
    ok = False
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] != account_id:
            continue
        if e["level"] < MIN_LEVEL:
            continue
        if e["expires"] and e["expires"] < sent.isoformat():
            continue
        ok = True
    if not ok:
        return False, "no_entitlement"
    return True, None


def _settled_at(tools, account_id, instrument_id, as_of):
    """Settled quantity at end of as_of across all sub-accounts, split-adjusted."""
    ledger = tools.get_ledger(account_id, instrument_id)
    splits = tools.get_corporate_actions(instrument_id)
    total = 0
    iso = as_of.isoformat()
    for t in ledger:
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= iso and t["date"] < s["date"]:
                q = q * s["ratio"]
        total += q
    return total


def _pending(tools, account_id, instrument_id, as_of):
    """Matched instructions still to settle after as_of: (total qty, earliest settle date)."""
    iso = as_of.isoformat()
    rows = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > iso]
    if not rows:
        return None, None
    return sum(x["qty"] for x in rows), min(x["settle_date"] for x in rows)


def analyze(request, tools):
    """Return (response, trace)."""
    trace = []
    resp = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    m = request.get("mentions") or {}
    sent = dt.date.fromisoformat(request["sent"])

    acct, why = _resolve_account(tools, m.get("account_text"))
    if why:
        trace.append(why)
        resp["outcome"] = "REQUEST_INFO"
        return resp, trace
    inst, why = _resolve_instrument(tools, m.get("instrument_text"))
    if why:
        trace.append(why)
        resp["outcome"] = "REQUEST_INFO"
        return resp, trace

    ok, why = _authorized(tools, request, acct, sent)
    if not ok:
        trace.append(why)
        resp["outcome"] = "REQUEST_AUTHORIZATION"
        return resp, trace

    body = _clean_body(request.get("body", ""))
    dates = _find_dates(body, sent)
    assumed = False
    future = False
    if dates:
        requested = dates[0][2]
        if requested == "PREV_BDAY":
            requested = _prev_bday(tools, sent)
        trace.append("date_found:%s" % requested.isoformat())
        future = requested > sent
    else:
        requested = sent
        assumed = True
        trace.append("date_assumed")
    as_of = requested
    if not future and not _is_bday(tools, as_of):
        as_of = _prev_bday(tools, as_of)
        trace.append("date_rolled")

    prof = tools.get_client_profile(acct) or {}
    resp.update(account_id=acct, instrument_id=inst)
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        trace.append("legal_hold" if prof.get("legal_hold") else "no_email_confirm")
        if not future:
            resp.update(as_of=as_of.isoformat(), as_of_assumed=assumed,
                        settled=_settled_at(tools, acct, inst, as_of))
        resp["outcome"] = "ESCALATE"
        return resp, trace

    if future:
        trace.append("future_date")
        resp.update(outcome="REQUEST_INFO", account_id=None, instrument_id=None)
        return resp, trace

    resp.update(as_of=as_of.isoformat(), as_of_assumed=assumed)
    settled = _settled_at(tools, acct, inst, as_of)
    if settled <= 0:
        trace.append("not_held")
        resp.update(outcome="NOT_HELD", settled=None)
        return resp, trace

    resp["settled"] = settled
    pend, pdate = _pending(tools, acct, inst, as_of)
    claim = _find_claim(body)
    if claim is not None:
        val, tol = claim
        total = settled + (pend or 0)
        if abs(val - total) > max(tol, REL_TOL * total):
            trace.append("claim_mismatch:%s vs %s" % (val, total))
            resp["outcome"] = "ESCALATE"
            return resp, trace

    resp.update(outcome="CONFIRMED", pending=pend, pending_date=pdate)
    return resp, trace


def respond(request, tools):
    try:
        resp, _ = analyze(request, tools)
    except Exception:
        resp = {"outcome": "REQUEST_INFO", "account_id": None, "instrument_id": None, "as_of": None,
                "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    return resp
