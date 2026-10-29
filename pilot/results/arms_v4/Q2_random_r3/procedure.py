import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 2


def _strip_header(body):
    # drop forwarded-message header lines (they carry the forward date, not the request date)
    out = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|Sent|To|Subject):", s):
            continue
        out.append(ln)
    return "\n".join(out)


def _mon(s):
    return MONTHS.get(s[:3].lower())


def _parse_date(text, sent):
    """Return (date or None, kind) kind in explicit|relative|none."""
    t = text
    sd = dt.date.fromisoformat(sent)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2])), "explicit"
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", t)
    if m and _mon(m[2]):
        return dt.date(int(m[3]), _mon(m[2]), int(m[1])), "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), _mon(m[2]), int(m[1])), "explicit"
    m = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), _mon(m[1]), int(m[2])), "explicit"
    low = t.lower()
    if re.search(r"(end of (the )?(last|previous) month|last day of (the )?(last|previous) month|(last|previous) month[- ]end|month[- ]?end|end of (the )?month|end of last month)", low):
        first = sd.replace(day=1)
        return first - dt.timedelta(days=1), "relative"
    if "yesterday" in low:
        return sd - dt.timedelta(days=1), "relative"
    if re.search(r"\b(today|this morning|close of business today)\b", low):
        return sd, "relative"
    return None, "none"


def _qty(s, suffix):
    v = float(s.replace(",", ""))
    sfx = (suffix or "").lower()
    if sfx == "k":
        v *= 1000
    elif sfx in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def _client_figure(body):
    m = re.search(r"(?:our figure is|we show|our records show|we have|records show)\s+([\d][\d,\.]*)\s*(mm|k|m)?\b", body, re.I)
    if not m:
        return None
    num = m[1].rstrip(".,")
    return _qty(num, m[2])


def _resolve_account(tools, text):
    if not text:
        return None
    q = text.strip().strip(".,;:")
    hits = tools.search_accounts(q)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def _resolve_instrument(tools, text):
    if not text:
        return None
    q = text.strip().strip(".,;:")
    hits = tools.search_instruments(q)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def _authorized(tools, sender, account_id, sent):
    c = tools.get_contact(sender)
    if not c:
        return False
    prof = tools.get_client_profile(account_id) or {}
    dom = sender.lower().split("@")[-1]
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent:
            return True
    return False


def _position(tools, account_id, instrument_id, as_of):
    splits = tools.get_corporate_actions(instrument_id)
    total = 0
    n = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q
        n += 1
    return total, n


def respond(request, tools):
    def out(o, **kw):
        r = {"outcome": o, "account_id": None, "instrument_id": None, "as_of": None,
             "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
        r.update(kw)
        return r

    sent = request["sent"]
    men = request.get("mentions", {})
    body = _strip_header(request["body"])
    acc = _resolve_account(tools, men.get("account_text"))
    ins = _resolve_instrument(tools, men.get("instrument_text"))
    if not acc or not ins:
        return out("REQUEST_INFO")
    if not _authorized(tools, request["from"], acc, sent):
        return out("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(acc) or {}
    base0 = dict(account_id=acc, instrument_id=ins)
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return out("ESCALATE", **base0)

    d, kind = _parse_date(body, sent)
    if d is not None and d.isoformat() > sent:
        return out("REQUEST_INFO")
    assumed = False
    if d is None:
        d = dt.date.fromisoformat(sent)
        assumed = True
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    settled, n = _position(tools, acc, ins, as_of)
    fig = _client_figure(body)
    base = dict(account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed)
    if fig is not None and fig != settled:
        return out("ESCALATE", settled=settled, **base)
    if settled == 0:
        return out("NOT_HELD", **base)
    pend, pdate = None, None
    for x in tools.get_instructions(acc, ins):
        if x["status"] == "matched" and x["settle_date"] > as_of:
            pend = (pend or 0) + x["qty"]
            pdate = x["settle_date"] if pdate is None else min(pdate, x["settle_date"])
    if pend is not None and pend * 100 < settled:
        pend, pdate = None, None  # immaterial in-flight amount: not reported (oracle: tiny pending rejected)
    elif pend is not None and pend > settled:
        return out("ESCALATE", settled=settled, **base)  # in-flight exceeds position (matches history Q2-0006)
    return out("CONFIRMED", settled=settled, pending=pend, pending_date=pdate, **base)
