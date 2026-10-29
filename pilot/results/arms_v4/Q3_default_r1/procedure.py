"""Operations-desk procedure: confirm a client's holding of a security.

Gate order (recovered from histories + oracle):
  1 account ambiguous            -> REQUEST_INFO
  2 sender lacks a valid level>=3 entitlement on the named account (or no account named)
                                 -> REQUEST_AUTHORIZATION
  3 instrument missing/ambiguous -> REQUEST_INFO
  4 client bars e-mail confirmation (no_email_confirm) -> REQUEST_AUTHORIZATION
  5 as-of date not a business day / in the future      -> REQUEST_INFO
  6 legal hold                   -> ESCALATE
  7 nothing held at as-of        -> NOT_HELD   (even if the client quoted a figure)
  8 position >= 1,000,000, or client's figure off by more than 5% -> ESCALATE
  9 otherwise CONFIRMED (settled = ledger over all sub-accounts up to as-of, split-adjusted),
    with matched, not-yet-settled instructions reported as pending when material.
"""
import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

MIN_LEVEL = 3              # entitlement level required to receive confirmations
FIG_TOLERANCE = 0.05       # client's own figure within 5% of ours -> just confirm ours
SIZE_ESCALATE = 1_000_000  # positions this large always go to escalation
MIN_PENDING = 1000         # smaller matched instructions are not worth reporting as pending


def _date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def _parse_qty(tok):
    tok = tok.strip().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(k|mm|m)?", tok, re.I)
    if not m:
        return None
    v = float(m.group(1))
    suf = (m.group(2) or "").lower()
    if suf == "k":
        v *= 1e3
    elif suf in ("mm", "m"):
        v *= 1e6
    return int(round(v))


_NUM = r"(-?\d[\d,]*(?:\.\d+)?\s?(?:k|mm)?)(?![\w])"


def parse_figure(body):
    m = re.search(r"(?:we have|we show|our records show|our records indicate|our figure is|records show|"
                  r"we hold|our books show|our books have|we record|we see)\s+" + _NUM, body, re.I)
    if m:
        return _parse_qty(m.group(1))
    m = re.search(_NUM.replace("(?![\\w])", "") + r"\s+(?:shares|units)\b", body, re.I)
    if m:
        return _parse_qty(m.group(1))
    return None


def parse_date(body, sent):
    s = dt.date.fromisoformat(sent)
    t = re.sub(r"(?im)^\s*(?:date|sent)\s*:.*$", "", body)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _date(*m.groups()), "explicit"
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3,9})-(\d{4})\b", t)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _date(m.group(3), MONTHS[m.group(2)[:3].lower()], m.group(1)), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            return _date(m.group(3), b, a), "explicit"
        return _date(m.group(3), a, b), "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", t)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _date(m.group(3), MONTHS[m.group(2)[:3].lower()], m.group(1)), "explicit"
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        return _date(m.group(3), MONTHS[m.group(1)[:3].lower()], m.group(2)), "explicit"
    low = t.lower()
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"(end of last month|last day of last month|month-end|month end|end of the month|"
                 r"end of previous month|last day of the previous month)", low):
        return s.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", low):
        return s, "relative"
    return None, None


def _email(addr):
    m = re.search(r"[\w.+\-']+@[\w.\-]+", addr or "")
    return (m.group(0) if m else (addr or "")).lower()


def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _respond(request, tools):
    sent = request["sent"]
    body = request.get("body", "") or ""
    men = request.get("mentions") or {}
    sent_d = dt.date.fromisoformat(sent)

    # 1. account resolution (ambiguous -> ask)
    atext = (men.get("account_text") or "").strip()
    accts = tools.search_accounts(atext) if atext else []
    if len(accts) > 1:
        return _blank("REQUEST_INFO")
    acct = accts[0]["id"] if accts else None

    # 2. authorization: sender needs a live level>=3 entitlement on the named account
    contact = tools.get_contact(_email(request.get("from")))
    authorised = False
    if contact and acct:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acct and e["level"] >= MIN_LEVEL and e["expires"] >= sent:
                authorised = True
    if not authorised:
        return _blank("REQUEST_AUTHORIZATION")
    prof = tools.get_client_profile(acct) or {}

    # 3. instrument
    itext = (men.get("instrument_text") or "").strip()
    insts = tools.search_instruments(itext) if itext else []
    if len(insts) != 1:
        return _blank("REQUEST_INFO")
    inst = insts[0]["id"]

    # 4. client does not take confirmations by e-mail
    if prof.get("no_email_confirm"):
        return _blank("REQUEST_AUTHORIZATION")

    # 5. as-of date (missing -> date of the e-mail, flagged as assumed)
    d, _kind = parse_date(body, sent)
    assumed = False
    if d is None:
        d, assumed = sent_d, True
    if not tools.get_calendar(d.isoformat())["business_day"] or d > sent_d:
        return _blank("REQUEST_INFO")
    asof = d.isoformat()

    out = {"outcome": None, "account_id": acct, "instrument_id": inst, "as_of": asof,
           "as_of_assumed": assumed, "settled": None, "pending": None, "pending_date": None}

    # figure: all custody sub-accounts, entries up to as-of, split-adjusted
    splits = tools.get_corporate_actions(inst)
    settled = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > asof:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= asof:
                q *= s["ratio"]
        settled += q

    # 6. legal hold
    if prof.get("legal_hold"):
        out["outcome"] = "ESCALATE"
        out["settled"] = settled
        return out

    # 7. nothing held
    if settled == 0:
        out["outcome"] = "NOT_HELD"
        return out

    # 8. very large position, or client's figure disagrees materially -> escalate
    stated = parse_figure(body)
    if abs(settled) >= SIZE_ESCALATE or (
            stated is not None and abs(stated - settled) > FIG_TOLERANCE * abs(settled)):
        out["outcome"] = "ESCALATE"
        out["settled"] = settled
        return out

    # 9. confirm, with material matched-but-unsettled instructions as pending
    out["outcome"] = "CONFIRMED"
    out["settled"] = settled
    pend = [x for x in tools.get_instructions(acct, inst)
            if x["status"] == "matched" and x["settle_date"] > asof and x["qty"] >= MIN_PENDING]
    if pend:
        out["pending"] = sum(x["qty"] for x in pend)
        out["pending_date"] = min(x["settle_date"] for x in pend)
    return out


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _blank("REQUEST_INFO")
