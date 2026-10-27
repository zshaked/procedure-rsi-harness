"""Holdings-confirmation desk procedure.

respond(request, tools) -> dict. Deterministic, standard library only, state read only via `tools`.

Decision order (see NOTES.md):
 1. sender on a free-mail / unknown domain            -> REQUEST_AUTHORIZATION
 2. account must resolve to exactly one account       -> else REQUEST_INFO
 3. sender domain in client profile AND contact has an
    unexpired entitlement on the account, level >= 2  -> else REQUEST_AUTHORIZATION
 4. client under legal hold                           -> ESCALATE
 5. instrument must resolve to exactly one            -> else REQUEST_INFO
 6. a position date is required and not in the future -> else REQUEST_INFO
 7. as_of = date rolled back to previous business day
 8. settled = ledger over all sub-accounts up to as_of, split-adjusted
 9. settled == 0                                      -> NOT_HELD
10. client figure differs > 10% from settled and from
    settled + pending                                 -> ESCALATE
11. settled < 0                                       -> ESCALATE
12. otherwise CONFIRMED (+ matched instructions settling after as_of as pending)
"""
import re
import datetime as dt

CONFIG = {
    "tolerance": 0.10,
    "min_level": 2,
    "pending_match": True,
    "pending_date": "max",        # latest settle date of the pending instructions
    "all_subaccounts": True,
    "roll": "previous",           # weekend/holiday -> previous business day
    "future_incl_today": True,
    "legal_hold_before_auth": False,
    "zero_before_mismatch": True,
    "assumed": "noyear",
    "free_mail_first": True,
}

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "proton.me", "hotmail.com", "aol.com",
             "icloud.com", "protonmail.com", "live.com", "msn.com", "mail.com", "gmx.com",
             "yahoo.co.uk", "googlemail.com", "me.com"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MON = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
       r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")


# ------------------------------------------------------------------ text parsing
def _clean_body(body):
    out = []
    for ln in (body or "").split("\n"):
        s = ln.strip()
        if s.startswith("-----") or re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if "confidential and intended solely" in s.lower():
            continue
        out.append(ln)
    return "\n".join(out)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _parse_date(body, sent):
    b = _clean_body(body)
    bl = b.lower()
    s = dt.date.fromisoformat(sent[:10])
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        d = _mk(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return d, "explicit"
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b", b)
    if m:
        a, c, y = int(m[1]), int(m[2]), int(m[3])
        y = y + 2000 if y < 100 else y
        d = _mk(y, a, c) if a <= 12 else _mk(y, c, a)
        if d:
            return d, "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?([A-Za-z]{3,9})\.?[\s\-,]+(\d{4})\b", b)
    if m and m[2][:3].lower() in MONTHS:
        d = _mk(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))
        if d:
            return d, "explicit"
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b)
    if m and m[1][:3].lower() in MONTHS:
        d = _mk(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2]))
        if d:
            return d, "explicit"
    for pat, mi, di in ((r"\b" + MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!,?\s*\d{4})", 1, 2),
                        (r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MON + r"\b(?![\s\-,]*\d{4})", 2, 1)):
        m = re.search(pat, b)
        if m:
            d = _mk(s.year, MONTHS[m[mi][:3].lower()], int(m[di]))
            if d and d > s:
                d = _mk(s.year - 1, d.month, d.day)
            if d:
                return d, "noyear"
    if re.search(r"\b(last|previous|prior) (business|working|trading) day\b", bl):
        return s, "prevbd"
    if "day before yesterday" in bl:
        return s - dt.timedelta(days=2), "relative"
    if "yesterday" in bl:
        return s - dt.timedelta(days=1), "relative"
    m = re.search(r"\b(\d+)\s+days?\s+ago\b", bl)
    if m:
        return s - dt.timedelta(days=int(m[1])), "relative"
    m = re.search(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", bl)
    if m:
        back = (s.weekday() - WEEKDAYS.index(m[1])) % 7 or 7
        return s - dt.timedelta(days=back), "relative"
    if re.search(r"(year[- ]end|end of (last|the previous|previous) year|last day of (last|the previous|previous) year)", bl):
        return dt.date(s.year - 1, 12, 31), "relative"
    if re.search(r"(quarter[- ]end|end of (last|the previous|previous) quarter)", bl):
        q0 = dt.date(s.year, 3 * ((s.month - 1) // 3) + 1, 1)
        return q0 - dt.timedelta(days=1), "relative"
    if re.search(r"(month[- ]end|end of (last|the previous|previous|the) month|last day of (last|the previous|previous) month|end of month|\beom\b)", bl):
        return s.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"\b(today|close of business today|cob today)\b", bl):
        return s, "relative"
    return None, None


def _parse_qty(body):
    b = _clean_body(body)
    m = re.search(r"(?:records show|figure is|we show|we have|books show|our position is|we hold)[ \t:]*"
                  r"(-?\(?[\d][\d,]*(?:\.\d+)?\)?)[ \t]*(mm|mn|m|k|thousand|million)?\b", b, re.I)
    if not m:
        return None
    t = m[1].replace(",", "")
    neg = t.startswith("-") or t.startswith("(")
    try:
        v = float(t.strip("-()"))
    except ValueError:
        return None
    suf = (m[2] or "").lower()
    if suf in ("mm", "mn", "m", "million"):
        v *= 1_000_000
    elif suf in ("k", "thousand"):
        v *= 1000
    v = int(round(v))
    return -v if neg else v


_PREFIX = re.compile(r"^(?:our\s+|the\s+)?(?:account|acct|a/c|fund|portfolio|sub-account)\.?\s*"
                     r"(?:no\.?|number|#)?\s*[:#]?\s*", re.I)


def _norm(t):
    if t is None:
        return None
    t = str(t).strip().strip("\"'`()[]<>.,;:")
    t = _PREFIX.sub("", t).strip().strip("\"'`()[]<>.,;:")
    return t or None


def _resolve_account(tools, text):
    t = _norm(text)
    if not t:
        return None
    cands = [t, re.sub(r"\s+", " ", t)]
    m = re.search(r"\b(ACC-\d+|SA-\d+)\b", t, re.I)
    if m:
        cands.insert(0, m[1].upper())
    for c in cands:
        ids = sorted({h["id"] for h in tools.search_accounts(c)})
        if len(ids) == 1:
            return ids[0]
        if len(ids) > 1:
            return None
    return None


def _resolve_instrument(tools, text):
    t = _norm(text)
    if not t:
        return None
    cands = [t, re.sub(r"\s+", " ", t)]
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", t.upper())
    if m:
        cands.insert(0, m[1])
    for c in cands:
        ids = sorted({i["id"] for i in tools.search_instruments(c)})
        if len(ids) == 1:
            return ids[0]
        if len(ids) > 1:
            return None
    return None


# ------------------------------------------------------------------ figures
def _settled(tools, acc, ins, as_of, cfg):
    cas = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    led = tools.get_ledger(acc, ins)
    if not cfg["all_subaccounts"]:
        a = tools.get_account(acc)
        led = [t for t in led if a and t["sub_account"] == a["sub_accounts"][0]]
    tot = 0
    for t in led:
        if t["date"] <= as_of:
            q = t["qty"]
            for c in cas:
                if t["date"] < c["date"] <= as_of:
                    q *= c["ratio"]
            tot += q
    return tot


def _pending(tools, acc, ins, as_of, cfg):
    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    if not pend:
        return None, None
    dates = [x["settle_date"] for x in pend]
    return sum(x["qty"] for x in pend), (max(dates) if cfg["pending_date"] == "max" else min(dates))


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools, cfg=None):
    cfg = dict(CONFIG, **(cfg or {}))
    sender = (request.get("from") or "").strip().lower()
    m = re.search(r"<([^>]+)>", sender)
    if m:
        sender = m.group(1).strip()
    domain = sender.split("@")[-1] if "@" in sender else ""
    sent = (request.get("sent") or "")[:10]
    ment = request.get("mentions") or {}
    body = request.get("body") or ""

    # 1. unknown sender domain
    if cfg["free_mail_first"] and (not domain or domain in FREE_MAIL):
        return _resp("REQUEST_AUTHORIZATION")

    # 2. account
    acc = _resolve_account(tools, ment.get("account_text"))
    if acc is None:
        return _resp("REQUEST_INFO")
    prof = tools.get_client_profile(acc) or {}
    ins = _resolve_instrument(tools, ment.get("instrument_text"))

    if cfg["legal_hold_before_auth"] and prof.get("legal_hold"):
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)

    # 3. authorization
    contact = tools.get_contact(sender)
    ok = False
    if contact:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= cfg["min_level"] and \
                    (not e.get("expires") or e["expires"] >= sent):
                ok = True
    if domain not in [d.lower() for d in prof.get("domains", [])] or not ok:
        return _resp("REQUEST_AUTHORIZATION")

    # 4. legal hold
    if prof.get("legal_hold"):
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)

    # 5. instrument
    if ins is None:
        return _resp("REQUEST_INFO")

    # 6. date
    d, kind = _parse_date(body, sent)
    if d is None:
        return _resp("REQUEST_INFO")
    s = dt.date.fromisoformat(sent)
    if kind == "prevbd":
        d = dt.date.fromisoformat(tools.get_calendar(sent)["previous_business_day"])
    if (d >= s) if cfg["future_incl_today"] else (d > s):
        return _resp("REQUEST_INFO")

    # 7. as_of
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]
    assumed = (kind == "noyear") if cfg["assumed"] == "noyear" else False

    # 8. figures
    settled = _settled(tools, acc, ins, as_of, cfg)
    pq, pd = _pending(tools, acc, ins, as_of, cfg)
    base = dict(account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed)

    # 9. not held
    if cfg["zero_before_mismatch"] and settled == 0:
        return _resp("NOT_HELD", settled=0, pending=pq, pending_date=pd, **base)

    # 10. client figure check
    client = _parse_qty(body)
    if client is not None:
        targets = [settled] + ([settled + (pq or 0)] if cfg["pending_match"] else [])
        tol = cfg["tolerance"]
        if not any((client == t) if t == 0 else abs(client - t) <= tol * abs(t) + 1e-9 for t in targets):
            return _resp("ESCALATE", account_id=acc, instrument_id=ins)

    if settled == 0:
        return _resp("NOT_HELD", settled=0, pending=pq, pending_date=pd, **base)
    # 11. negative
    if settled < 0:
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)
    # 12. confirmed
    return _resp("CONFIRMED", settled=settled, pending=pq, pending_date=pd, **base)
