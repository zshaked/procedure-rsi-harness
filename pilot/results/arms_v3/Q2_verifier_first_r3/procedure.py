"""Holding-confirmation desk procedure.  respond(request, tools) -> dict

Order of decisions (see NOTES.md):
 1. identify account + instrument uniquely, else REQUEST_INFO
 2. sender must hold an unexpired entitlement (level >= 2) on the account AND write from one of
    the client's registered domains, else REQUEST_AUTHORIZATION
 3. legal hold / no-email-confirm on the client profile -> ESCALATE
 4. position date: explicit / relative / none (-> email date, assumed); roll back to business day;
    a date after the email -> REQUEST_INFO
 5. settled = raw ledger over ALL sub-accounts up to as_of (inclusive), split-adjusted;
    pending = matched instructions settling after as_of (sum, latest date, split-adjusted)
 6. client figure (if any) must match settled+pending within 1%, else ESCALATE
 7. negative -> ESCALATE; zero -> NOT_HELD; else CONFIRMED
"""
import datetime as dt
import re

CONFIG = {
    "roll": "back",            # back: non-business day -> previous business day; 'prev': always prior bday
    "default_date": "sent",    # 'sent' | 'prev_bday'
    "pending_date": "max",     # 'max' | 'min'
    "pending_split": True,     # split-adjust pending across a split after as_of
    "compare": "total",        # 'total' (settled+pending) | 'settled'
    "tol": 0.01,
    "sub_only": False,         # named sub-account -> whole account (False) or that sub-account only
    "future": "REQUEST_INFO",
    "no_email_confirm": "ESCALATE",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


# ------------------------------------------------------------------ text helpers
def _clean_body(body):
    t = re.sub(r"-+ ?Forwarded message ?-+.*?Date:[^\n]*", " ", body, flags=re.S | re.I)
    t = re.sub(r"This email and any attachments.*", " ", t, flags=re.S | re.I)
    return t


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """-> (date|None, assumed: bool). Relative phrases are resolved against `sent`."""
    sent_d = dt.date.fromisoformat(sent)
    text = _clean_body(body)
    low = text.lower()
    # explicit dates first (most specific)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return d, False
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)
    if m:
        a, b, y = int(m[1]), int(m[2]), _year(m[3])
        d = _safe_date(y, a, b) if a <= 12 else _safe_date(y, b, a)   # US M/D/Y; D/M/Y if M>12
        if d:
            return d, False
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[\s\-]+" + MONTH_RE + r"\.?[\s\-,]+(\d{2,4})\b", low)
    if m:
        d = _safe_date(_year(m[3]), MONTHS[m[2][:3]], int(m[1]))
        if d:
            return d, False
    m = re.search(r"\b" + MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low)
    if m:
        d = _safe_date(int(m[3]), MONTHS[m[1][:3]], int(m[2]))
        if d:
            return d, False
    # relative phrases
    if re.search(r"\byesterday\b", low):
        return sent_d - dt.timedelta(days=1), False
    if re.search(r"\b(day before yesterday)\b", low):
        return sent_d - dt.timedelta(days=2), False
    if re.search(r"(end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|"
                 r"(last|previous|prior) month[- ]end|month[- ]end|end of month|\beom\b)", low):
        return _last_day_prev_month(sent_d), False
    if re.search(r"(end of (the )?(last|previous|prior) year|(last|previous|prior) year[- ]end|year[- ]end)", low):
        return dt.date(sent_d.year - 1, 12, 31), False
    if re.search(r"\b(today|this morning|close of business today|cob today)\b", low):
        return sent_d, False
    return None, True


def _qty(s):
    s = s.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    for suf, mu in (("mm", 1_000_000), ("mn", 1_000_000), ("m", 1_000_000), ("k", 1_000), ("bn", 10**9)):
        if s.endswith(suf):
            mult, s = mu, s[: -len(suf)]
            break
    try:
        val = float(s)
    except ValueError:
        return None, 0
    if mult == 1:
        return int(round(val)), 0
    decimals = len(s.split(".")[1]) if "." in s else 0
    return int(round(val * mult)), mult / (10 ** decimals) / 2   # rounding half-unit


NUM = r"(\d[\d,]*(?:\.\d+)?(?:\s?(?:mm|mn|bn|k|m)\b)?)"


def parse_figure(body):
    """Client's own figure if stated -> (qty|None, rounding_tolerance)."""
    text = _clean_body(body)
    pats = [
        r"(?:we show|our figure is|our records show|we have|we hold|our books show|our position is|"
        r"we see|our figure:|we record|we are showing|reconciles? to|our balance is)\s*(?:of\s*)?" + NUM,
        NUM + r"\s*(?:shares|units|sh\b)",
    ]
    for p in pats:
        m = re.search(p, text, flags=re.I)
        if m:
            q, ab = _qty(m[1])
            if q is not None:
                return q, ab
    return None, 0


# ------------------------------------------------------------------ resolution helpers
_ACC_PREFIX = r"^(?:our\s+)?(?:account|acct|a/c|fund|portfolio|the)\s*[:#]?\s*"


def _account_candidates(text):
    t = text.strip().strip(".,;:()\"'")
    out = [t]
    t2 = re.sub(_ACC_PREFIX, "", t, flags=re.I).strip()
    out.append(t2)
    m = re.search(r"\b(ACC)[\s\-_]?(\d{5})\b", t, flags=re.I)
    if m:
        out.append("ACC-" + m[2])
    m = re.search(r"\b(SA)[\s\-_]?(\d{6})\b", t, flags=re.I)
    if m:
        out.append("SA-" + m[2])
    seen, res = set(), []
    for c in out:
        if c and c.lower() not in seen:
            seen.add(c.lower())
            res.append(c)
    return res


def resolve_account(tools, text, body):
    if not text:
        m = re.search(r"\bACC-\d{5}\b|\bSA-\d{6}\b", _clean_body(body))
        if not m:
            return None, None
        text = m[0]
    for c in _account_candidates(text):
        hits = tools.search_accounts(c)
        if hits:
            if len(hits) != 1:
                return None, None
            sub = c.upper() if re.fullmatch(r"SA-\d+", c, flags=re.I) else None
            return hits[0]["id"], sub
    return None, None


def _instrument_candidates(text):
    t = text.strip().strip(".,;:()\"'")
    out = [t, t.lstrip("$")]
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", t.upper())
    if m:
        out.append(m[1])
    t2 = re.sub(r"\s+(us|equity|common|shares|stock|ordinary)\b.*$", "", t, flags=re.I)
    out.append(t2)
    return [c for c in dict.fromkeys(out) if c]


def resolve_instrument(tools, text, body):
    if not text:
        m = re.search(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", _clean_body(body))
        if not m:
            return None
        text = m[0]
    for c in _instrument_candidates(text):
        hits = tools.search_instruments(c)
        if hits:
            return hits[0]["id"] if len(hits) == 1 else None
    return None


def authorized(tools, sender, account_id, sent):
    contact = tools.get_contact(sender)
    if not contact:
        return False
    ok = any(e["account_id"] == account_id and e["level"] >= 2 and e["expires"] >= sent
             for e in tools.get_entitlements(contact["contact_id"]))
    prof = tools.get_client_profile(account_id) or {}
    domain = sender.split("@")[-1].lower()
    return ok and domain in [d.lower() for d in prof.get("domains", [])]


# ------------------------------------------------------------------ position maths
def settled_at(tools, acct, inst, as_of, sub=None):
    splits = [c for c in tools.get_corporate_actions(inst) if c.get("type") == "split"]
    tot = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > as_of or (sub and t["sub_account"].upper() != sub):
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        tot += q
    return tot


def pending_at(tools, acct, inst, as_of, cfg):
    splits = [c for c in tools.get_corporate_actions(inst) if c.get("type") == "split"]
    ins = [x for x in tools.get_instructions(acct, inst)
           if x["status"] == "matched" and x["settle_date"] > as_of]
    if not ins:
        return None, None
    tot = 0
    for x in ins:
        q = x["qty"]
        if cfg["pending_split"]:
            for s in splits:
                if as_of < s["date"] <= x["settle_date"]:
                    q *= s["ratio"]
        tot += q
    dates = [x["settle_date"] for x in ins]
    return tot, (max(dates) if cfg["pending_date"] == "max" else min(dates))


def _empty(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def respond(request, tools, cfg=None):
    cfg = dict(CONFIG, **(cfg or {}))
    m = request.get("mentions") or {}
    body = request.get("body") or ""
    sent = request["sent"]
    sender = (request.get("from") or "").strip().lower()
    m_ = re.search(r"<([^>]+)>", sender)
    if m_:
        sender = m_[1]

    acct, sub = resolve_account(tools, m.get("account_text"), body)
    inst = resolve_instrument(tools, m.get("instrument_text"), body)
    if not acct or not inst:
        return _empty("REQUEST_INFO")

    if not authorized(tools, sender, acct, sent):
        return _empty("REQUEST_AUTHORIZATION")

    def esc():
        r = _empty("ESCALATE")
        r["account_id"], r["instrument_id"] = acct, inst
        return r

    prof = tools.get_client_profile(acct) or {}
    if prof.get("legal_hold"):
        return esc()
    if prof.get("no_email_confirm"):
        return esc() if cfg["no_email_confirm"] == "ESCALATE" else _empty(cfg["no_email_confirm"])

    d, assumed = parse_date(body, sent)
    if d is None:
        d = dt.date.fromisoformat(sent)
        if cfg["default_date"] == "prev_bday":
            d = dt.date.fromisoformat(tools.get_calendar(sent)["previous_business_day"])
    if d > dt.date.fromisoformat(sent):
        return esc() if cfg["future"] == "ESCALATE" else _empty(cfg["future"])
    cal = tools.get_calendar(d.isoformat())
    if cfg["roll"] == "prev" or not cal["business_day"]:
        d = dt.date.fromisoformat(cal["previous_business_day"])
    as_of = d.isoformat()

    settled = settled_at(tools, acct, inst, as_of, sub if cfg["sub_only"] else None)
    pending, pdate = pending_at(tools, acct, inst, as_of, cfg)

    fig, abbreviated = parse_figure(body)
    if fig is not None:
        ours = settled + (pending or 0) if cfg["compare"] == "total" else settled
        tol = max(cfg["tol"] * max(abs(ours), 1), 0)
        tol = max(tol, abbreviated)  # "12.5k" / "1.2mm": allow the client's rounding
        if abs(fig - ours) > tol:
            return esc()
    if settled < 0:
        return esc()

    r = _empty("NOT_HELD" if settled == 0 else "CONFIRMED")
    r.update(account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
             pending=pending, pending_date=pdate)
    if settled != 0:
        r["settled"] = settled
    return r
