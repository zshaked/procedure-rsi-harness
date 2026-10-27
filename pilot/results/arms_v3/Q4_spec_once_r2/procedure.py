"""Holding-confirmation desk procedure (implements spec.md)."""
import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
TOLERANCE = 0.10


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_body(body):
    out, in_hdr = [], False
    for line in (body or "").split("\n"):
        s = line.strip()
        if s.startswith("---------- Forwarded"):
            in_hdr = True
            continue
        if in_hdr and re.match(r"(From|Date|Subject|To|Cc):", s):
            continue
        in_hdr = False
        if s.startswith("This email and any attachments"):
            continue
        out.append(line)
    return "\n".join(out)


def _mk(y, m, d):
    try:
        if y < 100:
            y += 2000
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month(s):
    return MONTHS.get(s.lower()[:3]) if s and s.lower()[:3] in MONTHS else None


def _last_of_month(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _parse_date(text, sent):
    """Returns (date or None, found_flag)."""
    t = text
    tl = t.lower()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", t)
    if m:  # US order (M/D/Y)
        d = _mk(int(m[3]), int(m[1]), int(m[2]))
        if d is None:
            d = _mk(int(m[3]), int(m[2]), int(m[1]))
        return d, True
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})\.?[- ,]+(\d{4})\b", t)
    if m and _month(m[2]):
        return _mk(int(m[3]), _month(m[2]), int(m[1])), True
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m and _month(m[1]):
        return _mk(int(m[3]), _month(m[1]), int(m[2])), True
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th) (?:of )?([A-Za-z]{3,9}),? (\d{4})\b", t)
    if m and _month(m[2]):
        return _mk(int(m[3]), _month(m[2]), int(m[1])), True
    if re.search(r"\byesterday\b", tl):
        return sent - dt.timedelta(days=1), True
    if re.search(r"\btoday\b", tl):
        return sent, True
    m = re.search(r"\bend of (january|february|march|april|may|june|july|august|september|"
                  r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
                  r"\b(?:,? (\d{4}))?", tl)
    if m:
        mo = _month(m[1])
        y = int(m[2]) if m[2] else (sent.year if mo <= sent.month else sent.year - 1)
        return _last_of_month(y, mo), True
    if re.search(r"month[- ]?end|end of (?:the )?(?:last|previous|prior) month|"
                 r"last day of (?:the )?(?:last|previous|prior) month|end of the month|"
                 r"end of month", tl):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1), True
    return None, False


def _to_num(s):
    s = s.strip().replace(",", "")
    mult = 1
    sl = s.lower()
    if sl.endswith("mm"):
        mult, s = 10 ** 6, s[:-2]
    elif sl.endswith("m"):
        mult, s = 10 ** 6, s[:-1]
    elif sl.endswith("k"):
        mult, s = 1000, s[:-1]
    return int(round(float(s.strip()) * mult))


_NUM = r"(-?\d[\d,]*(?:\.\d+)?(?: ?(?:k|K|mm|MM|m|M)\b)?)"


def _parse_qty(text):
    pats = [r"our records show\s+" + _NUM, r"our figure is\s+" + _NUM, r"we show\s+" + _NUM,
            r"we have\s+" + _NUM + r"\s*(?:shares|units)", r"our books show\s+" + _NUM,
            r"we hold\s+" + _NUM]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            try:
                return _to_num(m.group(1))
            except ValueError:
                return None
    return None


def _roll(tools, d):
    c = tools.get_calendar(d.isoformat())
    return d if c["business_day"] else dt.date.fromisoformat(c["previous_business_day"])


def _settled(tools, acc, ins, as_of):
    splits = [s for s in tools.get_corporate_actions(ins) if s.get("type") == "split"]
    tot = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            tot += q
    return tot


def _close(a, b):
    if b == 0:
        return a == 0
    return abs(a - b) <= TOLERANCE * abs(b)


def respond(request, tools):
    sender = (request.get("from") or "").strip().lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    sent = dt.date.fromisoformat(request["sent"][:10])
    mentions = request.get("mentions") or {}
    body = _clean_body(request.get("body") or "")
    acc_text = (mentions.get("account_text") or "").strip()
    ins_text = (mentions.get("instrument_text") or "").strip()

    contact = tools.get_contact(sender) if sender else None
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # 1. Account identification
    if not acc_text:
        m = re.search(r"\b(ACC-\d+|SA-\d+)\b", body)
        acc_text = m.group(1) if m else ""
    if not acc_text:
        known = False
        for e in ents:
            p = tools.get_client_profile(e["account_id"])
            if p and domain in [x.lower() for x in p["domains"]]:
                known = True
        return _blank("REQUEST_INFO" if known else "REQUEST_AUTHORIZATION")
    accs = tools.search_accounts(acc_text)
    if len(accs) != 1:
        return _blank("REQUEST_INFO")
    acc = accs[0]["id"]

    # 2-3. Authorization
    prof = tools.get_client_profile(acc) or {"domains": [], "legal_hold": False}
    if domain not in [x.lower() for x in prof.get("domains", [])]:
        return _blank("REQUEST_AUTHORIZATION")
    ok = any(e["account_id"] == acc and e["level"] >= 2 and e["expires"] >= sent.isoformat()
             for e in ents)
    if not ok:
        return _blank("REQUEST_AUTHORIZATION")

    # 4. Legal hold
    if prof.get("legal_hold"):
        ins_id = None
        if ins_text:
            hits = tools.search_instruments(ins_text)
            ins_id = hits[0]["id"] if len(hits) == 1 else None
        return _blank("ESCALATE", account_id=acc, instrument_id=ins_id)

    # 5. Instrument and date completeness
    if not ins_text:
        m = re.search(r"\b([A-Z]{2}\d{9}[0-9A-Z])\b", body)
        ins_text = m.group(1) if m else ""
    if not ins_text:
        return _blank("REQUEST_INFO")
    hits = tools.search_instruments(ins_text)
    if len(hits) != 1:
        return _blank("REQUEST_INFO")
    ins = hits[0]["id"]

    req_date, _ = _parse_date(body, sent)
    if req_date is None:
        return _blank("REQUEST_INFO")
    if req_date > sent:
        return _blank("REQUEST_INFO")

    # 6-8. Figures
    as_of = _roll(tools, req_date).isoformat()
    s = _settled(tools, acc, ins, as_of)
    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    p = sum(x["qty"] for x in pend)
    p_date = max((x["settle_date"] for x in pend), default=None)

    # 9. Not held
    if s == 0:
        return _blank("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of)

    # 10. Reconciliation
    claim = _parse_qty(body)
    if claim is not None and not (_close(claim, s) or (p and _close(claim, s + p))):
        return _blank("ESCALATE", account_id=acc, instrument_id=ins)

    out = _blank("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, settled=s)
    if p:
        out["pending"] = p
        out["pending_date"] = p_date
    return out
