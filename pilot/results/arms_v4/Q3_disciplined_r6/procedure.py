import re, datetime as dt

LEVEL_REQUIRED = 3
PEND_WINDOW_DAYS = 30      # matched instruction is pending if as_of < settle_date <= sent + this (assumption: Q3-0008 +7d reported; Q3-0018 +81d, Q3-0020 +125d not)
LARGE_POSITION = 1_000_000  # settled >= this -> ESCALATE (Q3-0145 oracle: 'positions that size always go to escalation'; threshold between 855,399 (hist confirmed) and 1,051,242; round-number guess)
EXPIRY_MARGIN_DAYS = 90    # guess: valid cases in data expire >= 312d out; Q3-0032 (+68d) judged lapsed

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _d(s):
    return dt.date.fromisoformat(s)


def _month_end_prev(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date|None, status) status in ok|none."""
    t = body
    t = re.sub(r"---------- Forwarded message ---------.*?\n\n", "", t, flags=re.S)  # drop fwd header
    s = sent
    low = t.lower()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), "ok"
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])), "ok"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2])), "ok"
    m = re.search(r"\b([A-Z][a-z]{2,8})\.? (\d{1,2}),? (\d{4})\b", t)
    if m and m[1][:3].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), "ok"
    m = re.search(r"\b(\d{1,2}) ([A-Z][a-z]{2,8}) (\d{4})\b", t)
    if m and m[2][:3].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), "ok"
    if "yesterday" in low:
        return s - dt.timedelta(days=1), "ok"
    if re.search(r"(end of last month|last day of last month|month-end|month end|end of the month)", low):
        return _month_end_prev(s), "ok"
    return None, "none"


def parse_claim(body):
    """Return (value, tolerance) or (None, 0). Tolerance is half a unit of the last written digit for k/mm forms."""
    m = re.search(r"(?:figure is|records show|we show|we have|show)\s+(-?[\d,]*\.?\d+)\s*(k|mm|m)?\b", body, re.I)
    if not m:
        return None, 0
    txt = m[1].replace(",", "")
    v = float(txt)
    suf = (m[2] or "").lower()
    mult = 1000 if suf == "k" else 1e6 if suf in ("mm", "m") else 1
    dec = len(txt.split(".")[1]) if "." in txt else 0
    tol = 0.5 * mult / (10 ** dec) if suf else 0
    return int(round(v * mult)), tol


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def decide(request, tools):
    body = request.get("body", "")
    m = request.get("mentions", {}) or {}
    sent = _d(request["sent"])
    contact = tools.get_contact(request["from"])
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # --- account resolution
    atext = m.get("account_text")
    if atext:
        accs = tools.search_accounts(atext)
        if len(accs) > 1:
            return _resp("REQUEST_INFO"), "account_ambiguous"
        if not accs:
            return _resp("REQUEST_INFO"), "account_unknown"
        acc = accs[0]["id"]
    else:
        own = {e["account_id"] for e in ents}
        if len(own) == 1:
            acc = next(iter(own))
        else:
            return _resp("REQUEST_INFO"), "account_missing"

    # --- authorization, part 1: sender's level (Q3-0014/0010/0015: level<3 -> AUTH even with odd dates)
    if not contact or not ents or max(e["level"] for e in ents) < LEVEL_REQUIRED:
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"

    # --- date (Q3-0198 oracle: non-business date -> ask which date; Q3-0022 history agrees)
    d, st = parse_date(body, sent)
    assumed = False
    if d is None:
        d, assumed = sent, True
    if not tools.get_calendar(d.isoformat())["business_day"]:
        return _resp("REQUEST_INFO"), "nonbd_date"

    # --- authorization, part 2: entitlement for this account
    mine = [e for e in ents if e["account_id"] == acc]
    if not mine:
        return _resp("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    best = max(mine, key=lambda e: (e["expires"], e["level"]))
    # Q3-0032 oracle: expiry 68d after sent counted as lapsed -> lapse if expiring within EXPIRY_MARGIN_DAYS of sent
    if best["expires"] < (sent + dt.timedelta(days=EXPIRY_MARGIN_DAYS)).isoformat():
        return _resp("REQUEST_AUTHORIZATION"), "auth_expired"
    if best["level"] < LEVEL_REQUIRED:
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"

    # --- instrument resolution
    itext = m.get("instrument_text")
    if not itext:
        return _resp("REQUEST_INFO", account_id=acc if False else None), "instrument_missing"
    ins = tools.search_instruments(itext)
    if len(ins) != 1:
        return _resp("REQUEST_INFO"), "instrument_unresolved"
    inst = ins[0]["id"]

    if d > sent:
        return _resp("REQUEST_INFO"), "future_date"

    prof = tools.get_client_profile(acc) or {}
    if prof.get("no_email_confirm"):
        return _resp("REQUEST_AUTHORIZATION"), "no_email_confirm"
    if prof.get("legal_hold"):
        return _resp("ESCALATE", account_id=acc, instrument_id=inst), "legal_hold"

    as_of = d.isoformat()

    # --- position
    ledger = tools.get_ledger(acc, inst)
    splits = tools.get_corporate_actions(inst)
    settled = 0
    for t in ledger:
        if t["date"] <= as_of:
            q = t["qty"]
            for sp in splits:
                if t["date"] < sp["date"] <= as_of:   # only splits that have happened by as_of
                    q = q * sp["ratio"]
            settled += q

    limit = (sent + dt.timedelta(days=PEND_WINDOW_DAYS)).isoformat()
    cands = [x for x in tools.get_instructions(acc, inst)
             if x["status"] == "matched" and as_of < x["settle_date"] <= limit]
    pend = sum(x["qty"] for x in cands) if cands else None
    pdate = min(x["settle_date"] for x in cands) if cands else None

    if settled >= LARGE_POSITION:
        return _resp("ESCALATE", account_id=acc, instrument_id=inst, as_of=as_of,
                     as_of_assumed=assumed, settled=settled), "large_position"

    if settled == 0:   # Q3-0080 oracle: no holding -> NOT_HELD even if the client states a figure
        return _resp("NOT_HELD", account_id=acc, instrument_id=inst, as_of=as_of,
                     as_of_assumed=assumed), "not_held"

    claim, prec = parse_claim(body)
    if claim is not None:
        allm = [x["qty"] for x in tools.get_instructions(acc, inst)
                if x["status"] == "matched" and x["settle_date"] > as_of]
        ok = [settled, settled + sum(allm)] + [settled + q for q in allm]   # Q3-0074 answer: claim may include pending
        if not any(abs(claim - v) <= prec for v in ok):
            return _resp("ESCALATE", account_id=acc, instrument_id=inst, as_of=as_of,
                         as_of_assumed=assumed, settled=settled), "qty_mismatch"

    return _resp("CONFIRMED", account_id=acc, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
                 settled=settled, pending=pend, pending_date=pdate), ("confirm_pending" if pend else "confirm")


def respond(request, tools):
    return decide(request, tools)[0]
