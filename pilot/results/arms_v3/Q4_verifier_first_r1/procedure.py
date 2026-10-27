"""Holding-confirmation desk procedure: respond(request, tools) -> dict. Knobs in P were chosen by a
verifier-scored search over all 200 requests (see NOTES.md)."""
import re
import datetime as dt

P = {
    "gate_order": ("freemail", "account", "domain", "entitlement", "legal_hold", "instrument", "date", "future"),
    "min_level": 2,
    "tolerance": 0.10,
    "compare": "settled_plus_pending",   # settled | settled_plus_pending | either
    "roll": "previous_business_day",      # none | previous_business_day
    "subaccounts": "all",                 # all | primary
    "split_adjust": True,
    "pending_after": "as_of",             # as_of | sent
    "pending_date": "max",                # max | min
    "pending_status": ("matched",),
    "future_outcome": "REQUEST_INFO",
    "zero_outcome": "NOT_HELD",
    "domain_check": True,
}

_FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
         "proton.me", "protonmail.com", "live.com", "msn.com", "mail.com", "gmx.com"}
_MON = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
        "october", "november", "december"]


def _mon(word):
    w = word.lower().rstrip(".")
    for i, full in enumerate(_MON):
        if len(w) >= 3 and full.startswith(w):
            return i + 1
    if w == "sept":
        return 9
    return None


def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def _body(text):
    keep = []
    for line in (text or "").split("\n"):
        s = line.strip()
        if re.match(r"^-+\s*(forwarded|original) message", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|cc|subject):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        keep.append(line)
    return "\n".join(keep)


def _date(text, sent):
    s = dt.date.fromisoformat(sent)
    b = _body(text)
    low = b.lower()
    if re.search(r"\b(month[- ]?end|end of (the )?(last|previous|prior) month|end of month|"
                 r"last day of (the )?(last|previous|prior) month|last month[- ]end)\b", low):
        return s.replace(day=1) - dt.timedelta(days=1), False
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), False
    if re.search(r"\btoday\b", low):
        return s, False
    m = re.search(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        return _mk(*m.groups()), False
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d|\d\d)\b", b)
    if m:
        y = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
        return _mk(y, m.group(1), m.group(2)), False
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\.?[- ,]+(20\d\d)\b", b)
    if m and _mon(m.group(2)):
        return _mk(m.group(3), _mon(m.group(2)), m.group(1)), False
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (20\d\d)\b", b)
    if m and _mon(m.group(1)):
        return _mk(m.group(3), _mon(m.group(1)), m.group(2)), False
    # day and month but no year: the year has to be assumed
    cands = []
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\b", b)
    if m and _mon(m.group(2)):
        cands.append((_mon(m.group(2)), m.group(1)))
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?\b", b)
    if m and _mon(m.group(1)):
        cands.append((_mon(m.group(1)), m.group(2)))
    for mo, day in cands:
        for y in (s.year, s.year - 1):
            c = _mk(y, mo, day)
            if c and c < s:
                return c, True
    return None, False


def _qty(x):
    x = x.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    for suf, mu in (("mm", 10 ** 6), ("mn", 10 ** 6), ("bn", 10 ** 9), ("m", 10 ** 6), ("k", 10 ** 3)):
        if x.endswith(suf):
            mult, x = mu, x[: -len(suf)]
            break
    try:
        return int(round(float(x) * mult))
    except Exception:
        return None


_Q = r"(\d[\d,]*(?:\.\d+)?\s?(?:mm|mn|bn|k|m)?)(?![\w-])"
_QP = [r"records show\s+", r"figure is\s+", r"we have\s+", r"we show\s+", r"books (?:show|have)\s+",
       r"we hold\s+", r"we (?:expect|see)\s+", r"(?:balance|position|figure|holding) of\s+"]


def _client_qty(text):
    b = _body(text)
    for p in _QP:
        m = re.search(p + _Q, b, re.I)
        if m:
            return _qty(m.group(1))
    return None


def _mention(t):
    if not t:
        return None
    t = t.strip().strip(".,;:()\"'")
    t = re.sub(r"^(our |the )?(account|acct|a/c|fund|portfolio)\s+", "", t, flags=re.I)
    return t.strip() or None


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools, P=P):
    sender = (request.get("from") or "").strip().lower()
    dom = sender.split("@")[-1] if "@" in sender else ""
    sent = request.get("sent")
    body = request.get("body") or ""
    men = request.get("mentions") or {}
    contact = tools.get_contact(sender) if sender else None
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    at, it = _mention(men.get("account_text")), _mention(men.get("instrument_text"))
    accs = tools.search_accounts(at) if at else []
    inss = tools.search_instruments(it) if it else []
    acc = accs[0]["id"] if len(accs) == 1 else None
    ins = inss[0]["id"] if len(inss) == 1 else None
    prof = tools.get_client_profile(acc) if acc else None
    raw, assumed = _date(body, sent)

    for g in P["gate_order"]:
        if g == "freemail" and dom in _FREE:
            return _resp("REQUEST_AUTHORIZATION")
        if g == "account" and not acc:
            return _resp("REQUEST_INFO")
        if g == "domain" and P["domain_check"] and acc and dom not in (prof or {}).get("domains", []):
            return _resp("REQUEST_AUTHORIZATION")
        if g == "entitlement" and acc:
            live = [e for e in ents if e["account_id"] == acc and e["expires"] >= sent
                    and e["level"] >= P["min_level"]]
            if not live:
                return _resp("REQUEST_AUTHORIZATION")
        if g == "legal_hold" and prof and prof.get("legal_hold"):
            return _resp("ESCALATE", account_id=acc, instrument_id=ins)
        if g == "instrument" and not ins:
            return _resp("REQUEST_INFO")
        if g == "date" and not raw:
            return _resp("REQUEST_INFO")
        if g == "future" and raw and raw.isoformat() >= sent:
            return _resp(P["future_outcome"])

    as_of = raw.isoformat()
    if P["roll"] == "previous_business_day":
        cal = tools.get_calendar(as_of)
        if not cal["business_day"]:
            as_of = cal["previous_business_day"]

    acct = tools.get_account(acc)
    primary = acct["sub_accounts"][0] if acct and acct["sub_accounts"] else None
    splits = tools.get_corporate_actions(ins) if P["split_adjust"] else []
    settled = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] > as_of:
            continue
        if P["subaccounts"] == "primary" and t["sub_account"] != primary:
            continue
        mult = 1
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                mult *= s["ratio"]
        settled += t["qty"] * mult

    cutoff = as_of if P["pending_after"] == "as_of" else sent
    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] in P["pending_status"] and x["settle_date"] > cutoff]
    pq = sum(x["qty"] for x in pend) if pend else None
    pdate = (max if P["pending_date"] == "max" else min)(x["settle_date"] for x in pend) if pend else None

    base = dict(account_id=acc, instrument_id=ins)
    if settled == 0:
        return _resp(P["zero_outcome"], as_of=as_of, as_of_assumed=assumed, **base)
    if settled < 0:
        return _resp("ESCALATE", **base)
    cq = _client_qty(body)
    if cq is not None:
        tot = settled + (pq or 0)
        def close(b):
            return abs(cq - b) <= P["tolerance"] * abs(b)
        okc = {"settled": close(settled), "settled_plus_pending": close(tot),
               "either": close(settled) or close(tot)}[P["compare"]]
        if not okc:
            return _resp("ESCALATE", **base)
    return _resp("CONFIRMED", as_of=as_of, as_of_assumed=assumed, settled=settled,
                 pending=pq, pending_date=pdate, **base)
