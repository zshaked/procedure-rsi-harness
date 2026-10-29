import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
TOL = 0.10  # relative tolerance between client's stated figure and ours
MIN_LEVEL = 2


def _d(s):
    return dt.date.fromisoformat(s)


def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def parse_date(body, sent):
    """Return (date or None). Dates are relative to `sent`."""
    t = body
    sd = _d(sent)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        # avoid the forwarded-header 'Date:' line
        for mm in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
            pre = t[max(0, mm.start() - 6):mm.start()]
            if "Date:" in pre:
                continue
            return _mk(*mm.groups())
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _mk(m.group(3), m.group(1), m.group(2))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s]" + MON_RE + r"[-,\s]+(\d{4})\b", t, re.I)
    if m:
        return _mk(m.group(3), MONTHS[m.group(2).lower()], m.group(1))
    m = re.search(r"\b" + MON_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        return _mk(m.group(3), MONTHS[m.group(1).lower()], m.group(2))
    low = t.lower()
    if re.search(r"month[- ]end|end of (the )?(last |previous )?month|last (business )?day of (the )?(last |previous )?month", low):
        first = sd.replace(day=1)
        return first - dt.timedelta(days=1)
    if "yesterday" in low:
        return sd - dt.timedelta(days=1)
    return None


def parse_figure(body):
    m = re.search(r"(?:figure is|records show|we show|we have|we hold|show)\s+(-?\d[\d,]*(?:\.\d+)?)\s*(k|mm|m)?\b", body, re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    u = (m.group(2) or "").lower()
    if u == "k":
        v *= 1e3
    elif u in ("mm", "m"):
        v *= 1e6
    return int(round(v))


def _resolve_account(tools, mentions, body):
    q = mentions.get("account_text")
    cands = []
    if q:
        cands = tools.search_accounts(q)
    if not cands:
        for pat in (r"\bACC-\d+\b", r"\bSA-\d+\b"):
            mm = re.search(pat, body)
            if mm:
                cands = tools.search_accounts(mm.group(0))
                if cands:
                    break
    return cands


def _resolve_instrument(tools, mentions, body):
    q = mentions.get("instrument_text")
    hits = []
    if q:
        hits = tools.search_instruments(q)
    if not hits:
        mm = re.search(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", body)
        if mm:
            hits = tools.search_instruments(mm.group(0))
    if len(hits) > 1 and q:
        cur = [h for h in hits if h["ticker"].lower() == q.strip().lower()]
        if len(cur) == 1:
            hits = cur
    return hits


def respond(request, tools):
    body = request.get("body", "")
    sent = request["sent"]
    sender = request.get("from", "")
    mentions = request.get("mentions") or {}
    domain = sender.split("@")[-1].lower()

    def out(outcome, acct=None, inst=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
        return {"outcome": outcome, "account_id": acct, "instrument_id": inst, "as_of": as_of,
                "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}

    AUTH = out("REQUEST_AUTHORIZATION")
    accs = _resolve_account(tools, mentions, body)
    insts = _resolve_instrument(tools, mentions, body)

    if len(accs) > 1:
        return out("REQUEST_INFO")

    # --- sender verification
    if accs:
        doms = set()
        for a in accs:
            p = tools.get_client_profile(a["id"]) or {}
            doms |= {x.lower() for x in p.get("domains", [])}
        if domain not in doms:
            return AUTH
    else:
        # account unresolved: unknown sender domain cannot be verified
        known = False
        c0 = tools.get_contact(sender)
        if c0:
            for e in tools.get_entitlements(c0["contact_id"]):
                p = tools.get_client_profile(e["account_id"]) or {}
                if domain in {x.lower() for x in p.get("domains", [])}:
                    known = True
        if not known:
            return AUTH
    if len(accs) != 1:
        return out("REQUEST_INFO")
    acct = accs[0]["id"]

    # --- entitlement
    c = tools.get_contact(sender)
    if not c:
        return AUTH
    ok = False
    need = MIN_LEVEL if insts else 3  # account-wide (no instrument) requests need full level
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct and e["level"] >= need and e["expires"] >= sent:
            ok = True
    if not ok:
        return AUTH

    inst = insts[0]["id"] if len(insts) == 1 else None
    if inst is None:
        return out("REQUEST_INFO", acct=acct)

    d = parse_date(body, sent)
    if d is None:
        return out("REQUEST_INFO", acct=acct, inst=inst)
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]
    if as_of > sent:
        return out("REQUEST_INFO", acct=acct, inst=inst)

    profile = tools.get_client_profile(acct) or {}
    if profile.get("legal_hold"):
        return out("ESCALATE", acct=acct, inst=inst, as_of=as_of)

    # --- figures
    splits = tools.get_corporate_actions(inst)
    settled = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q *= s["ratio"]
        settled += q

    pend = 0
    pdate = None
    for x in tools.get_instructions(acct, inst):
        if x["status"] == "matched" and x["settle_date"] > as_of:
            pend += x["qty"]
            if pdate is None or x["settle_date"] > pdate:
                pdate = x["settle_date"]

    claim = parse_figure(body)
    if settled == 0:
        return out("NOT_HELD", acct=acct, inst=inst, as_of=as_of, assumed=False)
    if settled < 0:
        return out("ESCALATE", acct=acct, inst=inst, as_of=as_of, settled=settled)
    if claim is not None:
        close = lambda base: abs(claim - base) <= TOL * abs(base)
        if not (close(settled) or (pend and close(settled + pend))):
            return out("ESCALATE", acct=acct, inst=inst, as_of=as_of, settled=settled)

    r = out("CONFIRMED", acct=acct, inst=inst, as_of=as_of, assumed=False, settled=settled)
    if pend:
        r["pending"] = pend
        r["pending_date"] = pdate
    return r
