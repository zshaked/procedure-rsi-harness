import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
CLAIM_TOLERANCE = 0.05
PENDING_HORIZON_DAYS = 10  # matched instructions settling within this many days of the email date


def _clean(t):
    if t is None:
        return None
    t = t.strip().strip(".,;:()\"'").strip()
    return t or None


def _prev_bd(d, tools):
    return dt.date.fromisoformat(tools.get_calendar(d.isoformat())["previous_business_day"])


def _is_bd(d, tools):
    return tools.get_calendar(d.isoformat())["business_day"]


def _month_end_prev(sent):
    first = sent.replace(day=1)
    return first - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date|None, found_expression_bool)."""
    b = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    # skip the forwarded-header "Date: yyyy-mm-dd"
    for mm in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", b):
        pre = b[max(0, mm.start() - 6):mm.start()]
        if "Date:" in pre:
            continue
        try:
            return dt.date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3))), True
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", b)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))), True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))), True
        except ValueError:
            pass
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})\b", b)
    if m and m.group(1)[:3].lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2))), True
    m = re.search(r"\b(\d{1,2}) ([A-Za-z]{3,9}) (\d{4})\b", b)
    if m and m.group(2)[:3].lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1))), True
    low = b.lower()
    if re.search(r"end of last month|last day of last month|month-end|month end|end of the month|last day of the month", low):
        return _month_end_prev(sent), True
    if "yesterday" in low:
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b", low):
        return sent, True
    return None, False


def parse_qty(s):
    s = s.replace(",", "").strip().lower()
    mult = 1
    if s.endswith("mm"):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


CLAIM_PATTERNS = [
    r"we have\s+(-?[\d,\.]+\s*(?:k|mm|m)?)\s+shares",
    r"our records show\s+(-?[\d,\.]+\s*(?:k|mm|m)?)\s+units",
    r"our figure is\s+(-?[\d,\.]+\s*(?:k|mm|m)?)\b",
    r"we show\s+(-?[\d,\.]+\s*(?:k|mm|m)?)\b",
]


def parse_claim(body):
    low = body.lower()
    for p in CLAIM_PATTERNS:
        m = re.search(p, low)
        if m:
            s = m.group(1).strip().rstrip(".,")
            s = s.replace(" ", "")
            return parse_qty(s)
    return None


def resolve_account(text, tools):
    t = _clean(text)
    if not t:
        return None, "none"
    hits = tools.search_accounts(t)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if len(hits) == 0:
        return None, "none"
    return None, "ambiguous"


def resolve_instrument(text, tools):
    t = _clean(text)
    if not t:
        return None, "none"
    hits = tools.search_instruments(t)
    ids = sorted({h["id"] for h in hits})
    if len(ids) == 1:
        return ids[0], "ok"
    if not ids:
        return None, "none"
    return None, "ambiguous"


def position(tools, acct, inst, as_of):
    ledger = tools.get_ledger(acct, inst)
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q
    return total


def authorized(tools, email, acct, sent):
    c = tools.get_contact(email)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct and e["level"] >= 3 and e["expires"] >= sent:
            return True
    return False


def _r(outcome, **kw):
    d = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    d.update(kw)
    return d


def respond(request, tools):
    sent_s = request["sent"]
    sent = dt.date.fromisoformat(sent_s)
    men = request.get("mentions") or {}
    body = request["body"]

    acct, ast = resolve_account(men.get("account_text"), tools)
    if ast == "ambiguous" or ast == "none" and men.get("account_text"):
        return _r("REQUEST_INFO")
    if acct is None:
        return _r("REQUEST_INFO")

    if not authorized(tools, request["from"], acct, sent_s):
        return _r("REQUEST_AUTHORIZATION")

    inst, ist = resolve_instrument(men.get("instrument_text"), tools)
    if inst is None:
        return _r("REQUEST_INFO", account_id=acct)

    d, found = parse_date(body, sent)
    assumed = not found
    if d is None:
        d = sent
    if not _is_bd(d, tools) or d > sent:
        return _r("REQUEST_INFO", account_id=acct)
    as_of = d.isoformat()

    prof = tools.get_client_profile(acct) or {}
    settled = position(tools, acct, inst, as_of)
    claim = parse_claim(body)

    if prof.get("no_email_confirm"):
        return _r("REQUEST_AUTHORIZATION")

    if prof.get("legal_hold"):
        return _r("ESCALATE", account_id=acct, instrument_id=inst, as_of=as_of,
                  as_of_assumed=assumed, settled=settled)

    if claim is not None and abs(claim - settled) > CLAIM_TOLERANCE * abs(settled):
        return _r("ESCALATE", account_id=acct, instrument_id=inst, as_of=as_of,
                  as_of_assumed=assumed, settled=settled)

    if settled == 0:
        return _r("NOT_HELD", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed)

    pend = 0
    pdate = None
    for x in tools.get_instructions(acct, inst):
        if x["status"] != "matched":
            continue
        if x["settle_date"] <= as_of:
            continue
        gap = (dt.date.fromisoformat(x["settle_date"]) - sent).days
        if gap < 0 or gap > PENDING_HORIZON_DAYS:
            continue
        pend += x["qty"]
        if pdate is None or x["settle_date"] < pdate:
            pdate = x["settle_date"]
    return _r("CONFIRMED", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
              settled=settled, pending=pend or None, pending_date=pdate)
