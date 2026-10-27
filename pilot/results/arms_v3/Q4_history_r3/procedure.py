"""Induced procedure for the holding-confirmation desk."""
import datetime as dt
import re

FREEMAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com",
            "icloud.com", "aol.com", "live.com", "msn.com", "gmx.com", "mail.com", "yandex.com"}
MIN_LEVEL = 2
TOLERANCE = 0.10  # relative difference between client figure and our figure before escalating

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DOW_RE = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*,?\s+)?"


def _empty(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _strip_noise(body):
    """Remove forwarded-message headers and disclaimers so their dates are not read as the as-of."""
    out = []
    for line in body.splitlines():
        s = line.strip()
        if re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if re.match(r"^-+\s*forwarded message", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        out.append(line)
    return "\n".join(out)


def _last_day_of_month(y, m):
    if m == 12:
        return dt.date(y, 12, 31)
    return dt.date(y, m + 1, 1) - dt.timedelta(days=1)


def _prev_month_end(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(text, sent):
    """Return (date, assumed) or (None, False)."""
    t = text.lower()
    # explicit ISO
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", t)
    if m:
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, False
    # dd-Mon-yyyy / d Mon yyyy / Dow d Mon yyyy
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + MON_RE + r"[a-z]*\.?[\s\-,]+(\d{4})\b", t)
    if m:
        d = _safe_date(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))
        if d:
            return d, False
    # Month d, yyyy
    m = re.search(r"\b" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m:
        d = _safe_date(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2)))
        if d:
            return d, False
    # m/d/yyyy (US)
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        d = _safe_date(y, a, b) or _safe_date(y, b, a)
        if d:
            return d, False
    # relative expressions
    if re.search(r"\byesterday\b", t):
        return sent - dt.timedelta(days=1), False
    if re.search(r"\b(today|close of business today|cob today|this morning)\b", t):
        return sent, False
    if re.search(r"(end of last month|last day of last month|last month[- ]end|previous month[- ]end|"
                 r"end of (the )?previous month|prior month[- ]end)", t):
        return _prev_month_end(sent), False
    if re.search(r"\bmonth[- ]?end\b|\bend of (the )?month\b|\bm/e\b", t):
        return _prev_month_end(sent), True
    if re.search(r"(end of last year|last year[- ]end|year[- ]end|end of (the )?year)", t):
        return dt.date(sent.year - 1, 12, 31), "last" not in t
    if re.search(r"(end of last quarter|last quarter[- ]end|quarter[- ]end|end of (the )?quarter)", t):
        q_start_month = 3 * ((sent.month - 1) // 3) + 1
        return dt.date(sent.year, q_start_month, 1) - dt.timedelta(days=1), "last" not in t
    m = re.search(r"\blast (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(m.group(1))
        delta = (sent.weekday() - wd) % 7 or 7
        return sent - dt.timedelta(days=delta), False
    # Month d (no year) -> most recent such date not after sent
    m = re.search(r"\b" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m:
        mo, da = MONTHS[m.group(1)[:3]], int(m.group(2))
        d = _safe_date(sent.year, mo, da)
        if d and d > sent:
            d = _safe_date(sent.year - 1, mo, da)
        if d:
            return d, True
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON_RE + r"\b", t)
    if m:
        mo, da = MONTHS[m.group(2)[:3]], int(m.group(1))
        d = _safe_date(sent.year, mo, da)
        if d and d > sent:
            d = _safe_date(sent.year - 1, mo, da)
        if d:
            return d, True
    return None, False


def parse_qty(text):
    t = text.lower()
    pats = [
        r"(?:records show|our figure is|we have|we show|our books show|we hold|we record|our position is|"
        r"we expect|reconcil\w* to|our records indicate|figure of|balance of)\s*:?\s*"
        r"([\d][\d,]*(?:\.\d+)?)\s*(mm|mn|m|k|million|thousand)?\b",
        r"([\d][\d,]*(?:\.\d+)?)\s*(mm|mn|m|k|million|thousand)?\s+(?:units|shares)\b",
    ]
    for p in pats:
        m = re.search(p, t)
        if m:
            num = m.group(1).replace(",", "")
            try:
                v = float(num)
            except ValueError:
                continue
            suf = m.group(2)
            if suf in ("k", "thousand"):
                v *= 1000
            elif suf in ("mm", "mn", "m", "million"):
                v *= 1000000
            return int(round(v))
    return None


def _biz_on_or_before(tools, d):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def _resolve_account(tools, text):
    if not text:
        return None
    t = text.strip()
    hits = tools.search_accounts(t)
    if not hits:
        t2 = re.sub(r"^(?:our\s+)?(?:account|acct|a/c|fund|the fund)\s+", "", t, flags=re.I).strip()
        t2 = t2.strip(" .,;:()[]'\"")
        if t2 and t2 != t:
            hits = tools.search_accounts(t2)
    if not hits:
        m = re.search(r"\b(?:ACC|SA)-\d+\b", t, re.I)
        if m:
            hits = tools.search_accounts(m.group(0))
    return hits


def _resolve_instrument(tools, text):
    if not text:
        return None
    t = text.strip()
    hits = tools.search_instruments(t)
    if not hits:
        m = re.search(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", t)
        if m:
            hits = tools.search_instruments(m.group(0))
    if not hits:
        t2 = re.sub(r"\b(shares|stock|common|ordinary|units|equity|position)\b", "", t, flags=re.I)
        t2 = re.sub(r"\(.*?\)", "", t2).strip(" .,;:()[]'\"")
        if t2 and t2 != t:
            hits = tools.search_instruments(t2)
    # dedupe by id
    seen, out = set(), []
    for h in hits:
        if h["id"] not in seen:
            seen.add(h["id"])
            out.append(h)
    return out


def _authorized(tools, sender, account_id, sent):
    domain = sender.split("@")[-1].lower()
    prof = tools.get_client_profile(account_id) or {}
    if domain not in [d.lower() for d in prof.get("domains", [])]:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] != account_id:
            continue
        if e.get("level") is None or e["level"] < MIN_LEVEL:
            continue
        exp = e.get("expires")
        if exp and exp < sent.isoformat():
            continue
        return True
    return False


def _settled(tools, account_id, instrument_id, as_of):
    iso = as_of.isoformat()
    splits = [a for a in tools.get_corporate_actions(instrument_id) if a.get("type") == "split"]
    total = 0
    for tr in tools.get_ledger(account_id, instrument_id):
        if tr["date"] > iso:
            continue
        q = tr["qty"]
        for s in splits:
            if tr["date"] < s["date"] <= iso:
                q *= s["ratio"]
        total += q
    return total


def _pending(tools, account_id, instrument_id, as_of):
    iso = as_of.isoformat()
    qty, last = 0, None
    for ins in tools.get_instructions(account_id, instrument_id):
        if ins.get("status") != "matched":
            continue
        if ins["settle_date"] <= iso:
            continue
        qty += ins["qty"]
        if last is None or ins["settle_date"] > last:
            last = ins["settle_date"]
    return qty, last


def respond(request, tools):
    sender = (request.get("from") or "").strip().lower()
    sent = dt.date.fromisoformat(str(request.get("sent"))[:10])
    mentions = request.get("mentions") or {}
    body = _strip_noise(request.get("body") or "")
    domain = sender.split("@")[-1]

    # 1. Unverifiable sender (personal mailbox) -> ask for client authorization.
    if domain in FREEMAIL:
        return _empty("REQUEST_AUTHORIZATION")

    # 2. Account must resolve to exactly one account.
    acc_text = mentions.get("account_text")
    if not acc_text:
        m = re.search(r"\b(?:ACC|SA)-\d{4,}\b", body)
        acc_text = m.group(0) if m else None
    acc_hits = _resolve_account(tools, acc_text)
    if not acc_hits or len(acc_hits) != 1:
        return _empty("REQUEST_INFO")
    account_id = acc_hits[0]["id"]

    # 3. Sender must be from a client domain and hold a live entitlement of sufficient level.
    if not _authorized(tools, sender, account_id, sent):
        return _empty("REQUEST_AUTHORIZATION")

    # 4. Instrument and date must be identifiable.
    ins_text = mentions.get("instrument_text")
    if not ins_text:
        m = re.search(r"\b[A-Z]{2}\d{9}[0-9]\b", body)
        ins_text = m.group(0) if m else None
    ins_hits = _resolve_instrument(tools, ins_text)
    if not ins_hits or len(ins_hits) != 1:
        return _empty("REQUEST_INFO")
    instrument_id = ins_hits[0]["id"]
    req_date, assumed = parse_date(body, sent)
    if req_date is None:
        return _empty("REQUEST_INFO")
    if req_date > sent:
        return _empty("REQUEST_INFO")

    res = _empty("ESCALATE")
    res["account_id"] = account_id
    res["instrument_id"] = instrument_id

    # 5. Client restrictions -> escalate.
    prof = tools.get_client_profile(account_id) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return res

    as_of = _biz_on_or_before(tools, req_date)
    settled = _settled(tools, account_id, instrument_id, as_of)
    pend, pend_date = _pending(tools, account_id, instrument_id, as_of)

    # 6. Reconcile with the client's figure, if given.
    client_qty = parse_qty(body)
    if client_qty is not None:
        def close(ours):
            base = max(abs(ours), abs(client_qty), 1)
            return abs(ours - client_qty) / base <= TOLERANCE
        if not (close(settled) or (pend and close(settled + pend))):
            return res

    res["as_of"] = as_of.isoformat()
    res["as_of_assumed"] = bool(assumed)
    if settled <= 0 and not pend:
        res["outcome"] = "NOT_HELD"
        res["settled"] = 0
        return res
    res["outcome"] = "CONFIRMED" if settled > 0 else "NOT_HELD"
    res["settled"] = settled
    if pend:
        res["pending"] = pend
        res["pending_date"] = pend_date
    return res
