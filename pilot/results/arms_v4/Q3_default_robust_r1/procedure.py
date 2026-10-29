import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
NUM = r"-?\d[\d,]*(?:\.\d+)?\s*(?:mm|m|k)?"

# tunables (decided from histories / oracle)
PENDING_WINDOW_DAYS = 28
LARGE_POSITION = 1_000_000


def _clean_body(body):
    lines = []
    for ln in body.split("\n"):
        s = ln.strip()
        if re.match(r"^(from|date|to|sent|subject):", s, re.I) or s.startswith("-----"):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _parse_date(text, sent):
    """Return (date or None, kind) kind in {'explicit','relative',None}."""
    t = text
    tl = t.lower()
    if re.search(r"\b(?:end|last day|last business day)\s+of\s+(?:the\s+)?last\s+month\b|\bmonth[- ]end\b|\bend of (?:the )?month\b|\blast day of (?:the )?(?:last|previous) month\b|\bend of (?:the )?previous month\b", tl):
        return _last_day_prev_month(sent), "relative"
    if re.search(r"\byesterday\b", tl):
        return sent - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", tl):
        return sent, "relative"
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        try:
            return dt.date(int(m[3]), int(m[1]), int(m[2])), "explicit"
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[- ]" + MON_RE + r",?[- ](\d{4})\b", tl)
    if m:
        try:
            return dt.date(int(m[3]), MONTHS[m[2]], int(m[1])), "explicit"
        except ValueError:
            pass
    m = re.search(r"\b" + MON_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", tl)
    if m:
        try:
            return dt.date(int(m[3]), MONTHS[m[1]], int(m[2])), "explicit"
        except ValueError:
            pass
    return None, None


def _to_int(tok):
    tok = tok.strip().lower().replace(",", "")
    mult = 1
    if tok.endswith("mm"):
        mult, tok = 1_000_000, tok[:-2]
    elif tok.endswith("m"):
        mult, tok = 1_000_000, tok[:-1]
    elif tok.endswith("k"):
        mult, tok = 1_000, tok[:-1]
    try:
        return int(round(float(tok.strip()) * mult))
    except ValueError:
        return None


def _claimed(text):
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):
        sl = sent.lower()
        if re.search(r"records show|we show|figure is|on our books|we have\b.*\d|our books", sl) and not re.search(r"please|confirm holdings|could you|can you|requesting", sl.split("we ")[0] if False else ""):
            if re.search(r"(records show|we show|figure is|we have)", sl):
                m = re.search(r"(?:records show|we show|figure is|we have)\s*(" + NUM + r")", sl)
                if m:
                    v = _to_int(m[1])
                    if v is not None:
                        return v
    return None


def _business(tools, d):
    c = tools.get_calendar(d.isoformat())
    return c["business_day"], dt.date.fromisoformat(c["previous_business_day"])


def _resolve_instrument(tools, txt):
    if not txt:
        return None, "none"
    hits = tools.search_instruments(txt)
    ids = {h["id"] for h in hits}
    if len(ids) == 1:
        return hits[0]["id"], "ok"
    return None, ("ambiguous" if ids else "unknown")


def _resolve_account(tools, txt):
    if not txt:
        return None, "none"
    hits = tools.search_accounts(txt)
    ids = {h["id"] for h in hits}
    if len(ids) == 1:
        return hits[0]["id"], "ok"
    return None, ("ambiguous" if ids else "unknown")


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    m = request.get("mentions") or {}
    body = _clean_body(request.get("body", ""))
    text = request.get("subject", "") + "\n" + body

    acct, ast = _resolve_account(tools, m.get("account_text"))
    contact = tools.get_contact(request["from"])
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    valid = [e for e in ents if e["expires"] >= sent.isoformat()]
    if ast == "none":
        # "our fund": infer from sender's single valid entitlement
        accs = {e["account_id"] for e in valid}
        if len(accs) == 1:
            acct, ast = next(iter(accs)), "ok"
    if ast != "ok":
        return _out("REQUEST_INFO")

    ok_auth = any(e["account_id"] == acct and e["level"] >= 3 for e in valid)
    prof = tools.get_client_profile(acct) or {}
    if not ok_auth:
        return _out("REQUEST_AUTHORIZATION")

    inst, ist = _resolve_instrument(tools, m.get("instrument_text"))
    if ist != "ok":
        return _out("REQUEST_INFO")

    d, kind = _parse_date(body, sent)
    assumed = False
    if d is None:
        if prof.get("no_email_confirm"):
            return _out("REQUEST_INFO")
        d, assumed = sent, True
    if d > sent:
        return _out("REQUEST_INFO")
    isbiz, prev = _business(tools, d)
    if not isbiz:
        return _out("REQUEST_INFO")
    as_of = d.isoformat()
    if prof.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")

    splits = tools.get_corporate_actions(inst)
    settled = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if s["date"] <= as_of and t["date"] < s["date"]:
                    q *= s["ratio"]
            settled += q

    if prof.get("legal_hold"):
        return _out("ESCALATE", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed, settled=settled)

    if settled == 0:
        return _out("NOT_HELD", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed)

    ins = tools.get_instructions(acct, inst)
    matched = [x for x in ins if x["status"] == "matched" and x["settle_date"] > as_of]
    claim = _claimed(body)
    if claim is not None and claim != settled and claim != settled + sum(x["qty"] for x in matched):
        return _out("ESCALATE", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed, settled=settled)

    if settled >= LARGE_POSITION:
        return _out("ESCALATE", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed, settled=settled)

    pend, pdate = None, None
    cands = [x for x in matched if x["settle_date"] <= (sent + dt.timedelta(days=PENDING_WINDOW_DAYS)).isoformat()]
    if cands:
        cands.sort(key=lambda x: x["settle_date"])
        pdate = cands[0]["settle_date"]
        pend = sum(x["qty"] for x in cands if x["settle_date"] == pdate)
    return _out("CONFIRMED", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
                settled=settled, pending=pend, pending_date=pdate)
