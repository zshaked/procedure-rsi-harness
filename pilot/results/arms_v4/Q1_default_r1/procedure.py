import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WD = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+"


def _strip_forward(body):
    lines = []
    for ln in body.split("\n"):
        if re.match(r"\s*(from|date|sent|to|subject)\s*:", ln, re.I) or ln.startswith("-----"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(body, sent):
    """Returns (date|None, found_phrase: bool)."""
    t = _strip_forward(body)
    s = dt.date.fromisoformat(sent)
    low = t.lower()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), True
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _mk(int(m[3]), int(m[1]), int(m[2])), True
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]+(\d{4})\b", t)
    if m and m[2].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2].lower()], int(m[1])), True
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})\b", t)
    if m and m[1].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1].lower()], int(m[2])), True
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), True
    if re.search(r"month[- ]end|end of last month|last day of (?:last|the previous) month|end of (?:the )?month", low):
        return s.replace(day=1) - dt.timedelta(days=1), True
    return None, False


def respond(request, tools):
    body = request.get("body", "")
    sent = request["sent"]
    men = request.get("mentions") or {}
    out = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
           "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def info(acc=None, ins=None, as_of=None):
        out.update(outcome="REQUEST_INFO", account_id=acc, instrument_id=ins, as_of=as_of,
                   settled=None, pending=None, pending_date=None)
        return out

    # --- resolve account
    acc = None
    at = men.get("account_text")
    if at:
        hits = tools.search_accounts(at)
        if len(hits) == 1:
            acc = hits[0]["id"]
    if not acc:
        return info()

    # --- authorization
    ok = False
    contact = tools.get_contact(request["from"])
    prof = tools.get_client_profile(acc) or {}
    dom = request["from"].lower().split("@")[-1]
    if contact and dom in [d.lower() for d in prof.get("domains", [])]:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= 3 and e["expires"] >= sent:
                ok = True
    if not ok:
        out["outcome"] = "REQUEST_AUTHORIZATION"
        return out

    # --- instrument
    ins = None
    it = men.get("instrument_text")
    if it:
        h = tools.search_instruments(it)
        if len(h) == 1:
            ins = h[0]["id"]
    if not ins:
        return info(acc)

    # --- date
    d, found = parse_date(body, sent)
    if d is None:
        return info(acc, ins)
    iso = d.isoformat()
    cal = tools.get_calendar(iso)
    if not cal["business_day"] or iso > sent:
        return info(acc, ins)

    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        out.update(outcome="ESCALATE", account_id=acc, instrument_id=ins)
        return out

    ledger = tools.get_ledger(acc, ins)
    splits = tools.get_corporate_actions(ins)
    total = 0
    for t in ledger:
        if t["date"] > iso:
            continue
        q = t["qty"]
        for sp in splits:
            if sp["date"] <= iso and t["date"] < sp["date"]:
                q *= sp["ratio"]
        total += q
    out.update(account_id=acc, instrument_id=ins, as_of=iso, as_of_assumed=False)
    if total <= 0:
        out.update(outcome="NOT_HELD")
        return out
    out.update(outcome="CONFIRMED", settled=total)
    pend = [x for x in tools.get_instructions(acc, ins) if x["status"] == "matched" and x["settle_date"] > iso]
    if pend:
        out["pending"] = sum(x["qty"] for x in pend)
        out["pending_date"] = max(x["settle_date"] for x in pend)
    return out
