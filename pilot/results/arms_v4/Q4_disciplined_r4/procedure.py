import re
import datetime as dt

FREEMAIL = {"gmail.com", "yahoo.com", "outlook.com", "proton.me", "hotmail.com", "icloud.com"}
TOL = 0.10          # relative mismatch tolerance (client figure vs desk figure)
MIN_LEVEL = 2
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _d(s):
    return dt.date.fromisoformat(s)


def _parse_qty(tok, suf):
    v = float(tok.replace(",", ""))
    s = (suf or "").lower()
    if s == "k":
        v *= 1e3
    elif s in ("m", "mm"):
        v *= 1e6
    return int(round(v))


def parse_client_figure(body):
    m = re.search(r"(?:records show|figure is|we show|we have|we hold|show)\s+(-?\d[\d,]*(?:\.\d+)?)\s*(mm|k|m)?(?![\w])", body, re.I)
    if m:
        return _parse_qty(m.group(1), m.group(2))
    return None


def parse_date(body, sent):
    """Returns (date or None, kind)."""
    s = _d(sent)
    t = re.sub(r"This email and any attachments.*", "", body, flags=re.S)
    t = re.sub(r"-+ Forwarded message -+.*?\n\n", "", t, count=1, flags=re.S) if "Forwarded message" in t else t
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "abs"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))), "abs"
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", t)
    if m:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))), "abs"
    m = re.search(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b", t)
    if m:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1))), "abs"
    m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b", t)
    if m:
        return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2))), "abs"
    low = t.lower()
    if "yesterday" in low:
        return s - dt.timedelta(days=1), "rel"
    if re.search(r"month-end|end of last month|last day of (?:the )?last month|end of (?:the )?month", low):
        first = s.replace(day=1)
        return first - dt.timedelta(days=1), "rel"
    return None, "none"


def decide(request, tools):
    body = request["body"]
    sent = request["sent"]
    men = request.get("mentions") or {}
    sender = request["from"].lower()
    dom = sender.split("@")[-1]
    out = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
           "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def done(outcome, branch, **kw):
        out["outcome"] = outcome
        out.update(kw)
        return out, branch

    contact = tools.get_contact(sender)
    accts = tools.search_accounts(men["account_text"]) if men.get("account_text") else None
    insts = tools.search_instruments(men["instrument_text"]) if men.get("instrument_text") else None
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    if not contact:
        return done("REQUEST_AUTHORIZATION", "no_contact")
    if accts is not None and len(accts) > 1:
        return done("REQUEST_INFO", "account_ambiguous")
    if accts is None or len(accts) == 0:
        ok = False
        for e in ents:
            p = tools.get_client_profile(e["account_id"])
            if p and dom in p["domains"]:
                ok = True
        if not ok:
            return done("REQUEST_AUTHORIZATION", "account_missing_unverified_sender")
        return done("REQUEST_INFO", "account_missing")
    acct = accts[0]["id"]
    prof = tools.get_client_profile(acct)
    mine = [e for e in ents if e["account_id"] == acct]
    if not mine:
        return done("REQUEST_AUTHORIZATION", "no_entitlement")
    valid = [e for e in mine if e["expires"] >= sent]
    if not valid:
        return done("REQUEST_AUTHORIZATION", "entitlement_expired")
    if max(e["level"] for e in valid) < MIN_LEVEL:
        return done("REQUEST_AUTHORIZATION", "level_low")
    if prof is None or dom not in prof["domains"]:
        return done("REQUEST_AUTHORIZATION", "domain_mismatch")
    iid = insts[0]["id"] if insts is not None and len(insts) == 1 else None
    if prof["legal_hold"]:
        return done("ESCALATE", "legal_hold", account_id=acct, instrument_id=iid)
    if insts is None or len(insts) == 0:
        return done("REQUEST_INFO", "instrument_missing", account_id=acct)
    if len(insts) > 1:
        return done("REQUEST_INFO", "instrument_ambiguous", account_id=acct)
    inst = insts[0]["id"]
    d, kind = parse_date(body, sent)
    if d is None:
        return done("REQUEST_INFO", "date_missing", account_id=acct, instrument_id=inst)
    if d > _d(sent):
        return done("REQUEST_INFO", "date_future", account_id=acct, instrument_id=inst)
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] <= as_of:
            q = t["qty"]
            for sp in splits:
                if sp["date"] <= as_of and t["date"] < sp["date"]:
                    q *= sp["ratio"]
            total += q
    base = dict(account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=False)
    ins = [x for x in tools.get_instructions(acct, inst) if x["status"] == "matched" and x["settle_date"] > as_of]
    pend = sum(x["qty"] for x in ins) or None
    pdate = max(x["settle_date"] for x in ins) if ins else None
    ref = total + (pend or 0)
    fig = parse_client_figure(body)
    if fig is not None and ref != 0 and abs(fig - ref) > TOL * abs(ref):
        return done("ESCALATE", "qty_mismatch", settled=total, **base)
    if fig is not None and ref == 0 and fig != 0:
        return done("ESCALATE", "qty_mismatch_zero", settled=0, **base)
    if total == 0 and not pend:
        return done("NOT_HELD", "not_held", **base)
    return done("CONFIRMED", "confirmed_pending" if pend else "confirmed", settled=total,
                pending=pend, pending_date=pdate, **base)


def respond(request, tools):
    return decide(request, tools)[0]
