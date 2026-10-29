"""Operations-desk procedure: confirm a client's holding of a security.

respond(request, tools) -> dict.  Deterministic, standard library + `tools` only.
"""
import re
import datetime as dt

# ---------------------------------------------------------------- policy knobs
MIN_LEVEL = 2            # entitlement level needed to be told a position
TOLERANCE = 0.10         # relative difference between client's figure and ours that is still "agreeing"
LEGAL_HOLD = "ESCALATE"
NO_EMAIL = None                      # oracle: a no-email-confirm account is still confirmed normally

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
           "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7,
           "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}


# ---------------------------------------------------------------- text helpers
def _clean_body(body):
    lines = body.split("\n")
    if lines and lines[0].lstrip().startswith("----------") and "orwarded" in lines[0]:
        i = 1
        while i < len(lines) and lines[i].strip() != "":
            i += 1
        lines = lines[i + 1:]
    text = "\n".join(lines)
    text = text.replace("This email and any attachments are confidential and intended solely for the addressee.", "")
    return text


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


_CUE = re.compile(r"(?i)(as\s+of|as\s+at|position\s+date|dated?|valuation|balance\s+on|\bon\b)\s*[:\-]?\s*(?:close\s+of\s+business|cob|cob\s+on|the)?\s*$")


def _explicit_dates(text, sent_year):
    """All explicit calendar dates in the text as (position, date)."""
    found = []
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        found.append((m.start(), _mk(int(m[1]), int(m[2]), int(m[3]))))
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", text):
        y = int(m[3])
        y = y + 2000 if y < 100 else y
        found.append((m.start(), _mk(y, int(m[1]), int(m[2]))))          # US month/day/year
    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        found.append((m.start(), _mk(int(m[3]), int(m[2]), int(m[1]))))   # dotted day.month.year
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[-\s]([A-Za-z]{3,9})\.?,?[-\s]+(\d{4})\b", text):
        if m[2].lower() in _MONTHS:
            found.append((m.start(), _mk(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))))
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text):
        if m[1].lower() in _MONTHS:
            found.append((m.start(), _mk(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))))
    return sorted((p, d) for p, d in found if d is not None)


def _parse_date(text, sent):
    """The date the e-mail asks about, as written (before business-day adjustment), or None."""
    sd = dt.date.fromisoformat(sent)
    cands = _explicit_dates(text, sd.year)
    if cands:
        for pos, d in cands:                       # prefer a date introduced by "as of", "position date", ...
            if _CUE.search(text[max(0, pos - 40):pos]):
                return d
        return cands[0][1]
    if re.search(r"(?i)\byesterday\b", text):
        return sd - dt.timedelta(days=1)
    if re.search(r"(?i)(month[- ]?end|\beom\b|end of (the )?(last|previous|prior) month|"
                 r"last (calendar |business |working )?day of (the )?(last|previous|prior) month|"
                 r"end of (the )?month)", text):
        return sd.replace(day=1) - dt.timedelta(days=1)
    if re.search(r"(?i)\b(last|previous|prior) (business|working) day\b", text):
        return "PREV_BDAY"
    if re.search(r"(?i)\b(today|this morning|close of business)\b", text):
        return sd
    return None


_NUM = r"(-?\s?\d[\d,]*(?:\.\d+)?)(?:[ ]?(k|mm|m|million|thousand)\b)?"


def _parse_figure(text):
    """The quantity the client says they hold (None when not stated)."""
    m = re.search(r"(?i)(?:figure\s+(?:is|of)|records\s+show|books\s+show|we\s+show|we\s+have|we\s+see|we\s+hold|"
                  r"balance\s+(?:is|of)|shows?)\s+" + _NUM, text)
    if not m:
        return None
    s = m[1].replace(",", "").replace(" ", "")
    try:
        v = float(s)
    except ValueError:
        return None
    suf = (m[2] or "").lower()
    if suf in ("k", "thousand"):
        v *= 1e3
    elif suf in ("mm", "m", "million"):
        v *= 1e6
    return int(round(v))


# ---------------------------------------------------------------- domain helpers
def _business_day_on_or_before(d, tools):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d
    return dt.date.fromisoformat(c["previous_business_day"])


def _position(tools, acct, inst, as_of):
    """Settled quantity at as_of across all sub-accounts, split-adjusted to the as_of share basis."""
    asof = as_of.isoformat()
    acts = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > asof:
            continue
        q = t["qty"]
        for a in acts:
            if a.get("type") == "split" and a["date"] <= asof and t["date"] < a["date"]:
                q *= a["ratio"]
        total += q
    return total


def _pending(tools, acct, inst, as_of):
    asof = as_of.isoformat()
    xs = [x for x in tools.get_instructions(acct, inst) if x["status"] == "matched" and x["settle_date"] > asof]
    if not xs:
        return None, None
    return sum(x["qty"] for x in xs), max(x["settle_date"] for x in xs)


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- the procedure
def _respond(request, tools):
    sent = request["sent"]
    body = _clean_body(request.get("body", ""))
    ment = request.get("mentions") or {}
    sender = request["from"].strip().lower()
    domain = sender.split("@")[-1]

    # ---- who is asking
    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # ---- which account / instrument
    at = (ment.get("account_text") or "").strip()
    it = (ment.get("instrument_text") or "").strip()
    cands = [a["id"] for a in tools.search_accounts(at)] if at else []
    insts = [i["id"] for i in tools.search_instruments(it)] if it else []

    def domains_of(acct):
        prof = tools.get_client_profile(acct)
        return [d.lower() for d in prof["domains"]] if prof else []

    def entitled(acct):
        for e in ents:
            if e["account_id"] == acct and e["expires"] >= sent and e["level"] >= MIN_LEVEL:
                return True
        return False

    # ---- sender verification comes first: nothing is disclosed to an unverified sender
    if contact is None:
        return _blank("REQUEST_AUTHORIZATION")
    if not any(domain in domains_of(e["account_id"]) for e in ents):
        return _blank("REQUEST_AUTHORIZATION")          # e.g. free-mail address, not a registered client domain
    # ---- account must be identified before entitlement can be tested
    if len(cands) == 1:
        if not (entitled(cands[0]) and domain in domains_of(cands[0])):
            return _blank("REQUEST_AUTHORIZATION")

    acct = cands[0] if len(cands) == 1 else None
    inst = insts[0] if len(insts) == 1 else None

    # ---- date
    d = _parse_date(body, sent)
    kind_assumed = False

    # ---- anything missing or ambiguous -> ask
    if acct is None or inst is None or d is None:
        return _blank("REQUEST_INFO", account_id=acct, instrument_id=inst)
    sd = dt.date.fromisoformat(sent)
    if d == "PREV_BDAY":
        d = dt.date.fromisoformat(tools.get_calendar(sent)["previous_business_day"])
    if d > sd:
        return _blank("REQUEST_INFO", account_id=acct, instrument_id=inst)

    as_of = _business_day_on_or_before(d, tools)
    prof = tools.get_client_profile(acct)

    settled = _position(tools, acct, inst, as_of)
    pend, pend_date = _pending(tools, acct, inst, as_of)
    fields = dict(account_id=acct, instrument_id=inst, as_of=as_of.isoformat(),
                  as_of_assumed=kind_assumed, settled=settled)

    if prof and prof.get("legal_hold"):
        return _blank(LEGAL_HOLD, **fields)
    if NO_EMAIL and prof and prof.get("no_email_confirm"):
        return _blank(NO_EMAIL, **fields)

    # ---- nothing settled at that date: say so (even if the client believes otherwise)
    if settled == 0:
        return _blank("NOT_HELD", account_id=acct, instrument_id=inst, as_of=as_of.isoformat(),
                      as_of_assumed=kind_assumed)

    # ---- does the client's own figure agree with ours?
    stated = _parse_figure(body)
    if stated is not None:
        # the client's figure is what they believe they hold including matched-but-unsettled trades
        o = settled + (pend or 0)
        if o == 0:
            ok = stated == 0
        else:
            ok = abs(stated - o) / abs(o) <= TOLERANCE + 1e-9
        if not ok:
            return _blank("ESCALATE", **fields)

    return _blank("CONFIRMED", pending=pend, pending_date=pend_date, **fields)


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:                      # never crash on an unforeseen e-mail: hand it to a human
        return _blank("ESCALATE")
