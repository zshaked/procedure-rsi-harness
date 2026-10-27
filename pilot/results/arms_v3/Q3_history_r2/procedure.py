"""Induced procedure for the position-confirmation desk (history-only arm)."""
import datetime as dt
import re

RECORDS_START = "2025-12-15"   # earliest date in the system of record
PENDING_WINDOW_DAYS = 60       # matched instructions settling after as_of and within ~2 months of the email

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _strip_body(body):
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if re.match(r"^(from|date|sent|to|subject):", s, re.I):
            continue
        if s.startswith("----------"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _month(tok):
    return MONTHS.get(tok[:3].lower())


def _last_of_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Return (date|None, found_phrase: bool)."""
    t = text
    low = t.lower()
    cands = []
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        cands.append((m.start(), (int(m.group(1)), int(m.group(2)), int(m.group(3)))))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t):
        cands.append((m.start(), (int(m.group(3)), int(m.group(1)), int(m.group(2)))))
    for m in re.finditer(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})\.?[- ,]+(\d{4})\b", t):
        mo = _month(m.group(2))
        if mo:
            cands.append((m.start(), (int(m.group(3)), mo, int(m.group(1)))))
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t):
        mo = _month(m.group(1))
        if mo:
            cands.append((m.start(), (int(m.group(3)), mo, int(m.group(2)))))
    cands.sort()
    for _, (y, mo, d) in cands:
        try:
            return dt.date(y, mo, d), True
        except ValueError:
            return None, True  # a date was given but is invalid
    if re.search(r"\b(end of last month|last day of (the )?(last|previous|prior) month|"
                 r"month[- ]end|end of (the )?(previous|prior) month|last month[- ]end)\b", low):
        return _last_of_prev_month(sent), True
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\b(today|this morning|current(ly)?|as of now|latest)\b", low):
        return sent, True
    return None, False


def parse_qty(s):
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*(mm|m|k)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"mm": 1_000_000, "m": 1_000_000, "k": 1_000, None: 1}[m.group(2)]
    return int(round(v * mult))


def client_figure(text):
    num = r"(-?\d[\d,]*(?:\.\d+)?\s*(?:mm|m|k)?)\b"
    pats = [r"our figure is\s+" + num,
            r"we have\s+" + num + r"\s*(?:shares|units)?",
            r"we show\s+" + num,
            r"our (?:records|books) show\s+" + num,
            r"we hold\s+" + num,
            r"on our books[^\d-]{0,20}" + num]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            q = parse_qty(m.group(1))
            if q is not None:
                return q
    return None


def _resolve_account(req, tools, contact):
    text = (req.get("mentions") or {}).get("account_text")
    if text and text.strip():
        hits = tools.search_accounts(text)
        if len(hits) == 1:
            return hits[0]["id"], None
        return None, "REQUEST_INFO"
    # no account named: infer from the sender's entitlements if unique
    if contact:
        ids = sorted({e["account_id"] for e in tools.get_entitlements(contact["contact_id"])})
        if len(ids) == 1:
            return ids[0], None
    return None, "REQUEST_INFO"


def _authorized(tools, contact, account_id, sent):
    if not contact:
        return False
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= 3 and (e.get("expires") or "9999") >= sent:
            return True
    return False


def _settled(tools, account_id, instrument_id, as_of):
    splits = tools.get_corporate_actions(instrument_id)
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s.get("type") == "split" and t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        total += q
    return total


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"][:10])
    sent_s = sent.isoformat()
    body = _strip_body(request.get("body", ""))
    contact = tools.get_contact(request.get("from", "") or "")

    account_id, err = _resolve_account(request, tools, contact)
    if err:
        return _out(err)

    if not _authorized(tools, contact, account_id, sent_s):
        return _out("REQUEST_AUTHORIZATION")

    itext = (request.get("mentions") or {}).get("instrument_text")
    if not itext or not itext.strip():
        return _out("REQUEST_INFO")
    ihits = tools.search_instruments(itext)
    if len(ihits) != 1:
        return _out("REQUEST_INFO")
    instrument_id = ihits[0]["id"]

    d, found = parse_date(body, sent)
    if found and d is None:
        return _out("REQUEST_INFO")
    assumed = d is None
    if assumed:
        d = sent
    if d > sent:
        return _out("REQUEST_INFO")
    as_of = d.isoformat()
    cal = tools.get_calendar(as_of)
    if not cal["business_day"]:
        as_of = cal["previous_business_day"]

    profile = tools.get_client_profile(account_id) or {}
    if profile.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    esc = _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    if profile.get("legal_hold"):
        return esc
    if as_of < RECORDS_START:
        return esc

    settled = _settled(tools, account_id, instrument_id, as_of)
    if settled < 0:
        return esc
    matched_after = [x for x in tools.get_instructions(account_id, instrument_id)
                     if x["status"] == "matched" and x["settle_date"] > as_of]
    limit = (sent + dt.timedelta(days=PENDING_WINDOW_DAYS)).isoformat()
    pend = [x for x in matched_after if x["settle_date"] <= limit]
    fig = client_figure(body)
    if fig is not None and fig != settled:
        # a client figure that includes matched-but-unsettled trades is explained, not a break
        if not pend or fig != settled + sum(x["qty"] for x in pend):
            if fig != settled + sum(x["qty"] for x in matched_after) or not matched_after:
                return esc
            pend = matched_after

    if settled == 0:
        return _out("NOT_HELD", account_id=account_id, instrument_id=instrument_id,
                    as_of=as_of, as_of_assumed=assumed)

    res = _out("CONFIRMED", account_id=account_id, instrument_id=instrument_id,
               as_of=as_of, as_of_assumed=assumed, settled=settled)
    if pend:
        res["pending"] = sum(x["qty"] for x in pend)
        res["pending_date"] = max(x["settle_date"] for x in pend)
    return res
