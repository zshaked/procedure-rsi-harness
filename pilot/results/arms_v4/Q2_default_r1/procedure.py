import re
import datetime as dt

# ---------------------------------------------------------------- policy switches
LEGAL_HOLD_OUTCOME = "ESCALATE"            # authorized sender, account under legal hold
NO_EMAIL_OUTCOME = "REQUEST_AUTHORIZATION"  # authorized sender, account flagged no_email_confirm
CF_COMPARE_TOTAL = True                    # client figure is compared with settled + matched pending
ZERO_WITH_FIGURE = "NOT_HELD"              # nothing held but client quoted a figure
MIN_LEVEL = 2

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _mon(s):
    return MONTHS[s[:3].lower()]


def _d(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _clean_body(body):
    """Drop forwarded-message header lines (From:/Date:/...) and separators."""
    out = []
    for ln in body.splitlines():
        if re.match(r"^\s*(from|date|sent|to|cc|subject)\s*:", ln, re.I):
            continue
        if re.match(r"^\s*-{3,}.*-{3,}\s*$", ln):
            continue
        if re.match(r"^\s*on .{5,80}wrote:\s*$", ln, re.I):
            continue
        out.append(ln)
    return "\n".join(out)


def _month_end_prev(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return the date the email asks about, or None if it gives none."""
    t = _clean_body(body)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        d = _d(*m.groups())
        if d:
            return d
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        d = _d(m.group(3), m.group(1), m.group(2))
        if d:
            return d
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s]+" + MONTH_RE + r"\.?[-\s,]+(\d{4})\b", t, re.I)
    if m:
        d = _d(m.group(3), _mon(m.group(2)), m.group(1))
        if d:
            return d
    m = re.search(r"\b" + MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        d = _d(m.group(3), _mon(m.group(1)), m.group(2))
        if d:
            return d
    low = t.lower()
    if re.search(r"\b(end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|"
                 r"month[- ]?end|end of (the )?month|last business day of (the )?(last|previous|prior) month)\b", low):
        return _month_end_prev(sent)
    if re.search(r"\b(end of (the )?(last|previous|prior) quarter|last day of (the )?(last|previous|prior) quarter|"
                 r"quarter[- ]?end)\b", low):
        qm = ((sent.month - 1) // 3) * 3 + 1
        return dt.date(sent.year, qm, 1) - dt.timedelta(days=1)
    if re.search(r"\b(year[- ]?end|end of (the )?(last|previous|prior) year|end of last year)\b", low):
        return dt.date(sent.year - 1, 12, 31)
    m = re.search(r"\b(?:last|previous)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(m.group(1))
        back = (sent.weekday() - wd) % 7 or 7
        return sent - dt.timedelta(days=back)
    if re.search(r"\b(last|previous|prior) business day\b", low):
        d0 = sent - dt.timedelta(days=1)
        while d0.weekday() >= 5:
            d0 -= dt.timedelta(days=1)
        return d0
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1)
    if re.search(r"\b(today|this morning|close of business today)\b", low):
        return sent
    return None


_NUM = r"(\d[\d,]*(?:\.\d+)?)(?:\s?(k|mm|m|million|thousand)(?![a-z]))?"


def _qty(numstr, suf):
    """Return (value, half_width_of_rounding)."""
    s = numstr.replace(",", "")
    v = float(s)
    suf = (suf or "").lower()
    mult = {"": 1, "k": 1e3, "thousand": 1e3, "mm": 1e6, "m": 1e6, "million": 1e6}[suf]
    val = int(round(v * mult))
    half = 0
    if suf:
        dec = len(s.split(".")[1]) if "." in s else 0
        half = 0.5 * mult * (10 ** (-dec))
    return val, half


def _mask(t):
    t = re.sub(r"\b(ACC|SA)-\d+\b", " ", t)
    t = re.sub(r"\b[A-Z]{2}[A-Z0-9]{10}\b", " ", t)
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", t)
    t = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ", t)
    t = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?[-\s]+" + MONTH_RE + r"\.?[-\s,]+\d{4}\b", " ", t, flags=re.I)
    t = re.sub(r"\b" + MONTH_RE + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b", " ", t, flags=re.I)
    return t


def client_figure(body):
    """(value, half_width) of the quantity the client quotes, or None."""
    t = _mask(_clean_body(body))
    cue = (r"(?:figure\s+(?:is|of|:)|we\s+show|records\s+(?:show|indicate|reflect)|we\s+have|we\s+hold|"
           r"books\s+(?:show|indicate)|shows?|showing|balance\s+(?:is|of)|position\s+of)")
    m = re.search(cue + r"\s*:?\s*(?:a\s+position\s+of\s+|a\s+balance\s+of\s+|approximately\s+|approx\.?\s+|about\s+)?"
                  + _NUM + r"(?![\d,])", t, re.I)
    if m:
        return _qty(m.group(1), m.group(2))
    return None


def _figure_agrees(cf, value):
    v, half = cf
    return abs(v - value) <= half


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    body = request["body"]
    mentions = request.get("mentions") or {}

    def blank(outcome):
        return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
                "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    # ---- 1. resolve the account; missing/ambiguous -> ask
    at = mentions.get("account_text")
    it = mentions.get("instrument_text")
    if not at:
        return blank("REQUEST_INFO")
    accs = tools.search_accounts(at)
    if len(accs) != 1:
        return blank("REQUEST_INFO")
    acct = accs[0]["id"]

    # ---- 2. authorization: known contact, sender domain on the account's profile,
    #         unexpired entitlement of sufficient level on this account
    sender = request["from"].strip().lower()
    mm = re.search(r"[\w.+\-']+@[\w.\-]+", sender)
    if mm:
        sender = mm.group(0)
    dom = sender.split("@")[-1]
    prof = tools.get_client_profile(acct)
    contact = tools.get_contact(sender)
    ok = bool(prof) and bool(contact) and dom in [x.lower() for x in prof["domains"]]
    if ok:
        ok = False
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acct and e["level"] >= MIN_LEVEL and e["expires"] >= request["sent"]:
                ok = True
    if not ok:
        return blank("REQUEST_AUTHORIZATION")

    # ---- 2b. account-level restrictions
    if prof.get("no_email_confirm"):
        return blank(NO_EMAIL_OUTCOME)

    # ---- 2c. instrument
    inst = None
    if it:
        insts = tools.search_instruments(it)
        if len(insts) == 1:
            inst = insts[0]["id"]
    if inst is None:
        if prof.get("legal_hold"):
            r = blank("ESCALATE")
            r["account_id"] = acct
            return r
        return blank("REQUEST_INFO")

    # ---- 3. as-of date
    d = parse_date(body, sent)
    assumed = False
    if d is None:
        d = sent
        assumed = True
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    # ---- 4. figures from the ledger (all sub-accounts, split adjusted)
    ledger = tools.get_ledger(acct, inst)
    acts = tools.get_corporate_actions(inst)
    settled = 0
    for t in ledger:
        if t["date"] <= as_of:
            q = t["qty"]
            for a in acts:
                if a["date"] <= as_of and t["date"] < a["date"]:
                    q *= a["ratio"]
            settled += q

    pending = None
    pending_date = None
    pend = [x for x in tools.get_instructions(acct, inst) if x["status"] == "matched" and x["settle_date"] > as_of]
    if pend:
        pending = sum(x["qty"] for x in pend)
        pending_date = max(x["settle_date"] for x in pend)

    res = {"outcome": "CONFIRMED", "account_id": acct, "instrument_id": inst, "as_of": as_of,
           "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pending_date}

    # ---- 5. legal hold: nothing is released, a person reviews
    if prof.get("legal_hold"):
        res["outcome"] = "ESCALATE"
        return res

    # ---- 6. compare with the client's own figure
    cf = client_figure(body)
    if settled == 0 and not pending:
        if cf is not None and ZERO_WITH_FIGURE == "ESCALATE":
            res["outcome"] = "ESCALATE"
            return res
        res["outcome"] = "NOT_HELD"
        res["settled"] = None
        res["pending"] = None
        res["pending_date"] = None
        return res
    if cf is not None:
        if CF_COMPARE_TOTAL:
            agree = _figure_agrees(cf, settled + (pending or 0))
        else:
            agree = _figure_agrees(cf, settled) or _figure_agrees(cf, settled + (pending or 0))
        if not agree:
            res["outcome"] = "ESCALATE"
    return res
