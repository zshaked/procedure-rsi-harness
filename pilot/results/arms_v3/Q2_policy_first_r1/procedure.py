"""Induced procedure for the holdings-confirmation desk. Deterministic, stdlib only."""
import calendar
import datetime as dt
import re

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DOW_RE = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+)?"

FIGURE_PATTERNS = [
    r"we show\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m|million)?)(?![a-z])",
    r"our figure is\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m|million)?)(?![a-z])",
    r"(?:our )?records show\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m|million)?)(?![a-z])",
    r"we have\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m|million)?)\s*(?:shares|units)",
    r"we hold\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m|million)?)(?![a-z])",
    r"our books show\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m|million)?)(?![a-z])",
    r"we expect\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m|million)?)(?![a-z])",
]


def _empty(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def clean_body(body):
    """Drop forwarded-message headers, signature disclaimers."""
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if re.match(r"^-+\s*forwarded message\s*-+$", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|subject|cc):", s, re.I):
            continue
        if "confidential and intended solely" in s.lower():
            continue
        lines.append(ln)
    return "\n".join(lines)


def parse_qty(s):
    s = s.strip().lower().replace(" ", "")
    mult = 1
    for suf, m in (("million", 10 ** 6), ("mm", 10 ** 6), ("k", 10 ** 3), ("m", 10 ** 6)):
        if s.endswith(suf):
            mult = m
            s = s[: -len(suf)]
            break
    s = s.replace(",", "").rstrip(".")
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def client_figure(text):
    """(quantity, rounding tolerance) of the figure the client quotes, or None."""
    t = text.lower()
    for p in FIGURE_PATTERNS:
        m = re.search(p, t)
        if m:
            raw = m.group(1).replace(" ", "")
            q = parse_qty(raw)
            if q is None:
                continue
            tol = 0
            sm = re.match(r"^[\d,]*(?:\.(\d+))?(k|mm|million|m)$", raw)
            if sm:  # abbreviated figure: allow for the rounding implied by its precision
                mult = 10 ** 3 if sm.group(2) == "k" else 10 ** 6
                tol = mult / (10 ** len(sm.group(1) or "")) / 2
            return q, tol
    return None


def _yr(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _last_of_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Return (date|None, found: bool, ambiguous: bool)."""
    t = text.lower()
    # ISO
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), True
    # numeric M/D/Y
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if a > 12 and b <= 12:
            a, b = b, a  # clearly D/M/Y
        return _mk(y, a, b), True
    # 27-Jan-2026 / 27 Jan 2026 / Thu 25 Dec 2025 / 5 January 2026
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+" + MON_RE + r"[a-z]*\.?[\s\-/,]+(\d{4}|\d{2})\b", t)
    if m:
        return _mk(_yr(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1))), True
    # January 8, 2026 / Jan 8 2026
    m = re.search(r"\b" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}|\d{2})\b", t)
    if m:
        return _mk(_yr(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2))), True
    # end of January 2026 / January 2026 month-end
    m = re.search(r"\bend of\s+" + MON_RE + r"[a-z]*,?\s+(\d{4})\b", t) or \
        re.search(r"\b" + MON_RE + r"[a-z]*,?\s+(\d{4})\s+month[- ]?end\b", t)
    if m:
        y, mo = int(m.group(2)), MONTHS[m.group(1)[:3]]
        return _mk(y, mo, calendar.monthrange(y, mo)[1]), True
    # relative expressions
    if re.search(r"\byesterday\b", t):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b|\bas of now\b|\bcurrent(?:ly)?\b", t):
        return sent, True
    if re.search(r"(end of (?:the )?last month|last day of (?:the )?(?:last|previous|prior) month|"
                 r"end of (?:the )?(?:previous|prior) month|month[- ]end|end of month|last month[- ]end|"
                 r"prior month[- ]end|previous month[- ]end)", t):
        return _last_of_prev_month(sent), True
    if re.search(r"(year[- ]end|end of (?:last )?year)", t):
        return dt.date(sent.year - 1, 12, 31), True
    return None, False


def resolve_account(text, tools):
    if not text or not text.strip():
        return None, "missing"
    hits = tools.search_accounts(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], None
    if not hits:
        return None, "notfound"
    return None, "ambiguous"


def resolve_instrument(text, tools):
    if not text or not text.strip():
        return None, "missing"
    hits = tools.search_instruments(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], None
    return None, ("notfound" if not hits else "ambiguous")


def authorized(sender, account_id, sent, tools):
    sender = (sender or "").strip().lower()
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    prof = tools.get_client_profile(account_id) or {}
    if domain not in [d.lower() for d in prof.get("domains", [])]:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= 2 and e["expires"] >= sent.isoformat():
            return True
    return False


def business_day_on_or_before(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def settled_position(account_id, instrument_id, as_of, tools):
    a = as_of.isoformat()
    total = 0
    splits = [c for c in tools.get_corporate_actions(instrument_id) if c.get("type") == "split"]
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > a:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= a:
                q *= s["ratio"]
        total += q
    return total


def pending_settlement(account_id, instrument_id, as_of, tools):
    a = as_of.isoformat()
    pend = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > a]
    if not pend:
        return None, None
    return sum(x["qty"] for x in pend), max(x["settle_date"] for x in pend)


def figures_agree(figure, ours):
    """The client's figure is compared with the desk's total (settled + matched pending)."""
    q, tol = figure
    return abs(q - ours) <= max(tol, 0.005 * max(abs(ours), 1))


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    body = clean_body(request.get("body") or "")
    m = request.get("mentions") or {}

    acc, aerr = resolve_account(m.get("account_text"), tools)
    ins, ierr = resolve_instrument(m.get("instrument_text"), tools)
    if aerr or ierr:
        return _empty("REQUEST_INFO")

    if not authorized(request.get("from"), acc, sent, tools):
        return _empty("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(acc) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _empty("ESCALATE", account_id=acc, instrument_id=ins)

    req_date, found = parse_date(body, sent)
    assumed = False
    if found and req_date is None:
        return _empty("REQUEST_INFO")  # a date was given but is not a valid calendar date
    if not found:
        req_date = sent  # no date given: latest position, flagged as assumed
        assumed = True
    if req_date > sent:
        return _empty("REQUEST_INFO")
    as_of = business_day_on_or_before(req_date, tools)

    settled = settled_position(acc, ins, as_of, tools)
    if settled <= 0:
        # nothing held as of that date: NOT_HELD even if the client quotes a figure
        return _empty("NOT_HELD", account_id=acc, instrument_id=ins,
                      as_of=as_of.isoformat(), as_of_assumed=assumed)

    pq, pd = pending_settlement(acc, ins, as_of, tools)
    figure = client_figure(body)
    if figure is not None:
        raw = sum(t["qty"] for t in tools.get_ledger(acc, ins) if t["date"] <= as_of.isoformat())
        candidates = {settled + (pq or 0), raw + (pq or 0)}  # client may quote the pre-split count
        if not any(figures_agree(figure, c) for c in candidates):
            return _empty("ESCALATE", account_id=acc, instrument_id=ins)

    return _empty("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of.isoformat(),
                  as_of_assumed=assumed, settled=settled, pending=pq, pending_date=pd)
