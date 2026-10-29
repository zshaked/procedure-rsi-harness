import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

# ---- conventions (tunable) ----
TOL = 0.10            # relative tolerance between client figure and our figure
MIN_LEVEL = 2


def _d(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _clean_body(body):
    lines = []
    for ln in body.split("\n"):
        s = ln.strip()
        if re.match(r"^(from|date|sent|to|subject|cc):", s, re.I):
            continue
        if s.startswith("---"):
            continue
        if "confidential and intended solely" in s:
            continue
        lines.append(ln)
    return "\n".join(lines)


def parse_date(body, sent):
    """Return (date or None, kind). kind in explicit|relative|none."""
    t = _clean_body(body)
    sent_d = dt.date.fromisoformat(sent)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _d(*m.groups()), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _d(m.group(3), m.group(1), m.group(2)), "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]" + MON + r"[- ,]*(\d{4})\b", t, re.I)
    if m:
        return _d(m.group(3), MONTHS[m.group(2).lower()[:3]], m.group(1)), "explicit"
    m = re.search(r"\b" + MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        return _d(m.group(3), MONTHS[m.group(1).lower()[:3]], m.group(2)), "explicit"
    if re.search(r"\byesterday\b", t, re.I):
        return sent_d - dt.timedelta(days=1), "relative"
    if re.search(r"month-end|end of last month|last day of (the )?(last|previous) month|end of (the )?(last|previous) month", t, re.I):
        first = sent_d.replace(day=1)
        return first - dt.timedelta(days=1), "relative"
    return None, "none"


def parse_qty(s):
    s = s.replace(",", "").strip()
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*(k|mm|m)?$", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    u = (m.group(2) or "").lower()
    if u == "k":
        v *= 1e3
    elif u in ("mm", "m"):
        v *= 1e6
    return int(round(v))


def parse_claim(body):
    t = _clean_body(body)
    p = r"(?:our records show|we have|we show|figure is)\s+(-?\d[\d,]*(?:\.\d+)?\s*(?:mm|k|m)?)(?![a-z])"
    m = re.search(p, t, re.I)
    if m:
        return parse_qty(m.group(1))
    return None


def resolve_account(text, tools):
    if not text:
        return []
    return tools.search_accounts(text)


def resolve_instrument(text, tools):
    if not text:
        return []
    return tools.search_instruments(text)


def position(tools, acct, inst, as_of):
    ledger = tools.get_ledger(acct, inst)
    splits = tools.get_corporate_actions(inst)
    tot = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if as_of >= s["date"] and t["date"] < s["date"]:
                q *= s["ratio"]
        tot += q
    return tot


def pending_info(tools, acct, inst, as_of):
    ins = [x for x in tools.get_instructions(acct, inst)
           if x["status"] == "matched" and x["settle_date"] > as_of]
    if not ins:
        return None, None
    return sum(x["qty"] for x in ins), max(x["settle_date"] for x in ins)


def _resp(outcome, acct=None, inst=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acct, "instrument_id": inst, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


def _entitled(tools, contact, acct):
    if not contact:
        return []
    return [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == acct]


def decide(request, tools):
    m = request["mentions"]
    body = request["body"]
    sent = request["sent"]
    sender = request["from"]
    contact = tools.get_contact(sender)
    dom = sender.split("@")[-1].lower()

    accs = resolve_account(m.get("account_text"), tools)

    def known_for(aid):
        pr = tools.get_client_profile(aid) or {"domains": []}
        return any(e["expires"] >= sent for e in _entitled(tools, contact, aid)) and \
            dom in [d.lower() for d in pr["domains"]]

    if len(accs) != 1:
        if len(accs) > 1:
            cands = [a["id"] for a in accs]
            name = "account_ambiguous"
        else:
            cands = [e["account_id"] for e in tools.get_entitlements(contact["contact_id"])] if contact else []
            name = "account_missing"
        if any(known_for(c) for c in cands):
            return _resp("REQUEST_INFO"), name
        return _resp("REQUEST_AUTHORIZATION"), name + "_unauth"
    acct = accs[0]["id"]

    # authorization
    prof = tools.get_client_profile(acct) or {"domains": [], "legal_hold": False, "no_email_confirm": False}
    ents = _entitled(tools, contact, acct)
    if not contact:
        return _resp("REQUEST_AUTHORIZATION"), "auth_unknown_contact"
    if not ents:
        return _resp("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    live = [e for e in ents if e["expires"] >= sent]
    if not live:
        return _resp("REQUEST_AUTHORIZATION"), "auth_expired"
    if not any(e["level"] >= MIN_LEVEL for e in live):
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"
    if dom not in [d.lower() for d in prof["domains"]]:
        return _resp("REQUEST_AUTHORIZATION"), "auth_domain"

    ins = resolve_instrument(m.get("instrument_text"), tools)
    d, kind = parse_date(body, sent)
    inst = ins[0]["id"] if len(ins) == 1 else None

    def compute():
        if inst is None or d is None or d > dt.date.fromisoformat(sent):
            return None, None
        cal = tools.get_calendar(d.isoformat())
        as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]
        return as_of, position(tools, acct, inst, as_of)

    if prof.get("legal_hold"):
        as_of, settled = compute()
        return _resp("ESCALATE", acct, inst, as_of, False, settled), "legal_hold"

    if inst is None:
        return _resp("REQUEST_INFO", acct), "instrument_missing"
    if d is None:
        return _resp("REQUEST_INFO", acct, inst), "no_date"
    if d > dt.date.fromisoformat(sent):
        return _resp("REQUEST_INFO", acct, inst), "future_date"
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    settled = position(tools, acct, inst, as_of)
    pend, pdate = pending_info(tools, acct, inst, as_of)
    claim = parse_claim(body)
    total = settled + (pend or 0)

    if settled == 0 and not pend:
        return _resp("NOT_HELD", acct, inst, as_of, False), "not_held"

    if claim is not None and abs(claim - total) / max(abs(total), 1) > TOL:
        return _resp("ESCALATE", acct, inst, as_of, False, settled), "qty_mismatch"

    if settled == 0:
        return _resp("CONFIRMED", acct, inst, as_of, False, settled, pend, pdate), "settled_zero_pending"
    if pend:
        return _resp("CONFIRMED", acct, inst, as_of, False, settled, pend, pdate), "confirmed_pending"
    return _resp("CONFIRMED", acct, inst, as_of, False, settled), "confirmed"


def respond(request, tools):
    try:
        return decide(request, tools)[0]
    except Exception:
        return _resp("ESCALATE")
