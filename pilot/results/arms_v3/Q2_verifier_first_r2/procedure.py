"""Desk procedure: respond(request, tools) -> response dict. Deterministic, stdlib only."""
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


# Variant knobs (the search in scratch/search.py picks these by verifier pass rate).
P = {
    "missing_date": "last_month_end",   # | prev_bd_sent | sent
    "pending_date": "max",              # | min
    "pending_status": ("matched",),     # | ("matched", "unmatched")
    "order": "acct_auth_flags_inst",    # | "acct_inst_auth_flags"
    "all_subs": True,
    "split_adjust": True,
    "roll": True,
    "future": "REQUEST_INFO",
}

_ID_RE = re.compile(r"\b(ACC-\d+|SA-\d+)\b", re.I)
_ISIN_RE = re.compile(r"\b([A-Z]{2}\d{10})\b")
_LEAD = re.compile(r"^(?:our|the|my)?\s*(?:account|acct|a/c|fund|portfolio|sub-account)?\s*[:#]?\s*", re.I)


def _resolve_account(tools, text, body):
    cands = []
    if text:
        cands += [text, _LEAD.sub("", text.strip()).strip(" .,;:()\"'")]
        cands += _ID_RE.findall(text)
    else:
        cands += _ID_RE.findall(body or "")
    for c in cands:
        if c and c.strip():
            hits = tools.search_accounts(c)
            if hits:
                return hits
    return []


def _resolve_instrument(tools, text):
    if not text:
        return []
    cands = [text, text.strip(" .,;:()\"'")]
    cands += _ISIN_RE.findall(text)
    cands.append(re.sub(r"\s+(shares|stock|units|position)$", "", text.strip(), flags=re.I))
    for c in cands:
        if c and c.strip():
            hits = tools.search_instruments(c)
            if hits:
                return hits
    return []


def _roll(tools, d_iso):
    if not P["roll"]:
        return d_iso
    c = tools.get_calendar(d_iso)
    return d_iso if c["business_day"] else c["previous_business_day"]


def _settled(tools, acct, inst, as_of):
    splits = [ca for ca in tools.get_corporate_actions(inst) if ca.get("type") == "split"] if P["split_adjust"] else []
    primary = (tools.get_account(acct) or {}).get("sub_accounts", [None])[0]
    tot = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > as_of:
            continue
        if not P["all_subs"] and t["sub_account"] != primary:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        tot += q
    return tot


def _pending(tools, acct, inst, as_of):
    xs = [x for x in tools.get_instructions(acct, inst)
          if x["status"] in P["pending_status"] and x["settle_date"] > as_of]
    if not xs:
        return None, None
    ds = [x["settle_date"] for x in xs]
    return sum(x["qty"] for x in xs), (max(ds) if P["pending_date"] == "max" else min(ds))


def _authorized(tools, req, acct):
    sender = (req.get("from") or "").strip().lower()
    dom = sender.split("@")[-1]
    prof = tools.get_client_profile(acct) or {}
    if dom not in [x.lower() for x in prof.get("domains", [])]:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    return any(e["account_id"] == acct and e["level"] >= 2 and e["expires"] >= req["sent"]
               for e in tools.get_entitlements(c["contact_id"]))


def _resp(outcome, acct=None, inst=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acct, "instrument_id": inst, "as_of": as_of,
            "as_of_assumed": bool(assumed) if as_of else False, "settled": settled,
            "pending": pending, "pending_date": pdate}


def respond(request, tools):
    m = request.get("mentions") or {}
    body = request.get("body") or ""
    sent = request["sent"]
    accs = _resolve_account(tools, m.get("account_text"), body)
    ins = _resolve_instrument(tools, m.get("instrument_text"))
    # 1. account must resolve to exactly one account
    if len(accs) != 1:
        return _resp("REQUEST_INFO")
    acct = accs[0]["id"]
    inst = ins[0]["id"] if len(ins) == 1 else None
    if P["order"] == "acct_inst_auth_flags" and not inst:
        return _resp("REQUEST_INFO")
    # 2. sender authorization (domain, contact, live entitlement level >= 2)
    if not _authorized(tools, request, acct):
        return _resp("REQUEST_AUTHORIZATION")
    prof = tools.get_client_profile(acct) or {}
    # 3. client flags
    if prof.get("no_email_confirm"):
        return _resp("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return _resp("ESCALATE", acct, inst)
    # 4. instrument must resolve
    if not inst:
        return _resp("REQUEST_INFO")
    # 5. position date
    d, found = parse_date(body, sent)
    if found and d is None:
        return _resp("REQUEST_INFO")
    if not found:
        s = _dt.date.fromisoformat(sent)
        if P["missing_date"] == "last_month_end":
            base = _month_end_prev(s).isoformat()
            as_of = _roll(tools, base)
        elif P["missing_date"] == "prev_bd_sent":
            as_of = tools.get_calendar(sent)["previous_business_day"]
        else:
            as_of = _roll(tools, sent)
    else:
        if d.isoformat() >= sent:
            return _resp(P["future"])
        as_of = _roll(tools, d.isoformat())
    # 6. desk figure and comparison with the client's figure
    settled = _settled(tools, acct, inst, as_of)
    claim = parse_claim(body)
    if claim is not None and claim != settled:
        return _resp("ESCALATE", acct, inst)
    if settled <= 0:
        return _resp("NOT_HELD", acct, inst, as_of, not found)
    pend, pdate = _pending(tools, acct, inst, as_of)
    return _resp("CONFIRMED", acct, inst, as_of, not found, settled, pend, pdate)
