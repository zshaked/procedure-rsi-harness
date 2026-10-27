"""Holding-confirmation desk procedure (induced). Standard library only; state via `tools`."""
import calendar
import datetime as dt
import re

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9

MIN_LEVEL = 2


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_body(body):
    # drop forwarded-message headers and disclaimers so their dates are not read as position dates
    body = re.sub(r"-{2,}\s*Forwarded message\s*-{2,}.*?\n\s*\n", "\n", body, flags=re.S | re.I)
    body = re.sub(r"^(From|Date|Sent|To|Subject):.*$", "", body, flags=re.M)
    body = re.sub(r"This email and any attachments.*", "", body, flags=re.S | re.I)
    return body


def _last_day_prev_month(d):
    first = d.replace(day=1)
    return first - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date, explicit) or (None, None)."""
    s = sent
    b = body
    low = b.lower()
    # relative expressions
    if re.search(r"\b(month[- ]end|end of (the )?(last|previous|prior) month|last (business |calendar )?day of (the )?(last|previous|prior) month|end of month|previous month[- ]end|last month[- ]end)\b", low):
        return _last_day_prev_month(s), False
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), False
    if re.search(r"\btoday\b", low):
        return s, False
    # ISO
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), True
        except ValueError:
            pass
    # M/D/YYYY
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", b)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return dt.date(y, int(m.group(1)), int(m.group(2))), True
        except ValueError:
            pass
    # 27-Jan-2026 / 27 Jan 2026 / 27 January 2026
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})\.?[\s-]+(\d{4})\b", b)
    if m and m.group(2).lower() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))), True
        except ValueError:
            pass
    # January 27, 2026
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b)
    if m and m.group(1).lower() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))), True
        except ValueError:
            pass
    return None, None


def parse_figure(body):
    num = r"(-?\d[\d,]*(?:\.\d+)?(?:mm|k|m)?)(?![a-z0-9])"
    pats = [r"records show\s+" + num, r"figure is\s+" + num,
            r"we have\s+" + num + r"\s+(?:shares|units)", r"we show\s+" + num,
            r"we hold\s+" + num, r"our books show\s+" + num]
    low = body.lower()
    for p in pats:
        m = re.search(p, low)
        if m:
            return parse_qty(m.group(1))
    return None


def parse_qty(t):
    t = t.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    if t.endswith("mm"):
        mult, t = 1_000_000, t[:-2]
    elif t.endswith("k"):
        mult, t = 1_000, t[:-1]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    t = t.rstrip(".")
    try:
        return int(round(float(t) * mult))
    except ValueError:
        return None


def business_as_of(d, tools):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d.isoformat()
    return c["previous_business_day"]


def settled_qty(account_id, instrument_id, as_of, tools):
    splits = [ca for ca in tools.get_corporate_actions(instrument_id) if ca.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for sp in splits:
            if t["date"] < sp["date"] <= as_of:
                q *= sp["ratio"]
        total += q
    return total


def pending_qty(account_id, instrument_id, as_of, tools):
    ins = [x for x in tools.get_instructions(account_id, instrument_id)
           if x["status"] == "matched" and x["settle_date"] > as_of]
    if not ins:
        return None, None
    return sum(x["qty"] for x in ins), max(x["settle_date"] for x in ins)


TOLERANCE = 0.10


def _close(fig, settled, pend):
    for ref in {settled, settled + (pend or 0)}:
        if ref == 0:
            if fig == 0:
                return True
            continue
        if abs(fig - ref) <= TOLERANCE * abs(ref):
            return True
    return False


def authorized(sender, account_id, sent, tools):
    domain = sender.split("@")[-1].lower()
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


def known_domain(sender, tools):
    """Is the sender's domain a registered domain of some client? (freemail etc. is not)."""
    return sender.split("@")[-1].lower() in _all_domains(tools)


_DOM_CACHE = {}


def _all_domains(tools):
    if "d" not in _DOM_CACHE:
        doms = set()
        # enumerate accounts: name-prefix search over every leading character ...
        for ch in "abcdefghijklmnopqrstuvwxyz0123456789":
            for a in tools.search_accounts(ch):
                p = tools.get_client_profile(a["id"]) or {}
                doms.update(d.lower() for d in p.get("domains", []))
        # ... plus the id range via get_account
        i = 10000
        miss = 0
        while miss < 50:
            a = tools.get_account("ACC-%d" % i)
            if a:
                miss = 0
                p = tools.get_client_profile(a["id"]) or {}
                doms.update(d.lower() for d in p.get("domains", []))
            else:
                miss += 1
            i += 1
        _DOM_CACHE["d"] = doms
    return _DOM_CACHE["d"]


def respond(request, tools):
    sender = request.get("from", "") or ""
    sent = dt.date.fromisoformat(request["sent"])
    body = _clean_body(request.get("body", "") or "")
    ment = request.get("mentions") or {}
    acc_text = ment.get("account_text")
    ins_text = ment.get("instrument_text")

    # 0. senders from unregistered domains (freemail etc.) need client authorization
    if not known_domain(sender, tools):
        return _blank("REQUEST_AUTHORIZATION")

    # 1. resolve account
    accs = tools.search_accounts(acc_text) if acc_text else []
    if len(accs) != 1:
        return _blank("REQUEST_INFO")
    account_id = accs[0]["id"]

    # 2. authorization
    if not authorized(sender, account_id, sent, tools):
        return _blank("REQUEST_AUTHORIZATION")

    # 3. instrument and date
    ins = tools.search_instruments(ins_text) if ins_text else []
    if len(ins) != 1:
        return _blank("REQUEST_INFO")
    instrument_id = ins[0]["id"]
    d, explicit = parse_date(body, sent)
    if d is None:
        return _blank("REQUEST_INFO")
    if d > sent:
        return _blank("REQUEST_INFO")

    prof = tools.get_client_profile(account_id) or {}
    if prof.get("legal_hold"):
        return _blank("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    as_of = business_as_of(d, tools)
    assumed = False
    settled = settled_qty(account_id, instrument_id, as_of, tools)

    pend, pdate = pending_qty(account_id, instrument_id, as_of, tools)

    # client's own figure must agree (within tolerance) with settled, or settled + pending
    fig = parse_figure(body)
    if fig is not None and not _close(fig, settled, pend):
        return _blank("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    if settled == 0:
        return _blank("NOT_HELD", account_id=account_id, instrument_id=instrument_id,
                      as_of=as_of, as_of_assumed=assumed)
    return _blank("CONFIRMED", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
                  as_of_assumed=assumed, settled=settled, pending=pend, pending_date=pdate)
