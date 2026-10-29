import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
TOL = 0.10
FREEMAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "proton.me", "protonmail.com"}


def _body_text(req):
    return req.get("body") or ""


def _parse_qty(s):
    s = s.strip().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(k|mm|m)?", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    u = (m.group(2) or "").lower()
    if u == "k":
        v *= 1000
    elif u in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def _client_figure(body):
    m = re.search(r"(?:our figure is|our records show|we show|we have|we count)\s+(-?[\d][\d,\.]*\s?(?:k|mm|m)?)\b(?:\s+(?:units|shares))?", body, re.I)
    if m:
        return _parse_qty(m.group(1))
    return None


def _date_part(body):
    # strip forwarded header and signature to isolate the request sentence
    lines = body.split("\n")
    keep = []
    for l in lines:
        if re.match(r"\s*(From|Date|To|Subject|Sent):", l) or l.startswith("----------"):
            continue
        keep.append(l)
    return "\n".join(keep)


def _parse_date(body, sent):
    t = _date_part(body)
    s = dt.date.fromisoformat(sent)
    low = t.lower()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            if a > 12:
                return dt.date(y, b, a)
            return dt.date(y, a, b)
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})[a-z]*-(\d{4})\b", t)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", t)
    if m and m.group(2)[:3].lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1)
    if re.search(r"month-end|month end|end of (?:the )?month|end of (?:the )?(?:last|previous) month|last (?:business )?day of (?:the )?(?:last|previous) month", low):
        first = s.replace(day=1)
        return first - dt.timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return s
    return None


def _prev_bd(tools, d):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def _resolve_account(tools, text):
    if not text:
        return None, False
    q = text.strip()
    q = re.sub(r"^(?:our\s+)?(?:fund|account|acct|a/c)\s+", "", q, flags=re.I).strip()
    hits = tools.search_accounts(q)
    if not hits and q != text.strip():
        hits = tools.search_accounts(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], False
    if len(hits) > 1:
        return None, True
    return None, False


def _resolve_instrument(tools, text):
    if not text:
        return None
    hits = tools.search_instruments(text.strip())
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def _holdings(tools, acct, inst, as_of):
    iso = as_of.isoformat()
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] <= iso:
            q = t["qty"]
            for sp in splits:
                if t["date"] < sp["date"] <= iso:
                    q *= sp["ratio"]
            total += q
    return total


def _authorized(tools, req, acct):
    email = req["from"].lower()
    sent = req["sent"]
    dom = email.split("@")[-1]
    prof = tools.get_client_profile(acct)
    c = tools.get_contact(email)
    if not prof or not c:
        return False
    if dom not in [d.lower() for d in prof["domains"]]:
        return False
    ok = False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct and e["level"] >= 2 and e["expires"] >= sent:
            ok = True
    return ok


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _respond(request, tools):
    men = request.get("mentions") or {}
    body = _body_text(request)
    acct, ambiguous = _resolve_account(tools, men.get("account_text"))
    inst = _resolve_instrument(tools, men.get("instrument_text"))

    # sender verification
    if acct is None and not ambiguous:
        # account unknown: judge on sender domain only
        dom = request["from"].lower().split("@")[-1]
        c = tools.get_contact(request["from"])
        if dom in FREEMAIL or not c:
            return _out("REQUEST_AUTHORIZATION")
        return _out("REQUEST_INFO")
    if ambiguous:
        return _out("REQUEST_INFO")
    if not _authorized(tools, request, acct):
        return _out("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(acct)
    if prof.get("legal_hold"):
        return _out("ESCALATE", account_id=acct, instrument_id=inst)
    if inst is None:
        return _out("REQUEST_INFO", account_id=acct)
    d = _parse_date(body, request["sent"])
    if d is None:
        return _out("REQUEST_INFO", account_id=acct, instrument_id=inst)
    if d > dt.date.fromisoformat(request["sent"]):
        return _out("REQUEST_INFO", account_id=acct, instrument_id=inst)
    d = _prev_bd(tools, d)
    settled = _holdings(tools, acct, inst, d)
    pend, pdate = None, None
    for x in tools.get_instructions(acct, inst):
        if x["status"] == "matched" and x["settle_date"] > d.isoformat():
            pend = (pend or 0) + x["qty"]
            pdate = max(pdate or "", x["settle_date"])
    if settled == 0:
        return _out("NOT_HELD", account_id=acct, instrument_id=inst, as_of=d.isoformat())
    if settled < 0:
        return _out("ESCALATE", account_id=acct, instrument_id=inst, as_of=d.isoformat(), settled=settled)
    fig = _client_figure(body)
    if fig is not None:
        ok = False
        for base in (settled + (pend or 0),):
            if base == fig or (base > 0 and abs(fig - base) <= TOL * base):
                ok = True
        if not ok:
            return _out("ESCALATE", account_id=acct, instrument_id=inst, as_of=d.isoformat(), settled=settled)
    if settled == 0:
        return _out("NOT_HELD", account_id=acct, instrument_id=inst, as_of=d.isoformat())
    return _out("CONFIRMED", account_id=acct, instrument_id=inst, as_of=d.isoformat(),
                settled=settled, pending=pend, pending_date=pdate)


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _out("REQUEST_INFO")
