"""Induced procedure for the position-confirmation desk."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

REQUIRED_LEVEL = 3
LARGE_POSITION = 1_000_000


def _clean_body(body):
    body = re.sub(r"This email and any attachments.*", "", body, flags=re.S)
    body = re.sub(r"-+ Forwarded message -+\s*\nFrom:.*\nDate:.*\n", "", body)
    return body


def _month(tok):
    return MONTHS.get(tok[:3].lower())


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _last_day_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date or None, found_text: bool). found_text True with date None = unparseable."""
    b = _clean_body(body)
    low = b.lower()
    if re.search(r"end of last month|last day of last month|month[- ]end|end of (the )?month", low):
        return _last_day_prev_month(sent), True
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b", low):
        return sent, True
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))), True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:  # US style M/D/YYYY; fall back to D/M/YYYY when M/D is impossible
        a, b2, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (_safe_date(y, a, b2) or _safe_date(y, b2, a)), True
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]+(\d{4})\b", b)
    if m and _month(m.group(2)):
        return _safe_date(int(m.group(3)), _month(m.group(2)), int(m.group(1))), True
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", b)
    if m and _month(m.group(1)):
        return _safe_date(int(m.group(3)), _month(m.group(1)), int(m.group(2))), True
    if re.search(r"\b(as of|as at|position date)\b", low):
        return None, True
    return None, False


def parse_qty_token(s):
    s = s.strip().lower().replace(",", "")
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


def parse_client_qty(body):
    b = _clean_body(body)
    m = re.search(r"(?:figure is|records show|we have|we show|our books show|we hold)\s+"
                  r"(\d[\d,]*(?:\.\d+)?\s*(?:mm|k|m)?)\b", b, flags=re.I)
    if not m:
        return None
    return parse_qty_token(m.group(1).replace(" ", ""))


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def resolve_account(text, tools):
    if not text:
        return None
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def resolve_instrument(text, tools):
    if not text:
        return None
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def infer_account_from_sender(sender, tools):
    """No account named ("our fund"): use the sender's account if they are linked to exactly one."""
    c = tools.get_contact(sender)
    if not c:
        return None
    accts = sorted({e["account_id"] for e in tools.get_entitlements(c["contact_id"])})
    return accts[0] if len(accts) == 1 else None


def authorized(sender, account_id, sent, tools):
    c = tools.get_contact(sender)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= REQUIRED_LEVEL and e["expires"] >= sent:
            return True
    return False


def settled_qty(account_id, instrument_id, as_of, tools):
    splits = tools.get_corporate_actions(instrument_id)
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["type"] == "split" and t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        total += q
    return total


def pending_info(account_id, instrument_id, as_of, tools):
    """Matched (not cancelled / unmatched) instructions settling after the as-of date."""
    rows = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    if not rows:
        return None, None
    return sum(x["qty"] for x in rows), max(x["settle_date"] for x in rows)


def respond(request, tools):
    sender = (request.get("from") or "").strip().lower()
    sent = request["sent"]
    sent_d = dt.date.fromisoformat(sent)
    body = request.get("body") or ""
    mentions = request.get("mentions") or {}

    account_text = mentions.get("account_text")
    if account_text:
        account_id = resolve_account(account_text, tools)
    else:
        account_id = infer_account_from_sender(sender, tools)
    if account_id is None:
        return _resp("REQUEST_INFO")

    if not authorized(sender, account_id, sent, tools):
        return _resp("REQUEST_AUTHORIZATION")

    profile = tools.get_client_profile(account_id) or {}

    instrument_id = resolve_instrument(mentions.get("instrument_text"), tools)
    if instrument_id is None:
        return _resp("REQUEST_INFO")

    date, found = parse_date(body, sent_d)
    if found and date is None:
        return _resp("REQUEST_INFO")
    assumed = date is None
    if assumed:
        date = sent_d
    if date > sent_d:
        return _resp("REQUEST_INFO")
    as_of = date.isoformat()
    if not tools.get_calendar(as_of)["business_day"]:
        # Oracle: a non-business date is not rolled; the desk asks which date they want.
        return _resp("REQUEST_INFO")

    if profile.get("legal_hold"):
        return _resp("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    if profile.get("no_email_confirm"):
        return _resp("REQUEST_AUTHORIZATION")

    settled = settled_qty(account_id, instrument_id, as_of, tools)
    if settled <= 0:
        # Oracle: nothing held -> NOT_HELD, even if the client quoted a figure.
        return _resp("NOT_HELD", account_id=account_id, instrument_id=instrument_id,
                     as_of=as_of, as_of_assumed=assumed)
    client_qty = parse_client_qty(body)
    if client_qty is not None and client_qty != settled:
        return _resp("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    if settled >= LARGE_POSITION:
        # Oracle: positions that size always go to escalation before we confirm.
        return _resp("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    pend, pdate = pending_info(account_id, instrument_id, as_of, tools)
    return _resp("CONFIRMED", account_id=account_id, instrument_id=instrument_id, as_of=as_of,
                 as_of_assumed=assumed, settled=settled, pending=pend, pending_date=pdate)
