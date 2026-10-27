"""Position-confirmation desk procedure (implements spec.md)."""
import re
import datetime as dt

LARGE = 1_000_000
TOLERANCE = 0.02
PENDING_WINDOW_DAYS = 90
HISTORY_START = "2025-12-15"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return "BAD"


def _last_of_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _clean_body(body):
    lines = []
    for ln in body.split("\n"):
        s = ln.strip()
        if re.match(r"^(from|date|sent|to|subject|cc)\s*:", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _parse_date(body, sent):
    """Return (date|'BAD'|None, found). Earliest-positioned candidate wins."""
    s = dt.date.fromisoformat(sent)
    b = body
    low = b.lower()
    c = []
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b):
        c.append((m.start(), _mk(int(m[1]), int(m[2]), int(m[3]))))
    for m in re.finditer(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b", b):
        a, bb, y = int(m[1]), int(m[2]), int(m[3])
        if y < 100:
            y += 2000
        if a > 12 >= bb:
            c.append((m.start(), _mk(y, bb, a)))
        else:
            c.append((m.start(), _mk(y, a, bb)))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ](?:of )?" + _MON_RE + r"\.?[-, ]+(\d{4})\b", low):
        c.append((m.start(), _mk(int(m[3]), _MONTHS[m[2][:3]], int(m[1]))))
    for m in re.finditer(r"\b" + _MON_RE + r"\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", low):
        c.append((m.start(), _mk(int(m[3]), _MONTHS[m[1][:3]], int(m[2]))))
    if not c:
        # dates without a year: "January 5", "5 Jan"
        for m in re.finditer(r"\b(?:as (?:of|at)|position date|close of business|cob)\s+(?:close of business\s+)?(?:(\d{1,2})(?:st|nd|rd|th)? " + _MON_RE + r"|" + _MON_RE + r" (\d{1,2})(?:st|nd|rd|th)?)\b", low):
            if m[1]:
                mo, d = _MONTHS[m[2][:3]], int(m[1])
            else:
                mo, d = _MONTHS[m[3][:3]], int(m[4])
            x = _mk(s.year, mo, d)
            if x != "BAD" and x > s:
                x = _mk(s.year - 1, mo, d)
            c.append((m.start(), x))
    rel = [
        (r"\b(?:end of|last day of)\s+(?:the\s+)?(?:last|previous|prior)\s+month\b|\bmonth[- ]end\b|\bprevious month[- ]end\b|\blast month[- ]end\b", lambda: _last_of_prev_month(s)),
        (r"\b(?:end of|last day of)\s+(?:the\s+)?(?:last|previous|prior)\s+year\b|\byear[- ]end\b", lambda: dt.date(s.year - 1, 12, 31)),
        (r"\b(?:end of|last day of)\s+(?:the\s+)?(?:last|previous|prior)\s+quarter\b|\bquarter[- ]end\b", lambda: s.replace(month=((s.month - 1) // 3) * 3 + 1, day=1) - dt.timedelta(days=1)),
        (r"\byesterday\b", lambda: s - dt.timedelta(days=1)),
        (r"\btoday\b|\bthis morning\b", lambda: s),
    ]
    for pat, fn in rel:
        m = re.search(pat, low)
        if m:
            c.append((m.start(), fn()))
    if not c:
        return None, False
    c.sort(key=lambda t: t[0])
    return c[0][1], True


_NUM = r"(-?\d[\d,]*(?:\.\d+)?)\s*(k|mm|m|mn|bn|million|thousand)?\b"


def _parse_qty(body):
    pats = [
        r"(?:figure is|figure of|records show|records reflect|we show|we have|books show|we hold|we see|our position is|position of|balance of|balance is|holding of)\s*(?:a\s+)?(?:position\s+of\s+|holding\s+of\s+|balance\s+of\s+)?" + _NUM,
        _NUM + r"\s*(?:shares|units)\b",
    ]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            g = [x for x in m.groups()]
            num, suf = g[0], (g[1] or "").lower()
            try:
                v = float(num.replace(",", ""))
            except ValueError:
                continue
            mult = {"k": 1e3, "thousand": 1e3, "mm": 1e6, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9}.get(suf, 1)
            return int(round(v * mult))
    return None


def _holding(tools, acc, ins, as_of):
    ledger = tools.get_ledger(acc, ins)
    cas = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    tot = 0
    for t in ledger:
        if t["date"] <= as_of:
            q = t["qty"]
            for c in cas:
                if t["date"] < c["date"] <= as_of:
                    q *= c["ratio"]
            tot += q
    return tot


def respond(request, tools):
    sent = request.get("sent")
    sender = (request.get("from") or "").strip()
    m = request.get("mentions") or {}
    body = _clean_body(request.get("body") or "")
    at = (m.get("account_text") or "").strip()
    it = (m.get("instrument_text") or "").strip()

    contact = tools.get_contact(sender) if sender else None
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # 1-4 account
    if at:
        hits = tools.search_accounts(at)
        if len(hits) != 1:
            return _out("REQUEST_INFO")
        acc = hits[0]["id"]
    else:
        ids = sorted({e["account_id"] for e in ents})
        if len(ids) == 1:
            acc = ids[0]
        elif not contact:
            return _out("REQUEST_AUTHORIZATION")
        else:
            return _out("REQUEST_INFO")

    # 5 authorization
    ok = any(e["account_id"] == acc and e["level"] >= 3 and e["expires"] >= sent for e in ents)
    if not ok:
        return _out("REQUEST_AUTHORIZATION")

    # 9 instrument
    if not it:
        return _out("REQUEST_INFO")
    ins_hits = tools.search_instruments(it)
    if len(ins_hits) != 1:
        return _out("REQUEST_INFO")
    ins = ins_hits[0]["id"]

    # 7, 8 profile flags
    prof = tools.get_client_profile(acc) or {}
    if prof.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _out("ESCALATE", account_id=acc, instrument_id=ins)

    # 10-12 date
    d, found = _parse_date(body, sent)
    assumed = False
    if not found:
        d, assumed = dt.date.fromisoformat(sent), True
    if d == "BAD":
        return _out("REQUEST_INFO")
    as_of = d.isoformat()
    if as_of > sent:
        return _out("REQUEST_INFO")
    if not tools.get_calendar(as_of)["business_day"]:
        return _out("REQUEST_INFO")
    if as_of < HISTORY_START:
        return _out("ESCALATE", account_id=acc, instrument_id=ins)

    # 13-15 figure
    settled = _holding(tools, acc, ins, as_of)
    if settled == 0:
        return _out("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed)
    if settled < 0 or settled >= LARGE:
        return _out("ESCALATE", account_id=acc, instrument_id=ins)
    claimed = _parse_qty(body)
    if claimed is not None and abs(claimed - settled) > TOLERANCE * abs(settled) + 1e-9:
        return _out("ESCALATE", account_id=acc, instrument_id=ins)

    # 16 pending
    lim = (d + dt.timedelta(days=PENDING_WINDOW_DAYS)).isoformat()
    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and as_of < x["settle_date"] <= lim]
    pq = sum(x["qty"] for x in pend) if pend else None
    pdate = max(x["settle_date"] for x in pend) if pend else None
    return _out("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed,
                settled=settled, pending=pq, pending_date=pdate)
