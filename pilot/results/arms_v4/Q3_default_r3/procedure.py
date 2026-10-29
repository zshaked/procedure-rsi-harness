"""Operations-desk procedure: confirm a client's holding of a security.

Order of checks (induced from histories + oracle):
  1. account resolution (ambiguous / unknown -> REQUEST_INFO; "our fund" -> the sender's sole live entitlement)
  2. sender's best live entitlement level < 3 -> REQUEST_AUTHORIZATION
  3. instrument unknown/missing, requested date in the future or not a business day -> REQUEST_INFO
  4. sender has no level>=3 entitlement on this account -> REQUEST_AUTHORIZATION
  5. account flags: no_email_confirm -> REQUEST_AUTHORIZATION, legal_hold -> ESCALATE
  6. position = sum of ledger rows (all sub-accounts) up to and including as_of, split-adjusted for
     splits that took effect on/before as_of
  7. nothing held -> NOT_HELD; very large position or client figure off by >5% -> ESCALATE; else CONFIRMED
     (pending reported only for matched instructions settling within 30 days after the email)
"""
import re
import datetime as dt

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# ---- policy knobs -------------------------------------------------------------------------
MIN_LEVEL = 3
PENDING_WINDOW_DAYS = 30        # matched instructions settling within this many days after the email
TOLERANCE = 0.05                # client figure within this fraction of ours is accepted
SIZE_ESCALATE = 1000000         # positions this large are escalated before confirming


def _clean_body(body):
    out = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s.startswith("---------- Forwarded message"):
            continue
        if re.match(r"^(From|Date|Sent|To|Cc|Subject):", s):
            continue
        if s.startswith("This email and any attachments"):
            continue
        out.append(ln)
    return "\n".join(out)


def _mon(s):
    return _MONTHS[s[:3].lower()]


def _mk(y, m, d):
    try:
        y = int(y)
        if y < 100:
            y += 2000
        return dt.date(y, int(m), int(d))
    except ValueError:
        return None


def _prev_month_end(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _find_date(text, sent):
    """First date expression in the text (position order); None if there is none."""
    res = []
    taken = []

    def add(m, d):
        if d is None:
            return
        for (a, b) in taken:
            if m.start() < b and m.end() > a:
                return
        taken.append((m.start(), m.end()))
        res.append((m.start(), d))

    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        add(m, _mk(m.group(1), m.group(2), m.group(3)))
    for m in re.finditer(r"\b(\d{1,2})-" + _MON + r"-(\d{4})\b", text):
        add(m, _mk(m.group(3), _mon(m.group(2)), m.group(1)))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"\.?,?\s+(\d{4})\b", text):
        add(m, _mk(m.group(3), _mon(m.group(2)), m.group(1)))
    for m in re.finditer(r"\b" + _MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text):
        add(m, _mk(m.group(3), _mon(m.group(1)), m.group(2)))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", text):
        add(m, _mk(m.group(3), m.group(1), m.group(2)))
    # relative expressions
    for m in re.finditer(
            r"\b(?:the\s+)?(?:last\s+(?:calendar\s+)?day\s+of\s+(?:last|the\s+previous|the\s+prior)\s+month"
            r"|end\s+of\s+last\s+month|last\s+month[- ]end|end\s+of\s+the\s+(?:previous|prior)\s+month"
            r"|(?:previous|prior)\s+month[- ]end)\b", text, re.I):
        add(m, _prev_month_end(sent))
    for m in re.finditer(r"\b(?:the\s+)?(?:month[- ]end|end\s+of\s+(?:the\s+)?month|last\s+day\s+of\s+the\s+month)\b",
                         text, re.I):
        add(m, _prev_month_end(sent))
    for m in re.finditer(r"\byesterday\b", text, re.I):
        add(m, sent - dt.timedelta(days=1))
    for m in re.finditer(r"\btoday\b", text, re.I):
        add(m, sent)
    for m in re.finditer(r"\b(\d+|a|one|two|three|four|five)\s+(day|week)s?\s+ago\b", text, re.I):
        n = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}.get(m.group(1).lower())
        n = n if n is not None else int(m.group(1))
        add(m, sent - dt.timedelta(days=n * (7 if m.group(2).lower() == "week" else 1)))
    for m in re.finditer(r"\b(?:end\s+of\s+|close\s+of\s+business\s+)?last\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b",
                         text, re.I):
        target = _DOW[m.group(1).lower()[:3]]
        d = sent - dt.timedelta(days=1)
        while d.weekday() != target:
            d -= dt.timedelta(days=1)
        add(m, d)
    res.sort(key=lambda x: x[0])
    return res[0][1] if res else None


_QTY = re.compile(
    r"(?:we have|we show|we hold|our records show|our books show|our figure is|our figure|records show"
    r"|our position is)\s+(?:a position of\s+)?(-?\d[\d,]*(?:\.\d+)?)(?:[ ]?(k|mm|m|million|thousand)\b)?",
    re.I)


def _find_qty(text):
    q = _QTY.search(text)
    if not q:
        return None
    try:
        v = float(q.group(1).replace(",", ""))
    except ValueError:
        return None
    suf = (q.group(2) or "").lower()
    if suf in ("k", "thousand"):
        v *= 1e3
    elif suf in ("mm", "m", "million"):
        v *= 1e6
    return int(round(v))


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _resp("REQUEST_INFO")


def _respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    today = sent.isoformat()
    body = _clean_body(request["body"])
    men = request.get("mentions") or {}
    asof_req = _find_date(body, sent)
    stated = _find_qty(body)

    contact = tools.get_contact(request["from"])
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    live = [e for e in ents if e["expires"] >= today]

    # ---- 1. account
    at = men.get("account_text")
    if at:
        hits = tools.search_accounts(at)
        if len(hits) != 1:
            return _resp("REQUEST_INFO")
        acc = hits[0]["id"]
    else:
        ids = sorted(set(e["account_id"] for e in live))
        if len(ids) == 1:
            acc = ids[0]
        else:
            return _resp("REQUEST_INFO" if live else "REQUEST_AUTHORIZATION")

    # ---- 2. sender level
    if max([e["level"] for e in live], default=0) < MIN_LEVEL:
        return _resp("REQUEST_AUTHORIZATION")

    # ---- 3. instrument and date
    it = men.get("instrument_text")
    inst = None
    if it:
        hits = tools.search_instruments(it)
        if len(hits) == 1:
            inst = hits[0]["id"]
    if inst is None:
        return _resp("REQUEST_INFO")

    assumed = asof_req is None
    d = asof_req or sent
    if d > sent:
        return _resp("REQUEST_INFO")
    if not tools.get_calendar(d.isoformat())["business_day"]:
        return _resp("REQUEST_INFO")
    as_of = d.isoformat()

    # ---- 4. entitlement on this account
    if not any(e["account_id"] == acc and e["level"] >= MIN_LEVEL for e in live):
        return _resp("REQUEST_AUTHORIZATION")

    # ---- position
    splits = tools.get_corporate_actions(inst)
    settled = 0
    for t in tools.get_ledger(acc, inst):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if s["date"] <= as_of and t["date"] < s["date"]:
                    q *= s["ratio"]
            settled += q

    # ---- 5. account flags
    prof = tools.get_client_profile(acc) or {}
    if prof.get("no_email_confirm"):
        return _resp("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _resp("ESCALATE", account_id=acc, instrument_id=inst, as_of=as_of,
                     as_of_assumed=assumed, settled=settled)

    # ---- 7. outcome
    if settled == 0:
        return _resp("NOT_HELD", account_id=acc, instrument_id=inst, as_of=as_of, as_of_assumed=assumed)

    esc = _resp("ESCALATE", account_id=acc, instrument_id=inst, as_of=as_of,
                as_of_assumed=assumed, settled=settled)
    if settled < 0 or settled >= SIZE_ESCALATE:
        return esc

    matched = [x for x in tools.get_instructions(acc, inst)
               if x["status"] == "matched" and x["settle_date"] > as_of]
    if stated is not None:
        total = settled + sum(x["qty"] for x in matched)      # clients sometimes count matched trades as held
        dev = min(abs(stated - settled) / settled, abs(stated - total) / total if total else 9e9)
        if dev > TOLERANCE:
            return esc

    near = [x for x in matched
            if 0 <= (dt.date.fromisoformat(x["settle_date"]) - sent).days <= PENDING_WINDOW_DAYS]
    pend = pdate = None
    if near:
        pend = sum(x["qty"] for x in near)
        pdate = min(x["settle_date"] for x in near)
    return _resp("CONFIRMED", account_id=acc, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
                 settled=settled, pending=pend, pending_date=pdate)
