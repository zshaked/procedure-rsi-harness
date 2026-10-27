"""Induced procedure for the holding-confirmation desk. Deterministic, stdlib only."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_body(body):
    # drop forwarded-message header lines (they carry the sending date, not the position date)
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|To|Sent|Subject|Cc):", s, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _month(tok):
    return MONTHS.get(tok[:3].lower())


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _infer_year(m, d, sent):
    c = _mk(sent.year, m, d)
    if c and c > sent:
        c = _mk(sent.year - 1, m, d)
    return c


def _last_day_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Return (date or None, found_text: bool)."""
    t = text
    low = t.lower()
    M = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    cands = []
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        cands.append((m.start(), _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        d = _mk(y, a, b) if a <= 12 else _mk(y, b, a)
        cands.append((m.start(), d))
    for m in re.finditer(r"\b(\d{1,2})[- ]" + M + r"[- ,]+(\d{4})\b", t, re.I):
        cands.append((m.start(), _mk(int(m.group(3)), _month(m.group(2)), int(m.group(1)))))
    for m in re.finditer(r"\b" + M + r"\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t, re.I):
        cands.append((m.start(), _mk(int(m.group(3)), _month(m.group(1)), int(m.group(2)))))
    if not cands:
        for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)? " + M + r"\b", t, re.I):
            cands.append((m.start(), _infer_year(_month(m.group(2)), int(m.group(1)), sent)))
        for m in re.finditer(r"\b" + M + r"\.? (\d{1,2})(?:st|nd|rd|th)?\b", t, re.I):
            cands.append((m.start(), _infer_year(_month(m.group(1)), int(m.group(2)), sent)))
    rel = []
    for pat, fn in [
        (r"\b(end of last month|last day of (the )?(last|previous|prior) month|last month[- ]end|"
         r"(previous|prior) month[- ]end|month[- ]end|end of (the )?(previous|prior) month)\b",
         lambda: _last_day_prev_month(sent)),
        (r"\byesterday\b", lambda: sent - dt.timedelta(days=1)),
        (r"\btoday\b", lambda: sent),
        (r"\b(last|previous|prior) business day\b", lambda: sent - dt.timedelta(days=1)),
        (r"\b(end of last year|year[- ]end|last year[- ]end)\b", lambda: dt.date(sent.year - 1, 12, 31)),
    ]:
        m = re.search(pat, low)
        if m:
            rel.append((m.start(), fn()))
    m = re.search(r"\blast (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
    if m:
        wd = WEEKDAYS.index(m.group(1))
        back = (sent.weekday() - wd) % 7 or 7
        rel.append((m.start(), sent - dt.timedelta(days=back)))
    allc = sorted(cands + rel, key=lambda x: x[0])
    if not allc:
        return None, False
    return allc[0][1], True


def parse_qty(s):
    s = s.strip().lower().replace(",", "")
    mult = 1
    for suf, k in (("mm", 1_000_000), ("mn", 1_000_000), ("m", 1_000_000), ("k", 1_000), ("bn", 10**9)):
        if s.endswith(suf):
            mult = k
            s = s[: -len(suf)].strip()
            break
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


NUM = r"(\d[\d,]*(?:\.\d+)?\s*(?:mm|mn|bn|k|m)?)\b"


def stated_figure(text):
    pats = [
        r"(?:figure is|we show|we have|records show|our records show|books show|we hold|holding of|balance of|position of|we record|reflects?)\s*(?:a (?:holding|position|balance) of\s*)?" + NUM,
        NUM + r"\s*(?:shares|units|sh)\b",
    ]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            q = parse_qty(m.group(1))
            if q is not None:
                return q
    return None


def _roll_business(tools, d):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"][:10])
    mentions = request.get("mentions") or {}
    acct_text = (mentions.get("account_text") or "").strip()
    inst_text = (mentions.get("instrument_text") or "").strip()
    body = _clean_body(request.get("body", ""))

    # 1. Identify account and instrument unambiguously, else ask for clarification.
    if not acct_text or not inst_text:
        return _out("REQUEST_INFO")
    accs = tools.search_accounts(acct_text)
    insts = tools.search_instruments(inst_text)
    if len(accs) != 1 or len(insts) != 1:
        return _out("REQUEST_INFO")
    acct = accs[0]["id"]
    inst = insts[0]["id"]

    # 2. Date: parse; future dates cannot be confirmed -> clarify.
    d, found = parse_date(body, sent)
    if found and d is None:
        return _out("REQUEST_INFO")
    assumed = False
    if d is None:
        d = sent - dt.timedelta(days=1)
        assumed = True
    if d > sent:
        return _out("REQUEST_INFO")

    # 3. Authorization: sender must be a known contact on a client domain with a live
    #    entitlement of level >= 2 to this account.
    sender = (request.get("from") or "").strip().lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    profile = tools.get_client_profile(acct) or {}
    domains = [x.lower() for x in profile.get("domains", [])]
    contact = tools.get_contact(sender)
    ok = False
    if contact and domain in domains:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acct and e["level"] >= 2 and e["expires"] >= sent.isoformat():
                ok = True
    if not ok:
        return _out("REQUEST_AUTHORIZATION")

    # 4. Client restrictions -> review.
    if profile.get("legal_hold") or profile.get("no_email_confirm"):
        return _out("ESCALATE", account_id=acct, instrument_id=inst)

    # 5. Settled position across all sub-accounts, split-adjusted, at the business-day as-of.
    as_of = _roll_business(tools, d)
    iso = as_of.isoformat()
    splits = [c for c in tools.get_corporate_actions(inst) if c.get("type") == "split"]
    settled = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= iso:
                q = q * s["ratio"]
        settled += q

    if settled <= 0:
        return _out("NOT_HELD", account_id=acct, instrument_id=inst, as_of=iso,
                    as_of_assumed=assumed, settled=0)
    # 6. Client's own figure disagrees with ours -> review (no partial confirmation).
    stated = stated_figure(body)
    if stated is not None and stated != settled:
        return _out("ESCALATE", account_id=acct, instrument_id=inst)

    pend = [x for x in tools.get_instructions(acct, inst)
            if x["status"] == "matched" and x["settle_date"] > iso]
    pending = sum(x["qty"] for x in pend) if pend else None
    pending_date = max(x["settle_date"] for x in pend) if pend else None
    return _out("CONFIRMED", account_id=acct, instrument_id=inst, as_of=iso,
                as_of_assumed=assumed, settled=settled, pending=pending, pending_date=pending_date)
