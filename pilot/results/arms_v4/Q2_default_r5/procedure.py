import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _clean_body(body):
    out = []
    for ln in body.split("\n"):
        s = ln.strip()
        if re.match(r"(?i)^(from|date|sent|to|cc|subject)\s*:", s):
            continue
        if s.startswith("----------"):
            continue
        if re.search(r"(?i)confidential and intended solely", s):
            continue
        out.append(s)
    return "\n".join(out)


def _mon(s):
    return MONTHS.get(s[:3].lower())


def _parse_date(text, sent):
    """Return (date or None, found: bool). found=True when a date expression is present."""
    t = text
    sent_d = dt.date.fromisoformat(sent[:10])
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2])), True
    m = re.search(r"\b(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]*(\d{4})\b", t)
    if m and _mon(m[2]):
        return dt.date(int(m[3]), _mon(m[2]), int(m[1])), True
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m and _mon(m[1]):
        return dt.date(int(m[3]), _mon(m[1]), int(m[2])), True
    if re.search(r"(?i)(end of (the )?last month|last day of (the )?last month|end of (the )?previous month|"
                 r"last day of (the )?previous month|month[- ]end|end of month)", t):
        return sent_d.replace(day=1) - dt.timedelta(days=1), True
    if re.search(r"(?i)\byesterday\b", t):
        return sent_d - dt.timedelta(days=1), True
    if re.search(r"(?i)\btoday\b", t):
        return sent_d, True
    return None, False


def _qty(s):
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mm|m|k)?$", s)
    if not m:
        return None
    v = float(m[1])
    mult = {"k": 1e3, "m": 1e6, "mm": 1e6}.get(m[2], 1)
    return int(round(v * mult))


def _stated(text):
    m = re.search(r"(?i)(?:figure is|we show|we have|records show|books show|we hold|our figure|show)\s*:?\s*"
                  r"(\d[\d,]*(?:\.\d+)?\s*(?:mm|k|m)?)\b(?!-)", text)
    if m:
        raw = m[1].strip().lower().replace(",", "")
        v = _qty(raw)
        if v is None:
            return None
        mm = re.match(r"^(\d+)(?:\.(\d+))?\s*(mm|m|k)?$", raw)
        tol = 0
        if mm and mm[3]:
            unit = {"k": 1e3, "m": 1e6, "mm": 1e6}[mm[3]]
            tol = 0.5 * unit / (10 ** len(mm[2] or ""))
        return (v, tol)
    return None


def _matches(stated, ours):
    val, tol = stated
    return abs(val - ours) <= tol


def _prev_bd(tools, d):
    return dt.date.fromisoformat(tools.get_calendar(d.isoformat())["previous_business_day"])


def _is_bd(tools, d):
    return tools.get_calendar(d.isoformat())["business_day"]


def _resolve_account(tools, text):
    if not text:
        return None, "none"
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    return None, ("none" if not hits else "ambiguous")


def _resolve_instrument(tools, text):
    if not text:
        return None, "none"
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    return None, ("none" if not hits else "ambiguous")


def _authorized(tools, sender, sent, acct):
    email = sender.strip().lower()
    c = tools.get_contact(email)
    if not c:
        return False
    prof = tools.get_client_profile(acct) or {}
    dom = email.split("@")[-1]
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct and e["level"] >= 2 and e["expires"] >= sent[:10]:
            return True
    return False


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    m = request.get("mentions") or {}
    sent = request["sent"][:10]
    body = _clean_body(request["body"])
    acct, ast = _resolve_account(tools, m.get("account_text"))
    inst, ist = _resolve_instrument(tools, m.get("instrument_text"))
    if acct is None or inst is None:
        return _out("REQUEST_INFO")
    if not _authorized(tools, request["from"], sent, acct):
        return _out("REQUEST_AUTHORIZATION")
    prof = tools.get_client_profile(acct) or {}
    base = dict(account_id=acct, instrument_id=inst)
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", **base)

    d, found = _parse_date(body, sent)
    assumed = not found
    if not found:
        d = dt.date.fromisoformat(sent)
    if d > dt.date.fromisoformat(sent):
        return _out("REQUEST_INFO")
    if not _is_bd(tools, d):
        d = _prev_bd(tools, d)
    iso = d.isoformat()

    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= iso and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q

    pend = [x for x in tools.get_instructions(acct, inst)
            if x["status"] == "matched" and x["settle_date"] > iso]
    pending = pending_date = None
    if pend:
        pending = sum(x["qty"] for x in pend)
        pending_date = max(x["settle_date"] for x in pend)

    if total == 0:
        return _out("NOT_HELD", as_of=iso, as_of_assumed=assumed, **base)
    stated = _stated(body)
    if stated is not None and not _matches(stated, total + (pending or 0)):
        return _out("ESCALATE", settled=total, as_of=iso, as_of_assumed=assumed, **base)
    return _out("CONFIRMED", as_of=iso, as_of_assumed=assumed, settled=total,
                pending=pending, pending_date=pending_date, **base)
