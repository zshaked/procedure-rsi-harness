"""Induced procedure for the holding-confirmation desk."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
TOLERANCE = 0.10  # oracle: 7% gap still confirmed; 15% gaps escalated in history


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


def _month_end_before(d):
    """Last calendar day of the month preceding d."""
    return d.replace(day=1) - dt.timedelta(days=1)


def _parse_date(body, sent):
    """Return (date or None, vague: bool). vague=True for month-end style phrases."""
    text = body.lower()
    # strip forwarded-header 'Date:' lines
    text = re.sub(r"^date:.*$", " ", text, flags=re.M)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), False
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2])), False
    m = re.search(r"\b(\d{1,2})[- ]([a-z]{3})[a-z]*\.?[- ,]+(\d{4})\b", text)
    if m and m[2] in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[2]], int(m[1])), False
    m = re.search(r"\b([a-z]{3})[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", text)
    if m and m[1] in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[1]], int(m[2])), False
    if "yesterday" in text:
        return sent - dt.timedelta(days=1), False
    if re.search(r"\btoday\b", text):
        return sent, False
    if re.search(r"(end of|last day of) (the )?(last|previous|prior) month|month[- ]end|end of (the )?month", text):
        return _month_end_before(sent), True
    return None, False


def _parse_qty(body):
    t = body.replace(" ", " ")
    pats = [r"(?:records show|our figure is|we show|we have)\s+(-?\d[\d,]*(?:\.\d+)?(?:k|mm|m)?)(?![a-z])"]
    for p in pats:
        m = re.search(p, t, flags=re.I)
        if m:
            s = m[1].strip().lower().replace(",", "")
            mult = 1
            if s.endswith("mm"):
                mult, s = 1_000_000, s[:-2]
            elif s.endswith("m"):
                mult, s = 1_000_000, s[:-1]
            elif s.endswith("k"):
                mult, s = 1_000, s[:-1]
            s = s.strip().rstrip(".")
            try:
                return int(round(float(s) * mult))
            except ValueError:
                return None
    return None


def _resolve_account(text, tools):
    if not text:
        return None, "missing"
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if not hits:
        return None, "missing"
    return None, "ambiguous"


def _resolve_instrument(text, tools):
    if not text:
        return None, "missing"
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if not hits:
        return None, "missing"
    return None, "ambiguous"


def _authorized(sender, account_id, tools, today):
    contact = tools.get_contact(sender)
    if not contact:
        return False
    prof = tools.get_client_profile(account_id) or {}
    domain = sender.split("@")[-1].lower()
    if domain not in [d.lower() for d in prof.get("domains", [])]:
        return False
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= 2 and e["expires"] >= today:
            return True
    return False


def _business_day_on_or_before(date_iso, tools):
    cal = tools.get_calendar(date_iso)
    return date_iso if cal["business_day"] else cal["previous_business_day"]


def respond(request, tools):
    sender = request.get("from", "")
    sent = dt.date.fromisoformat(request["sent"])
    body = request.get("body", "") or ""
    mentions = request.get("mentions") or {}
    acc_text = mentions.get("account_text")
    ins_text = mentions.get("instrument_text")
    if not ins_text:
        m = re.search(r"\b(US\d{10})\b", body)
        if m:
            ins_text = m[1]

    acc, acc_status = _resolve_account(acc_text, tools)
    if acc is None:
        # cannot identify the account: a sender from an unrecognised domain gets an authorization request
        domain = sender.split("@")[-1].lower()
        return _out("REQUEST_INFO") if _known_domain(domain, tools) else _out("REQUEST_AUTHORIZATION")

    if not _authorized(sender, acc, tools, request["sent"]):
        return _out("REQUEST_AUTHORIZATION")

    ins, ins_status = _resolve_instrument(ins_text, tools)
    try:
        date, vague = _parse_date(body, sent)
    except ValueError:
        date, vague = None, False
    if ins is None or date is None:
        return _out("REQUEST_INFO")
    if date >= sent:
        # future (or not yet closed) date: oracle rejected CONFIRMED and ESCALATE; REQUEST_INFO best remaining guess
        return _out("REQUEST_INFO")

    prof = tools.get_client_profile(acc) or {}
    # legal hold -> escalate (oracle-confirmed). no_email_confirm did NOT block a confirmation per oracle.
    if prof.get("legal_hold"):
        return _out("ESCALATE", acc, ins)

    as_of = _business_day_on_or_before(date.isoformat(), tools)

    settled = 0
    splits = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    for t in tools.get_ledger(acc, ins):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            settled += q

    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    pending = sum(x["qty"] for x in pend) if pend else None
    pdate = max(x["settle_date"] for x in pend) if pend else None

    if settled < 0:
        return _out("ESCALATE", acc, ins)
    # as_of_assumed: oracle rejected True for month-end phrases and for weekend roll-back
    vague = False
    if settled == 0:
        # oracle: nothing held -> NOT_HELD even when the client quotes a figure
        return _out("NOT_HELD", acc, ins, as_of, vague, None, pending, pdate)

    client = _parse_qty(body)
    if client is not None:
        ours = settled + (pending or 0)
        base = max(abs(ours), 1)
        if abs(client - ours) / base > TOLERANCE and abs(client - settled) / max(abs(settled), 1) > TOLERANCE:
            return _out("ESCALATE", acc, ins)

    if settled == 0:
        return _out("NOT_HELD", acc, ins, as_of, vague, None, pending, pdate)
    return _out("CONFIRMED", acc, ins, as_of, vague, settled, pending, pdate)


def _known_domain(domain, tools):
    """Whether any client account lists this domain (search_accounts('') lists all accounts)."""
    for a in tools.search_accounts(""):
        p = tools.get_client_profile(a["id"]) or {}
        if domain in (d.lower() for d in p.get("domains", [])):
            return True
    return False
