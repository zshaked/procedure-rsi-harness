import re, datetime as dt

MON = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONFULL = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
           "september": 9, "october": 10, "november": 11, "december": 12}
D = dt.date


def _body(request):
    b = request.get("body", "")
    return b


def parse_sent(request):
    return D.fromisoformat(request["sent"][:10])


def parse_date(body, sent):
    """Return (date or None, kind). kind: 'explicit','relative', None"""
    b = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    # skip forwarded-header Date: line
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", b):
        pre = b[max(0, m.start() - 8):m.start()]
        if re.search(r"Date:\s*$", pre):
            continue
        try:
            return D(int(m.group(1)), int(m.group(2)), int(m.group(3))), "explicit"
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        a, c, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return D(y, a, c), "explicit"
        except ValueError:
            try:
                return D(y, c, a), "explicit"
            except ValueError:
                pass
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ](\d{4})\b", b)
    if m and m.group(2).lower() in MON:
        return D(int(m.group(3)), MON[m.group(2).lower()], int(m.group(1))), "explicit"
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})\b", b)
    if m:
        k = m.group(1).lower()
        mo = MONFULL.get(k) or MON.get(k[:3])
        if mo:
            return D(int(m.group(3)), mo, int(m.group(2))), "explicit"
    low = b.lower()
    if re.search(r"end of last month|last day of last month|month[- ]end|end of the month|last day of the month", low):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1), "relative"
    if "yesterday" in low:
        return sent - dt.timedelta(days=1), "relative"
    if "today" in low:
        return sent, "relative"
    return None, None


def parse_qty(body):
    m = re.search(r"(?:figure is|have|show|records show|reference[^0-9\-]*?)\s*(-?[\d][\d,\.]*)(k|mm)?\b", body, re.I)
    if not m:
        return None
    s = m.group(1).replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    if suf == "k":
        v *= 1000
    elif suf in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def prev_bd(tools, d):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d
    return D.fromisoformat(c["previous_business_day"])


def respond(request, tools):
    men = request.get("mentions", {})
    sender = request["from"].strip().lower()
    sent = parse_sent(request)
    at, it = men.get("account_text"), men.get("instrument_text")

    def base(outcome, **kw):
        r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
             "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
        r.update(kw)
        return r

    accs = tools.search_accounts(at) if at else []
    insts = tools.search_instruments(it) if it else []
    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    domain = sender.split("@")[-1]

    # ambiguity / unresolved
    if len(accs) > 1 or len(insts) > 1:
        return base("REQUEST_INFO")
    acc = accs[0]["id"] if accs else None
    inst = insts[0]["id"] if insts else None

    # authorization
    if acc is None:
        okd = any(e["level"] >= 2 and e["expires"] >= sent.isoformat() and
                  domain in [x.lower() for x in (tools.get_client_profile(e["account_id"]) or {}).get("domains", [])]
                  for e in ents)
        return base("REQUEST_INFO" if okd else "REQUEST_AUTHORIZATION")
    prof = tools.get_client_profile(acc) or {}
    ok_dom = domain in [d.lower() for d in prof.get("domains", [])]
    ok_ent = any(e["account_id"] == acc and e["level"] >= 2 and e["expires"] >= sent.isoformat() for e in ents)
    if not (ok_dom and ok_ent):
        return base("REQUEST_AUTHORIZATION")
    if prof.get("legal_hold"):
        return base("ESCALATE", account_id=acc, instrument_id=inst)
    if inst is None:
        return base("REQUEST_INFO")
    d, kind = parse_date(request["body"], sent)
    if d is None:
        return base("REQUEST_INFO", account_id=acc, instrument_id=inst)
    if d > sent:
        return base("REQUEST_INFO", account_id=acc, instrument_id=inst)
    asof = prev_bd(tools, d)
    iso = asof.isoformat()
    led = tools.get_ledger(acc, inst)
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in led:
        if t["date"] <= iso:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= iso:
                    q *= s["ratio"]
            total += q
    ins = tools.get_instructions(acc, inst)
    pend = [x for x in ins if x["status"] == "matched" and x["settle_date"] > iso]
    pq = sum(x["qty"] for x in pend)
    pd_ = max(x["settle_date"] for x in pend) if pend else None
    claimed = parse_qty(request["body"])
    if total == 0 and not pend:
        return base("NOT_HELD", account_id=acc, instrument_id=inst, as_of=iso)
    def near(x, y):
        return abs(x - y) <= 0.10 * max(abs(y), 1)
    if claimed is not None and not (near(claimed, total) or near(claimed, total + pq)):
        return base("ESCALATE", account_id=acc, instrument_id=inst)
    return base("CONFIRMED", account_id=acc, instrument_id=inst, as_of=iso, settled=total,
                pending=pq or None, pending_date=pd_)
