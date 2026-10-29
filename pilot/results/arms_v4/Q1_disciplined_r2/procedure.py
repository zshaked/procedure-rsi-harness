import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 3


def _parse_date(body, sent):
    """Return (kind, date|None). kind in 'none','date','bad'."""
    s = dt.date.fromisoformat(sent)
    b = body
    # drop forwarded header "Date: ..." line
    b = re.sub(r"(?m)^Date:.*$", "", b)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    if m:
        return "date", dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        return "date", dt.date(int(m[3]), int(m[1]), int(m[2]))
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", b)
    if m and m[2].lower() in MONTHS:
        return "date", dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", b)
    if m and m[2][:3].lower() in MONTHS:
        return "date", dt.date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))
    m = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", b)
    if m and m[1][:3].lower() in MONTHS:
        return "date", dt.date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2]))
    if re.search(r"\byesterday\b", b, re.I):
        return "date", s - dt.timedelta(days=1)
    if re.search(r"(last day of last month|end of last month|month-end|month end|end of the month)", b, re.I):
        first = s.replace(day=1)
        return "date", first - dt.timedelta(days=1)
    return "none", None


def _resolve_account(tools, text):
    if not text:
        return None, "missing"
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"], None
    return None, "ambiguous" if hits else "unknown"


def _resolve_instrument(tools, text):
    if not text:
        return None, "missing"
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"], None
    return None, "ambiguous" if hits else "unknown"


def _auth():
    return {"outcome": "REQUEST_AUTHORIZATION", "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _info(account=None, instrument=None):
    return {"outcome": "REQUEST_INFO", "account_id": account, "instrument_id": instrument, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def decide(request, tools):
    m = request.get("mentions", {})
    sent = request["sent"]
    email = request["from"]
    acc, aerr = _resolve_account(tools, m.get("account_text"))
    if acc is None:
        return _info(), "account_" + aerr
    c = tools.get_contact(email)
    if not c:
        return _auth(), "auth_no_contact"
    ents = [e for e in tools.get_entitlements(c["contact_id"]) if e["account_id"] == acc]
    if not ents:
        return _auth(), "auth_no_entitlement"
    if not any(e["level"] >= MIN_LEVEL for e in ents):
        return _auth(), "auth_level"
    if not any(e["level"] >= MIN_LEVEL and e["expires"] >= sent for e in ents):
        return _auth(), "auth_expired"
    prof = tools.get_client_profile(acc) or {}
    if email.lower().split("@")[-1] not in [d.lower() for d in prof.get("domains", [])]:
        return _auth(), "auth_domain"
    ins, ierr = _resolve_instrument(tools, m.get("instrument_text"))
    if ins is None:
        return _info(acc, None), "instrument_" + ierr
    kind, d = _parse_date(request["body"], sent)
    if kind == "none":
        return _info(acc, ins), "no_date"
    cal = tools.get_calendar(d.isoformat())
    if not cal["business_day"]:
        return _info(acc, ins), "nonbusiness_date"
    for flag, br in (("legal_hold", "escalate_legal_hold"), ("no_email_confirm", "escalate_no_email")):
        if prof.get(flag):
            r = _info(acc, ins)
            r["outcome"] = "ESCALATE"
            return r, br
    asof = d.isoformat()
    splits = tools.get_corporate_actions(ins)
    settled = 0
    split_used = False
    for t in tools.get_ledger(acc, ins):
        if t["date"] > asof:
            continue
        q = t["qty"]
        for sp in splits:
            if asof >= sp["date"] and t["date"] < sp["date"]:
                q *= sp["ratio"]
                split_used = True
        settled += q
    base = {"account_id": acc, "instrument_id": ins, "as_of": asof, "as_of_assumed": False}
    if settled == 0:
        base.update(outcome="NOT_HELD", settled=None, pending=None, pending_date=None)
        return base, "not_held"
    pend = [x for x in tools.get_instructions(acc, ins) if x["status"] == "matched" and x["settle_date"] > asof]
    pq = sum(x["qty"] for x in pend)
    base.update(outcome="CONFIRMED", settled=settled,
                pending=pq or None, pending_date=max((x["settle_date"] for x in pend), default=None))
    if split_used:
        return base, "confirmed_split"
    return base, "confirmed_pending" if pend else "confirmed"


def respond(request, tools):
    return decide(request, tools)[0]
