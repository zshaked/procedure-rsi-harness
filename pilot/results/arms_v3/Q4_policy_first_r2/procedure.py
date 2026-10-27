"""Induced procedure for the holdings-confirmation desk.

Deterministic; standard library only; all state via `tools`.
"""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
MON3["sept"] = 9

TOLERANCE = 0.10  # relative tolerance between client's figure and ours before escalating


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- text cleanup
def _clean_body(body):
    body = body or ""
    # drop forwarded-header lines and disclaimers so their dates are not read as position dates
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if re.match(r"^-{3,}\s*forwarded message", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|subject|cc):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        lines.append(ln)
    return "\n".join(lines)


# ---------------------------------------------------------------- dates
def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _month_end(year, month):
    if month == 12:
        return dt.date(year, 12, 31)
    return dt.date(year, month + 1, 1) - dt.timedelta(days=1)


def _parse_date(text, sent):
    """Return (date, vague) or (None, None). vague=True when the date was inferred from a
    relative phrase rather than stated explicitly."""
    t = text
    tl = t.lower()
    # explicit formats
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        d = _mk(m.group(1), m.group(2), m.group(3))
        if d:
            return d, False
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        d = _mk(m.group(3), m.group(1), m.group(2))  # US style m/d/yyyy
        if d is None:
            d = _mk(m.group(3), m.group(2), m.group(1))
        if d:
            return d, False
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})\.?[- ,]+(\d{4})\b", t)
    if m:
        mon = m.group(2).lower()
        mo = MONTHS.get(mon) or MON3.get(mon[:4]) or MON3.get(mon[:3])
        if mo and (mon in MONTHS or len(mon) <= 4):
            d = _mk(m.group(3), mo, m.group(1))
            if d:
                return d, False
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m:
        mon = m.group(1).lower()
        mo = MONTHS.get(mon) or (MON3.get(mon[:3]) if len(mon) <= 4 else None)
        if mo:
            d = _mk(m.group(3), mo, m.group(2))
            if d:
                return d, False
    # relative phrases
    if re.search(r"\byesterday\b", tl):
        return sent - dt.timedelta(days=1), False
    if re.search(r"\btoday\b|\bclose of business today\b", tl):
        return sent, False
    if re.search(r"(last day of (the )?(last|previous|prior) month|end of (the )?(last|previous|prior) month|"
                 r"month[- ]end|end of (the )?month|last month[- ]end|previous month[- ]end)", tl):
        prev = sent.replace(day=1) - dt.timedelta(days=1)
        return prev, True
    if re.search(r"(year[- ]end|end of (last )?year)", tl):
        return dt.date(sent.year - 1, 12, 31), True
    return None, None


def _roll_back(tools, d):
    """Latest business day on or before d."""
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


# ---------------------------------------------------------------- quantities
def _parse_qty(s):
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mm|m|k|bn|b)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"k": 1e3, "m": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}.get(m.group(2) or "", 1)
    return int(round(v * mult))


def _client_figure(text):
    pats = [r"(?:records show|our figure is|we show|we have|we hold|our books show|we see|our position is|"
            r"we expect|showing|show)\s+(\d[\d,]*(?:\.\d+)?\s*(?:mm|k|m|bn)?)\b"]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            return _parse_qty(m.group(1))
    return None


# ---------------------------------------------------------------- position
def _settled(tools, acct, inst, as_of, sub=None):
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if sub and t["sub_account"] != sub:
            continue
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s.get("type") == "split" and t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        total += q
    return total


def _pending(tools, acct, inst, as_of):
    xs = [x for x in tools.get_instructions(acct, inst)
          if x["status"] == "matched" and x["settle_date"] > as_of]
    if not xs:
        return None, None
    return sum(x["qty"] for x in xs), max(x["settle_date"] for x in xs)


# ---------------------------------------------------------------- main
def respond(request, tools):
    return _respond(request, tools)[0]


def _respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"][:10])
    sender = (request.get("from") or "").strip().lower()
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    mentions = request.get("mentions") or {}
    acct_text = (mentions.get("account_text") or "").strip()
    inst_text = (mentions.get("instrument_text") or "").strip()
    body = _clean_body(request.get("body") or "")

    contact = tools.get_contact(sender) if sender else None

    # resolve account
    accts = tools.search_accounts(acct_text) if acct_text else []
    sub = None
    if acct_text and len(accts) == 1:
        a = tools.get_account(accts[0]["id"])
        if acct_text.lower() in (s.lower() for s in a["sub_accounts"]) and len(a["sub_accounts"]) > 1:
            sub = next(s for s in a["sub_accounts"] if s.lower() == acct_text.lower())
    insts = tools.search_instruments(inst_text) if inst_text else []

    # sender must at least come from a domain belonging to one of the candidate accounts' clients
    # or be a known contact; otherwise authorization is needed before anything else
    cand_domains = set()
    for a in accts:
        p = tools.get_client_profile(a["id"]) or {}
        cand_domains.update(d.lower() for d in p.get("domains", []))
    if contact is None:
        return _blank("REQUEST_AUTHORIZATION"), "auth:unknown_contact"
    if not accts:
        # No account resolved. Look at the sender's own entitled accounts whose client domain
        # matches the sender's domain ("our account"). None -> authorization needed (Q4-0009);
        # exactly one and no account named -> that account (oracle rejected REQUEST_INFO on
        # Q4-0055); otherwise ask.
        own = []
        for e in tools.get_entitlements(contact["contact_id"]):
            p = tools.get_client_profile(e["account_id"]) or {}
            if domain in (d.lower() for d in p.get("domains", [])) and e["account_id"] not in own:
                own.append(e["account_id"])
        if not own:
            return _blank("REQUEST_AUTHORIZATION"), "auth:no_account_foreign_domain"
        if acct_text or len(own) != 1:
            return _blank("REQUEST_INFO"), "info:no_account"
        a = tools.get_account(own[0])
        accts = [{"id": a["id"], "name": a["name"], "short_name": a["short_name"]}]
        p = tools.get_client_profile(a["id"]) or {}
        cand_domains = set(d.lower() for d in p.get("domains", []))
    if domain not in cand_domains:
        return _blank("REQUEST_AUTHORIZATION"), "auth:domain"

    # need one account, one instrument, one date
    date_raw, vague = _parse_date(body, sent)
    if len(accts) != 1:
        return _blank("REQUEST_INFO"), "info:account_ambiguous"
    if len(insts) != 1:
        return _blank("REQUEST_INFO"), "info:instrument"
    if date_raw is None:
        return _blank("REQUEST_INFO"), "info:no_date"
    if date_raw > sent:
        return _blank("REQUEST_INFO"), "info:future_date"

    acct = accts[0]["id"]
    inst = insts[0]["id"]
    profile = tools.get_client_profile(acct) or {}
    if domain not in [d.lower() for d in profile.get("domains", [])]:
        return _blank("REQUEST_AUTHORIZATION"), "auth:domain2"
    ok = False
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] == acct and e["level"] >= 2 and e["expires"] >= sent.isoformat():
            ok = True
    if not ok:
        return _blank("REQUEST_AUTHORIZATION"), "auth:entitlement"
    # no_email_confirm: oracle said a confirmation is fine for such an account (Q4-0054); not a gate
    if profile.get("legal_hold"):
        return _blank("ESCALATE", account_id=acct, instrument_id=inst), "esc:legal_hold"

    as_of_d = _roll_back(tools, date_raw)
    as_of = as_of_d.isoformat()
    settled = _settled(tools, acct, inst, as_of)  # whole account even if a sub-account was named (oracle Q4-0156)
    pend, pend_date = _pending(tools, acct, inst, as_of)
    assumed = False  # oracle: rolled weekend dates and "month-end" are not flagged as assumed

    if settled == 0:
        # nothing held: NOT_HELD even if the client quotes a figure (oracle Q4-0157)
        return _blank("NOT_HELD", account_id=acct, instrument_id=inst, as_of=as_of,
                      as_of_assumed=assumed, pending=pend, pending_date=pend_date), "not_held"

    fig = _client_figure(body)
    if fig is not None:
        cands = [settled] + ([settled + pend] if pend else [])
        if not any(abs(fig - c) <= TOLERANCE * max(abs(c), 1) for c in cands):
            return _blank("ESCALATE", account_id=acct, instrument_id=inst), "esc:mismatch"

    return _blank("CONFIRMED", account_id=acct, instrument_id=inst, as_of=as_of,
                  as_of_assumed=assumed, settled=settled, pending=pend, pending_date=pend_date), "confirmed"
