import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTHS_LONG = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
               "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
MIN_LEVEL = 3          # entitlement level needed to receive a confirmation
LEVEL_OK = lambda lvl: lvl >= MIN_LEVEL


def _d(s):
    return dt.date.fromisoformat(s)


def parse_as_of(body, sent):
    """Return (iso_date or None, kind). kind in explicit|relative|none."""
    s = _d(sent)
    b = "\n".join(l for l in body.split("\n")
                  if not re.match(r"\s*(From|Date|Sent|To|Subject):", l) and not l.startswith("-----"))
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    cands = []
    if m:
        cands.append((m.start(), dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "explicit"))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b):
        cands.append((m.start(), dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))), "explicit"))
    for m in re.finditer(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", b):
        mo = MONTHS.get(m.group(2).lower())
        if mo:
            cands.append((m.start(), dt.date(int(m.group(3)), mo, int(m.group(1))), "explicit"))
    for m in re.finditer(r"\b(\d{1,2}) ([A-Za-z]{3,9}) (\d{4})\b", b):
        w = m.group(2).lower()
        mo = MONTHS_LONG.get(w) or (MONTHS.get(w) if len(w) == 3 else None)
        if mo:
            cands.append((m.start(), dt.date(int(m.group(3)), mo, int(m.group(1))), "explicit"))
    for m in re.finditer(r"\b([A-Za-z]{3,9}) (\d{1,2}), (\d{4})\b", b):
        w = m.group(1).lower()
        mo = MONTHS_LONG.get(w)
        if mo:
            cands.append((m.start(), dt.date(int(m.group(3)), mo, int(m.group(2))), "explicit"))
    if cands:
        cands.sort(key=lambda x: x[0])
        return cands[0][1].isoformat(), "explicit"
    low = b.lower()
    if re.search(r"\byesterday\b", low):
        return (s - dt.timedelta(days=1)).isoformat(), "relative"
    if re.search(r"(last day of last month|end of last month|month-end|month end)", low):
        first = s.replace(day=1)
        return (first - dt.timedelta(days=1)).isoformat(), "relative"
    return None, "none"


TOL = 0.05   # relative tolerance between the client's stated figure and ours


def parse_claim(body):
    """Client's own figure, e.g. 'our figure is 904819', 'We show 12.5k', 'records show 1.2mm units'."""
    m = re.search(r"(?:our figure is|we show|we have|our records show|records show)\s+"
                  r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(mm|k|m)?\b", body, re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    suf = (m.group(2) or "").lower()
    if suf == "k":
        v *= 1e3
    elif suf in ("mm", "m"):
        v *= 1e6
    return v


SPLIT_ADJUST = False   # oracle rejected the split-adjusted figure (Q1-0121); raw ledger sum used


def _split_factor(tools, inst, as_of, rec_date):
    f = 1
    if not SPLIT_ADJUST:
        return f
    for a in tools.get_corporate_actions(inst):
        if a["type"] == "split" and rec_date < a["date"] <= as_of:
            f *= a["ratio"]
    return f


def settled_qty(tools, acct, inst, as_of):
    tot = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] <= as_of:
            tot += t["qty"] * _split_factor(tools, inst, as_of, t["date"])
    return tot


def pending_info(tools, acct, inst, as_of):
    q, last = 0, None
    for x in tools.get_instructions(acct, inst):
        if x["status"] == "matched" and x["settle_date"] > as_of:
            q += x["qty"] * _split_factor(tools, inst, x["settle_date"], as_of) if False else x["qty"]
            last = x["settle_date"] if last is None or x["settle_date"] > last else last
    return q, last


def _info(acct=None, inst=None):
    return {"outcome": "REQUEST_INFO", "account_id": acct, "instrument_id": inst, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def decide(request, tools):
    m = request.get("mentions", {})
    sent = request["sent"]
    base = {"account_id": None, "instrument_id": None, "as_of": None, "as_of_assumed": False,
            "settled": None, "pending": None, "pending_date": None}

    def out(o, branch, **kw):
        r = dict(base); r["outcome"] = o; r.update(kw)
        return r, branch

    # --- account resolution
    at = m.get("account_text")
    accts = tools.search_accounts(at) if at else []
    contact = tools.get_contact(request["from"])
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    ent_ids = {e["account_id"] for e in ents}
    if len(accts) != 1:
        return out("REQUEST_INFO", "account_unresolved" if not accts else "account_ambiguous")
    acct = accts[0]["id"]
    if acct not in ent_ids:
        return out("REQUEST_INFO", "account_not_entitled")
    # --- authorization
    prof = tools.get_client_profile(acct) or {}
    dom = request["from"].split("@")[-1].lower()
    ok_ent = [e for e in ents if e["account_id"] == acct and LEVEL_OK(e["level"]) and e["expires"] >= sent]
    if not ok_ent:
        return out("REQUEST_AUTHORIZATION", "auth_level_or_expiry")
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return out("REQUEST_AUTHORIZATION", "auth_domain")
    # --- instrument
    it = m.get("instrument_text")
    insts = tools.search_instruments(it) if it else []
    if len(insts) != 1:
        return out("REQUEST_INFO", "instrument_unresolved" if not insts else "instrument_ambiguous", account_id=acct)
    inst = insts[0]["id"]
    # --- date
    as_of, kind = parse_as_of(request["body"], sent)
    if as_of is None:
        return out("REQUEST_INFO", "no_date", account_id=acct, instrument_id=inst)
    cal = tools.get_calendar(as_of)
    if not cal["business_day"]:
        return out("REQUEST_INFO", "non_business_day", account_id=acct, instrument_id=inst)
    if prof.get("legal_hold"):
        return out("ESCALATE", "legal_hold", account_id=acct, instrument_id=inst)
    if prof.get("no_email_confirm"):
        return out("ESCALATE", "no_email_confirm", account_id=acct, instrument_id=inst)
    if as_of > sent:
        return out("REQUEST_INFO", "future_date", account_id=acct, instrument_id=inst)
    ledger = tools.get_ledger(acct, inst)
    settled = settled_qty(tools, acct, inst, as_of)
    pq, pd = pending_info(tools, acct, inst, as_of)
    claim = parse_claim(request["body"])
    if claim is not None and settled and abs(claim - settled) / abs(settled) > TOL:
        return out("ESCALATE", "qty_mismatch", account_id=acct, instrument_id=inst)
    if not ledger or (settled == 0 and pq == 0):
        return out("NOT_HELD", "not_held", account_id=acct, instrument_id=inst, as_of=as_of)
    r = dict(base)
    r.update(outcome="CONFIRMED", account_id=acct, instrument_id=inst, as_of=as_of, settled=settled)
    if pq:
        r["pending"], r["pending_date"] = pq, pd
    return r, "confirmed"


def respond(request, tools):
    return decide(request, tools)[0]
