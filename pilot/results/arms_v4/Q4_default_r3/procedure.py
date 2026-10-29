"""Procedure for the confirmation desk.  Standard library + `tools` only.  Deterministic."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

TOLERANCE = 0.10          # relative break tolerance between client figure and ours
MIN_LEVEL = 2             # entitlement level needed to receive a confirmation


# ----------------------------------------------------------------------------- parsing
def _body_lines(body):
    """Drop forwarded-message header lines and boilerplate, keep the content."""
    out = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^-{3,}\s*Forwarded message", s, re.I):
            continue
        if re.match(r"^(From|Date|To|Subject|Sent|Cc):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        out.append(s)
    return "\n".join(out)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _last_day_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Free-text date as written (before any business-day roll), or None."""
    t = text
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d1 = _mk(y, a, b)                      # US month/day/year
        if d1 is None:
            return _mk(y, b, a)
        return d1
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]*(\d{4})\b", t)
    if m and m.group(2).lower() in MONTHS:
        return _mk(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m and m.group(1).lower() in MONTHS:
        return _mk(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})\b", t)
    if m and m.group(2).lower() in MONTHS:
        return _mk(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    low = t.lower()
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1)
    if re.search(r"((end|last (?:business )?day) of (?:the )?(?:last|previous|prior) month|"
                 r"(?:last|previous|prior) month[- ]end|month[- ]end|end of (?:the )?month)", low):
        return _last_day_prev_month(sent)
    if re.search(r"\b(?:last|previous) business day\b", low):
        return sent - dt.timedelta(days=1)       # rolled back to a business day by the caller
    if re.search(r"\btoday\b", low):
        return sent
    return None


def parse_qty_token(tok):
    tok = tok.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)(k|m|mm|mn)?$", tok, re.I)
    if not m:
        return None
    v = float(m.group(1))
    suf = (m.group(2) or "").lower()
    if suf == "k":
        v *= 1e3
    elif suf in ("m", "mm", "mn"):
        v *= 1e6
    return int(round(v))


_NUM = r"(-?\d[\d,]*(?:\.\d+)?)\s*(mm|mn|m|k)?(?![A-Za-z0-9])"


def parse_stated_qty(text):
    m = re.search(r"(?:records show|books show|we show|we have|our figure is|figure is|we hold|"
                  r"we are showing|showing|we see|shows)\s*:?\s*" + _NUM, text, re.I)
    if m:
        return parse_qty_token(m.group(1) + (m.group(2) or ""))
    # fallback: a lone free-standing number once ids and dates are removed
    t = re.sub(r"\b[A-Z]{2}\d{10}\b", " ", text)
    t = re.sub(r"\b(?:ACC|SA)-\d+\b", " ", t, flags=re.I)
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b", " ", t)
    t = re.sub(r"\b\d{1,2}[- ][A-Za-z]{3,9}[- ,]*\d{4}\b|\b[A-Za-z]{3,9}\.? \d{1,2},? \d{4}\b", " ", t)
    cands = [mm for mm in re.finditer(r"(?<![\w-])" + _NUM, t)
             if len(re.sub(r"\D", "", mm.group(1))) >= 3 or mm.group(2)]
    if len(cands) == 1:
        return parse_qty_token(cands[0].group(1) + (cands[0].group(2) or ""))
    return None


# ----------------------------------------------------------------------------- state helpers
def roll_back(d, tools):
    """A non-business day maps to the previous business day."""
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def settled_qty(tools, acc, ins, as_of):
    """All custody sub-accounts, entries dated <= as_of, split-adjusted to as_of."""
    led = tools.get_ledger(acc, ins)
    splits = tools.get_corporate_actions(ins)
    total = 0
    for t in led:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q
    return total


def pending_info(tools, acc, ins, as_of):
    ms = [x for x in tools.get_instructions(acc, ins)
          if x["status"] == "matched" and x["settle_date"] > as_of]
    if not ms:
        return None, None
    return sum(x["qty"] for x in ms), max(x["settle_date"] for x in ms)


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _within(stated, actual):
    if stated == actual:
        return True
    return abs(stated - actual) <= TOLERANCE * max(abs(actual), 1)



def _disambiguate(cands, men, body, ents, request):
    """A partial name that fits several accounts is resolved only when the sender writes
    'our account <name>': then it is the one account the sender is validly entitled to."""
    text = men.get("account_text") or ""
    if not re.search(r"\bour\s+(?:account|acct|a/c|fund)\s+" + re.escape(text), body, re.I):
        return []
    mine = [a for a in cands
            if any(e["account_id"] == a["id"] and e["level"] >= MIN_LEVEL
                   and e["expires"] >= request["sent"] for e in ents)]
    return mine if len(mine) == 1 else []


# ----------------------------------------------------------------------------- main
def _respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    body = _body_lines(request.get("body", ""))
    men = request.get("mentions") or {}
    sender = request["from"].strip().lower()
    dom = sender.split("@")[-1]

    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    def dom_ok(account_id):
        p = tools.get_client_profile(account_id)
        return bool(p) and dom in [d.lower() for d in p["domains"]]

    # 1. sender must be a known contact writing from a domain of an account they are entitled to
    if not contact or not any(dom_ok(e["account_id"]) for e in ents):
        return _resp("REQUEST_AUTHORIZATION")

    # 2. account: a name that fits several accounts needs clarifying unless it is 'our account <name>'
    def valid_ent(e):
        return e["level"] >= MIN_LEVEL and e["expires"] >= request["sent"]

    acc_hits = tools.search_accounts(men["account_text"]) if men.get("account_text") else []
    if len(acc_hits) > 1:
        acc_hits = _disambiguate(acc_hits, men, body, ents, request)
    if len(acc_hits) != 1:
        return _resp("REQUEST_INFO")
    acc = acc_hits[0]["id"]

    # 3. entitlement to that account
    ok = [e for e in ents if e["account_id"] == acc and valid_ent(e)]
    if not ok or not dom_ok(acc):
        return _resp("REQUEST_AUTHORIZATION")

    # 4. instrument and date
    ins_hits = tools.search_instruments(men["instrument_text"]) if men.get("instrument_text") else []
    ins = ins_hits[0]["id"] if len(ins_hits) == 1 else None
    d = parse_date(body, sent)
    if ins is None or d is None or d > sent:
        return _resp("REQUEST_INFO", account_id=acc, instrument_id=ins)

    as_of = roll_back(d, tools).isoformat()
    prof = tools.get_client_profile(acc)
    settled = settled_qty(tools, acc, ins, as_of)
    pend, pend_date = pending_info(tools, acc, ins, as_of)

    # 5. special handling flags
    if prof and prof["legal_hold"]:
        return _resp("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of, settled=settled)

    # 6. nothing held
    if settled == 0:
        return _resp("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of)

    # 7. reconcile the client's own figure against our total (settled + pending)
    stated = parse_stated_qty(body)
    if settled < 0 or (stated is not None and not _within(stated, settled + (pend or 0))):
        return _resp("ESCALATE", account_id=acc, instrument_id=ins, as_of=as_of, settled=settled)

    return _resp("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, settled=settled,
                 pending=pend, pending_date=pend_date)


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _resp("ESCALATE")
