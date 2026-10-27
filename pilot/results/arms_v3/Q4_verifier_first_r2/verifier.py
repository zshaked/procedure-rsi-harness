"""Reference-free verifier for the holdings-confirmation desk.

verify(request, response, tools) -> (ok: bool, failures: list[str])

Each check below is a separate, commented condition that a correct response must satisfy,
with the evidence it was derived from (history case ids, unlabeled cases, tool docstrings,
and oracle answers -- see NOTES.md for the oracle log).
"""
import re
import datetime as dt

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "proton.me", "hotmail.com", "aol.com",
             "icloud.com", "protonmail.com", "live.com", "msn.com", "mail.com", "gmx.com"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Tunables (calibrated with the oracle; see NOTES.md)
MIN_LEVEL = 2            # Q4-0011 (level 1 -> REQUEST_AUTHORIZATION), Q4-0012/0013 (level 2 ok)
TOLERANCE = 0.10         # relative diff allowed: 8% accepted (oracle Q4-0077, hist Q4-0000 4%, Q4-0013 7%), 15% escalated (Q4-0001/0003/0024)


# ----------------------------------------------------------------------------- parsing helpers
def clean_body(body):
    """Drop forwarded-message headers and disclaimers (their 'Date:' is not the position date)."""
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


def _prev_month_end(s):
    return s.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date, kind) where kind is 'explicit' | 'relative' | None."""
    b = clean_body(body)
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
    # month/day without year -> most recent such date not after sent
    mon = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    for pat, mi, di in ((r"\b" + mon + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!,?\s*\d{4})", 1, 2),
                        (r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + mon + r"\b(?![\s\-,]*\d{4})", 2, 1)):
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
        k = WEEKDAYS.index(m[1])
        back = (s.weekday() - k) % 7 or 7
        return s - dt.timedelta(days=back), "relative"
    if re.search(r"(year[- ]end|end of (last|the previous|previous) year|last day of (last|the previous|previous) year)", bl):
        return dt.date(s.year - 1, 12, 31), "relative"
    if re.search(r"(quarter[- ]end|end of (last|the previous|previous) quarter)", bl):
        q0 = dt.date(s.year, 3 * ((s.month - 1) // 3) + 1, 1)
        return q0 - dt.timedelta(days=1), "relative"
    if re.search(r"(month[- ]end|end of (last|the previous|previous|the) month|last day of (last|the previous|previous) month|end of month|eom\b)", bl):
        return _prev_month_end(s), "relative"
    if re.search(r"\b(today|close of business today|cob today)\b", bl):
        return s, "relative"
    return None, None


def parse_qty(body):
    b = clean_body(body)
    m = re.search(r"(?:records show|figure is|we show|we have|books show|our position is|we hold)[ \t:]*"
                  r"(-?\(?[\d][\d,]*(?:\.\d+)?\)?)[ \t]*(mm|mn|m|k|thousand|million)?\b", b, re.I)
    if not m:
        return None
    t = m[1].replace(",", "")
    neg = t.startswith("-") or t.startswith("(")
    t = t.strip("-()")
    try:
        v = float(t)
    except ValueError:
        return None
    suf = (m[2] or "").lower()
    if suf in ("mm", "mn", "m", "million"):
        v *= 1_000_000
    elif suf in ("k", "thousand"):
        v *= 1000
    v = int(round(v))
    return -v if neg else v


_PREFIX = re.compile(r"^(?:our\s+|the\s+)?(?:account|acct|a/c|fund|portfolio|sub-account)\.?\s*(?:no\.?|number|#)?\s*[:#]?\s*", re.I)


def _norm_text(t):
    if t is None:
        return None
    t = t.strip().strip("\"'`()[]<>.,;:")
    t = _PREFIX.sub("", t).strip().strip("\"'`()[]<>.,;:")
    return t or None


def resolve_account(tools, text):
    """Unique account id, or None with reason ('missing'|'ambiguous'|'unknown')."""
    t = _norm_text(text)
    if not t:
        return None, "missing"
    cands = [t]
    t2 = re.sub(r"\s+", " ", t)
    if t2 != t:
        cands.append(t2)
    m = re.search(r"\b(ACC-\d+|SA-\d+)\b", t, re.I)
    if m:
        cands.insert(0, m[1].upper())
    for c in cands:
        hits = tools.search_accounts(c)
        ids = sorted({h["id"] for h in hits})
        if len(ids) == 1:
            return ids[0], None
        if len(ids) > 1:
            return None, "ambiguous"
    return None, "unknown"


def resolve_instrument(tools, text):
    t = _norm_text(text)
    if not t:
        return None, "missing"
    cands = [t, re.sub(r"\s+", " ", t)]
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", t.upper())
    if m:
        cands.insert(0, m[1])
    for c in cands:
        ids = sorted({i["id"] for i in tools.search_instruments(c)})
        if len(ids) == 1:
            return ids[0], None
        if len(ids) > 1:
            return None, "ambiguous"
    return None, "unknown"


def business_as_of(tools, d):
    cal = tools.get_calendar(d.isoformat())
    return d.isoformat() if cal["business_day"] else cal["previous_business_day"]


def settled_position(tools, acc, ins, as_of):
    """All custody sub-accounts, settled up to and including as_of, split-adjusted
    (ledger quantities are pre-split; a split multiplies holdings recorded before its date)."""
    cas = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    tot = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] <= as_of:
            q = t["qty"]
            for c in cas:
                if t["date"] < c["date"] <= as_of:
                    q *= c["ratio"]
            tot += q
    return tot


def pending_info(tools, acc, ins, as_of):
    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    if not pend:
        return 0, None
    return sum(x["qty"] for x in pend), max(x["settle_date"] for x in pend)


# ----------------------------------------------------------------------------- expected decision
def expected(request, tools, cfg=None):
    """Derive what the checklist requires. Returns dict with 'outcome' and required fields,
    plus 'why' (list of evidence strings)."""
    cfg = dict(cfg or {})
    tol = cfg.get("tolerance", TOLERANCE)
    why = []
    sender = (request.get("from") or "").strip().lower()
    m = re.search(r"<([^>]+)>", sender)
    if m:
        sender = m.group(1)
    domain = sender.split("@")[-1] if "@" in sender else ""
    sent = request.get("sent")
    ment = request.get("mentions") or {}
    body = request.get("body") or ""

    # CHECK A: free-mail / non-client sender domain -> REQUEST_AUTHORIZATION before anything else.
    # Evidence: Q4-0009 (gmail, no account named -> REQUEST_AUTHORIZATION, not REQUEST_INFO),
    #           Q4-0008 (gmail, entitled level 3, still REQUEST_AUTHORIZATION).
    if domain in FREE_MAIL or not domain:
        why.append("A: sender on free-mail/unknown domain")
        return {"outcome": "REQUEST_AUTHORIZATION", "why": why}

    # CHECK B: account must resolve to exactly one account (id, sub-account, name, short name,
    # or a unique name prefix). Ambiguous or missing -> REQUEST_INFO; entitlements are NOT used
    # to disambiguate.  Evidence: Q4-0002, Q4-0022 (prefix matches 3), Q4-0017 (short name 'SP' x2).
    acc, why_a = resolve_account(tools, ment.get("account_text"))
    if acc is None:
        why.append("B: account " + why_a)
        return {"outcome": "REQUEST_INFO", "why": why}

    # CHECK C: authorization = sender domain listed in the client profile AND the contact holds an
    # unexpired entitlement on that account with level >= 2.
    # Evidence: Q4-0004/0005/0018/0020 (no entitlement), Q4-0011 (level 1), Q4-0008 (domain),
    #           Q4-0003/0012/0013/0015/0021 (level 2 suffices). Tool doc: expired entitlements are included.
    prof = tools.get_client_profile(acc) or {}
    contact = tools.get_contact(sender)
    ok_ent = False
    if contact:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= cfg.get("min_level", MIN_LEVEL) \
                    and (not e.get("expires") or e["expires"] >= sent[:10]):
                ok_ent = True
    if domain not in [d.lower() for d in prof.get("domains", [])] or not ok_ent:
        why.append("C: sender not authorized for " + acc)
        return {"outcome": "REQUEST_AUTHORIZATION", "why": why}

    # CHECK D: legal hold -> ESCALATE (oracle Q4-0114). Comes AFTER authorization (oracle Q4-0118:
    # legal hold + level-1 sender -> REQUEST_AUTHORIZATION). no_email_confirm is NOT a stop
    # (oracle Q4-0054: "fine to confirm").
    ins, why_i = resolve_instrument(tools, ment.get("instrument_text"))
    if prof.get("legal_hold"):
        why.append("D: legal hold")
        return {"outcome": "ESCALATE", "account_id": acc, "instrument_id": ins, "why": why}

    # CHECK E: instrument must resolve uniquely -> else REQUEST_INFO. Evidence: Q4-0008 text, README.
    if ins is None:
        why.append("E: instrument " + why_i)
        return {"outcome": "REQUEST_INFO", "why": why}

    # CHECK F: a position date is required -> else REQUEST_INFO. Evidence: Q4-0014, Q4-0016.
    d, kind = parse_date(body, sent)
    if d is None:
        why.append("F: no date")
        return {"outcome": "REQUEST_INFO", "why": why}
    s = dt.date.fromisoformat(sent[:10])
    if kind == "prevbd":  # "last business day" = business day before the sent date
        d = dt.date.fromisoformat(tools.get_calendar(sent[:10])["previous_business_day"])
    # CHECK G: a date after the sent date cannot be confirmed -> REQUEST_INFO (oracle Q4-0083).
    # (date == sent date is unobserved; treated the same, configurable.)
    if d >= s if cfg.get("future_incl_today", True) else d > s:
        why.append("G: future date")
        return {"outcome": cfg.get("future", "REQUEST_INFO"), "why": why}

    # CHECK H: as_of = requested date, rolled back to the previous business day if it is a weekend
    # or holiday. Evidence: Q4-0006 (Sat 3 Jan -> 01-02), Q4-0012, Q4-0013 (-> 01-30).
    as_of = business_as_of(tools, d)
    # as_of_assumed: False for explicit dates, relative dates ("month-end", oracle Q4-0098) and
    # weekend/holiday roll-backs (oracle Q4-0077, Q4-0098). Only when the desk had to assume part of
    # the date itself (no year given) is it marked True (unobserved; best guess).
    mode = cfg.get("assumed", "noyear")
    assumed = (as_of != d.isoformat()) if mode == "rolled" else \
        (kind == "relative") if mode == "relative" else (kind == "noyear") if mode == "noyear" else False

    # CHECK I: settled figure = all sub-accounts, ledger to as_of inclusive, split-adjusted.
    # Evidence: Q4-0007 (sum of 3 sub-accounts), Q4-0019 (client quoted pre-split -> mismatch),
    # Q4-0091 (sub-account mention, client figure equals whole-account total).
    # get_position_summary is NOT used (primary sub-account only, day before as_of).
    settled = settled_position(tools, acc, ins, as_of)
    pq, pd = pending_info(tools, acc, ins, as_of)

    # CHECK L0: nothing settled -> NOT_HELD, even if the client quotes a figure (oracle Q4-0130).
    if settled == 0:
        why.append("L: not held")
        return {"outcome": "NOT_HELD", "account_id": acc, "instrument_id": ins, "as_of": as_of,
                "as_of_assumed": assumed, "settled": 0,
                "pending": pq or None, "pending_date": pd, "why": why}

    # CHECK J: client's figure must agree with the desk figure, else ESCALATE.
    # Evidence: Q4-0001/0003/0024 (client 0.85x -> ESCALATE), Q4-0019 (pre-split), Q4-0015 (match).
    # A client figure matching settled+pending is also fine (oracle Q4-0183, hist Q4-0013).
    client = parse_qty(body)
    if client is not None:
        targets = [settled]
        if cfg.get("pending_match", True):
            targets.append(settled + pq)
        def close(a, b):
            if b == 0:
                return a == 0
            return abs(a - b) <= tol * abs(b) + 1e-9
        if not any(close(client, t) for t in targets):
            why.append("J: client figure %s vs desk %s" % (client, settled))
            return {"outcome": "ESCALATE", "account_id": acc, "instrument_id": ins, "why": why}

    # CHECK K: negative settled -> ESCALATE (data problem).
    if settled < 0:
        why.append("K: negative position")
        return {"outcome": "ESCALATE", "account_id": acc, "instrument_id": ins, "why": why}

    # CHECK L: positive -> CONFIRMED with the settled figure.
    # CHECK M: pending = matched instructions settling after as_of (unmatched/cancelled excluded),
    # pending_date = latest such settle date; omitted when none.
    # Evidence: Q4-0013 (79+38071 -> 38,150, expected 04-05), Q4-0021 (unmatched excluded), Q4-0010.
    why.append("L: confirmed")
    return {"outcome": "CONFIRMED", "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled,
            "pending": pq or None, "pending_date": pd, "why": why}


def verify(request, response, tools, cfg=None):
    fails = []
    # CHECK 0: schema.
    if not isinstance(response, dict) or response.get("outcome") not in OUTCOMES:
        return False, ["0: invalid outcome"]
    exp = expected(request, tools, cfg)
    out = response["outcome"]
    if out != exp["outcome"]:
        fails.append("outcome %s, expected %s (%s)" % (out, exp["outcome"], "; ".join(exp["why"])))
        return False, fails
    # CHECK N: field population per README.
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        for k in ("account_id", "instrument_id"):
            if k in exp and response.get(k) != exp[k]:
                fails.append("%s %r expected %r" % (k, response.get(k), exp[k]))
    if out in ("CONFIRMED", "NOT_HELD"):
        if response.get("as_of") != exp["as_of"]:
            fails.append("as_of %r expected %r" % (response.get("as_of"), exp["as_of"]))
        if bool(response.get("as_of_assumed")) != bool(exp["as_of_assumed"]):
            fails.append("as_of_assumed %r expected %r" % (response.get("as_of_assumed"), exp["as_of_assumed"]))
    if out == "CONFIRMED":
        if response.get("settled") != exp["settled"]:
            fails.append("settled %r expected %r" % (response.get("settled"), exp["settled"]))
    if out in ("CONFIRMED", "NOT_HELD"):
        if (response.get("pending") or None) != exp.get("pending"):
            fails.append("pending %r expected %r" % (response.get("pending"), exp.get("pending")))
        if response.get("pending_date") != exp.get("pending_date"):
            fails.append("pending_date %r expected %r" % (response.get("pending_date"), exp.get("pending_date")))
    return (not fails), fails
