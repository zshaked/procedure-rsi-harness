"""Reference-free verifier for desk replies.

verify(request, response, tools) -> (ok, failures). Each check below is independent and commented
with the evidence it rests on (H = histories case id, U = unlabeled, O = oracle answer, D = tool doc).
"""
import re, datetime as _dt

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _mk(y, m, d):
    try:
        return _dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def _month_end_prev(sent):
    return sent.replace(day=1) - _dt.timedelta(days=1)


def parse_date(body, sent_iso):
    """Return (date|None, found: bool). found=False means no date was stated."""
    sent = _dt.date.fromisoformat(sent_iso)
    # strip forwarded header lines ("Date: 2026-01-30") so they are not read as the position date
    text = re.sub(r"(?im)^\s*(date|sent)\s*:.*$", " ", body)
    t = text.lower()
    # relative phrases
    if re.search(r"\byesterday\b", t):
        return sent - _dt.timedelta(days=1), True
    if re.search(r"\btoday\b|\bcurrent(ly)?\b|\bas of now\b", t) and not re.search(r"\d{4}", t):
        return sent, True
    if re.search(r"end of last month|last day of last month|month[- ]end|end of (the )?previous month|last month[- ]end", t):
        return _month_end_prev(sent), True
    # ISO
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        return _mk(*m.groups()), True
    # 27-Jan-2026 / 27 Jan 2026 / 27 January 2026 (optional weekday)
    m = re.search(r"\b(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]+(\d{4})\b", text)
    if m and m.group(2)[:3].lower() in _MONTHS:
        return _mk(m.group(3), _MONTHS[m.group(2)[:3].lower()], m.group(1)), True
    # January 8, 2026 / Jan 8 2026
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text)
    if m and m.group(1)[:3].lower() in _MONTHS:
        return _mk(m.group(3), _MONTHS[m.group(1)[:3].lower()], m.group(2)), True
    # US numeric m/d/yyyy
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:
        return _mk(m.group(3), m.group(1), m.group(2)), True
    return None, False


def parse_qty_token(s):
    s = s.strip().lower().replace(",", "")
    mult = 1
    for suf, mu in (("mm", 1000000), ("m", 1000000), ("k", 1000), ("bn", 1000000000)):
        if s.endswith(suf):
            s, mult = s[: -len(suf)], mu
            break
    try:
        return int(round(float(s) * mult))
    except Exception:
        return None


_CLAIM_RE = re.compile(
    r"(?:we show|our figure is|our records show|we have|we hold|our books show|we record|we see|shows?|figure of)\s*:?\s*"
    r"(\d[\d,]*(?:\.\d+)?\s*(?:mm|bn|k|m)?)\b", re.I)


def parse_claim(body):
    m = _CLAIM_RE.search(body)
    if not m:
        return None
    return parse_qty_token(m.group(1))


def business_roll(tools, d_iso):
    c = tools.get_calendar(d_iso)
    return d_iso if c["business_day"] else c["previous_business_day"]


def settled_qty(tools, acct, inst, as_of):
    """Sum of all sub-accounts' settled ledger up to as_of, split-adjusted to as_of."""
    splits = [ca for ca in tools.get_corporate_actions(inst) if ca.get("type") == "split"]
    tot = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        tot += q
    return tot


def pending_info(tools, acct, inst, as_of):
    xs = [x for x in tools.get_instructions(acct, inst) if x["status"] == "matched" and x["settle_date"] > as_of]
    if not xs:
        return None, None
    return sum(x["qty"] for x in xs), max(x["settle_date"] for x in xs)


def authorized(tools, req, acct):
    """(ok, reason). Contact must exist, sender domain must be a client domain, and an unexpired
    entitlement of level >= 2 for the account must exist."""
    sender = req["from"].strip().lower()
    dom = sender.split("@")[-1]
    prof = tools.get_client_profile(acct) or {}
    if dom not in [x.lower() for x in prof.get("domains", [])]:
        return False, "domain"
    c = tools.get_contact(sender)
    if not c:
        return False, "no_contact"
    ents = [e for e in tools.get_entitlements(c["contact_id"]) if e["account_id"] == acct]
    if not ents:
        return False, "no_entitlement"
    if not any(e["expires"] >= req["sent"] for e in ents):
        return False, "expired"
    if not any(e["level"] >= 2 and e["expires"] >= req["sent"] for e in ents):
        return False, "level"
    return True, "ok"

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}

# Conventions calibrated with the oracle (see NOTES.md for the question log).
CFG = {
    "missing_date": "last_month_end",   # O: Q2-0076 prev-business-day rejected, last month-end accepted
    "future_outcome": "REQUEST_INFO",   # assumption (no resolvable future-dated case in the data)
}


def derive(request, tools):
    """Facts any correct response depends on, evaluated in the desk's order:
    account -> sender authorization -> client flags -> instrument -> date -> figure."""
    m = request.get("mentions") or {}
    f = {"acct": None, "inst": None}
    at, it = m.get("account_text"), m.get("instrument_text")
    accs = tools.search_accounts(at) if at else []
    ins = tools.search_instruments(it) if it else []
    f["n_acc"], f["n_ins"] = len(accs), len(ins)
    d, found = parse_date(request["body"], request["sent"])
    f["date_found"] = found
    f["claim"] = parse_claim(request["body"])
    if len(accs) != 1:
        f["expect"] = "REQUEST_INFO"; f["why"] = "account"; return f
    f["acct"] = accs[0]["id"]
    ok, why = authorized(tools, request, f["acct"])
    f["auth"] = why
    if not ok:
        f["expect"] = "REQUEST_AUTHORIZATION"; f["why"] = "auth"; return f
    prof = tools.get_client_profile(f["acct"]) or {}
    if prof.get("no_email_confirm"):
        f["expect"] = "REQUEST_AUTHORIZATION"; f["why"] = "no_email_confirm"; return f
    if len(ins) == 1:
        f["inst"] = ins[0]["id"]
    if prof.get("legal_hold"):
        f["expect"] = "ESCALATE"; f["why"] = "legal_hold"; return f
    if not f["inst"]:
        f["expect"] = "REQUEST_INFO"; f["why"] = "instrument"; return f
    if found and d is None:
        f["expect"] = "REQUEST_INFO"; f["why"] = "bad_date"; return f
    if not found:
        as_of = business_roll(tools, _month_end_prev(_dt.date.fromisoformat(request["sent"])).isoformat())
    else:
        if d.isoformat() >= request["sent"]:
            f["expect"] = CFG["future_outcome"]; f["why"] = "future"; return f
        as_of = business_roll(tools, d.isoformat())
    f["as_of"], f["as_of_assumed"] = as_of, not found
    f["settled"] = settled_qty(tools, f["acct"], f["inst"], as_of)
    if f["claim"] is not None and f["claim"] != f["settled"]:
        f["expect"] = "ESCALATE"; f["why"] = "mismatch"; return f
    if f["settled"] <= 0:
        f["expect"] = "NOT_HELD"; f["why"] = "zero"; return f
    f["expect"] = "CONFIRMED"; f["why"] = "ok"
    f["pending"], f["pending_date"] = pending_info(tools, f["acct"], f["inst"], as_of)
    return f


def verify(request, response, tools):
    fails = []
    out = response.get("outcome")
    # C0 outcome is one of the five allowed values (README).
    if out not in OUTCOMES:
        return False, ["C0 invalid outcome %r" % out]
    f = derive(request, tools)
    exp, why = f["expect"], f["why"]
    # C1 account text missing / not found / matching several accounts -> REQUEST_INFO; checked first
    #    (H 0002, 0005, 0023 ambiguous fund families; H 0003 "our account" with no name).
    if why == "account" and out != "REQUEST_INFO":
        fails.append("C1 account not uniquely resolvable -> REQUEST_INFO")
    # C2 sender authorization before anything else about the position: sender domain must be one of
    #    the client's registered domains, contact known, unexpired entitlement level>=2
    #    (H 0014 proton.me despite level-3 entitlement; H 0009 expired; H 0018, 0024 level 1;
    #    H 0000, 0007, 0019 no entitlement; H 0001, 0017 level 2 confirmed;
    #    O Q2-0081 auth beats legal hold; O Q2-0095 domain beats no-email flag;
    #    O Q2-0041 auth beats missing instrument).
    if why == "auth" and out != "REQUEST_AUTHORIZATION":
        fails.append("C2 sender not authorized (%s) -> REQUEST_AUTHORIZATION" % f.get("auth"))
    # C3 client profile no_email_confirm -> REQUEST_AUTHORIZATION, even if instrument missing
    #    (O Q2-0105).
    if why == "no_email_confirm" and out != "REQUEST_AUTHORIZATION":
        fails.append("C3 client takes no email confirmations -> REQUEST_AUTHORIZATION")
    # C4 client under legal hold -> ESCALATE (O Q2-0096).
    if why == "legal_hold" and out != "ESCALATE":
        fails.append("C4 legal hold -> ESCALATE")
    # C5 instrument missing / unknown / ambiguous -> REQUEST_INFO (README; U 0041/0070 'positions held').
    if why == "instrument" and out != "REQUEST_INFO":
        fails.append("C5 instrument not uniquely resolvable -> REQUEST_INFO")
    # C6 position date on/after the sent date (or unparseable) -> REQUEST_INFO (assumption).
    if why in ("future", "bad_date") and out != exp:
        fails.append("C6 date not confirmable -> %s" % exp)
    # C7 client's stated figure differs from the desk figure -> ESCALATE
    #    (H 0008, 0011, 0013, 0015, 0016, 0020, 0012 all mismatches escalated; H 0004 match confirmed).
    if why == "mismatch" and out != "ESCALATE":
        fails.append("C7 claimed %s != desk figure %s -> ESCALATE" % (f["claim"], f["settled"]))
    # C8 nothing held at as_of -> NOT_HELD (O Q2-0123 empty ledger; O Q2-0153 closed-out position;
    #    the oracle's first answer on 0153 was a noisy 'not sure').
    if why == "zero" and out != "NOT_HELD":
        fails.append("C8 zero holding -> NOT_HELD")
    # C9 otherwise CONFIRMED (H 0001, 0004, 0010, 0017, 0021, 0022; H 0006 escalation was an operator
    #    mistake: O Q2-0006 accepted CONFIRMED).
    if why == "ok" and out != "CONFIRMED":
        fails.append("C9 position confirmable -> CONFIRMED")
    # C10 identifiers: resolved account id (not the text; H 0010 SGEIII -> ACC-10225) and instrument id
    #     (old tickers resolve to the current instrument, O Q2-0053) for CONFIRMED/NOT_HELD/ESCALATE.
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE") and out == exp:
        if response.get("account_id") != f["acct"]:
            fails.append("C10 account_id should be %s" % f["acct"])
        if response.get("instrument_id") != f["inst"]:
            fails.append("C10 instrument_id should be %s" % f["inst"])
    # C11 as_of = stated date rolled back to a business day (H 0017 Sat 31 Jan -> 2026-01-30; holidays
    #     from get_calendar); 'yesterday' = sent-1; 'month-end'/'end of last month' = last day of the
    #     previous month (O Q2-0053); no date -> previous month-end, as_of_assumed=True (O Q2-0076).
    if out in ("CONFIRMED", "NOT_HELD") and "as_of" in f:
        if response.get("as_of") != f["as_of"]:
            fails.append("C11 as_of should be %s" % f["as_of"])
        if bool(response.get("as_of_assumed")) != f["as_of_assumed"]:
            fails.append("C11 as_of_assumed should be %s" % f["as_of_assumed"])
    # C12 settled = all custody sub-accounts summed, transactions dated <= as_of, each multiplied by
    #     any split dated after it and on/before as_of (H 0004 two sub-accounts; H 0022; O Q2-0069 split;
    #     O Q2-0191 total even when a sub-account is named; get_position_summary is NOT the desk figure:
    #     primary sub-account only and previous day).
    if out == "CONFIRMED" and "settled" in f and response.get("settled") != f["settled"]:
        fails.append("C12 settled should be %s" % f["settled"])
    # C13 pending = sum of MATCHED instructions settling after as_of, pending_date = latest settle date;
    #     cancelled/unmatched ignored (H 0021; H 0010 cancelled only -> none; O Q2-0069 two matched;
    #     O Q2-0025 settle date after as_of but before sent still reported; O Q2-0006 level 2 sees it).
    if out == "CONFIRMED" and "pending" in f:
        if response.get("pending") != f["pending"] or response.get("pending_date") != f["pending_date"]:
            fails.append("C13 pending should be %s/%s" % (f["pending"], f["pending_date"]))
    # C14 fields that do not apply are empty (README).
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION"):
        for k in ("settled", "pending", "pending_date", "as_of"):
            if response.get(k) is not None:
                fails.append("C14 %s must be None for %s" % (k, out))
    if out in ("NOT_HELD", "ESCALATE"):
        for k in ("settled", "pending", "pending_date"):
            if response.get(k) is not None:
                fails.append("C14 %s must be None for %s" % (k, out))
    return (not fails), fails
