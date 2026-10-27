"""Induced procedure for the position-confirmation desk."""
import calendar
import datetime as dt
import re

PERSONAL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com",
            "live.com", "protonmail.com", "me.com", "msn.com", "mail.com", "gmx.com"}
MIN_LEVEL = 2
TOLERANCE = 0.10

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WD_RE = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+)?"


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- text cleanup
def _clean_body(body):
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if re.match(r"^-+\s*(forwarded|original) message", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if re.search(r"confidential and intended solely", s, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


# ---------------------------------------------------------------- dates
def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_date(text, sent):
    """Returns (date|None, assumed:bool)."""
    t = text.lower()
    # explicit ISO
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), False
    # 17-Jan-2026 / 17 Jan 2026 / Sat 3 Jan 2026 / 22 December 2025
    m = re.search(r"\b" + WD_RE + r"(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+" + MON_RE + r"\.?,?[\s\-/]+(\d{2,4})\b", t)
    if m:
        return _mk(_year(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1))), False
    # January 27, 2026 / Jan 27 2026
    m = re.search(r"\b" + WD_RE + MON_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m:
        return _mk(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2))), False
    # 1/23/2026 (US)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        d = _mk(y, a, b) if a <= 12 else _mk(y, b, a)
        return d, False
    # dates without year: "3 March", "March 3"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + MON_RE + r"\b", t) or None
    if m:
        d = _mk(sent.year, MONTHS[m.group(2)[:3]], int(m.group(1)))
        if d and d > sent:
            d = _mk(sent.year - 1, d.month, d.day)
        return d, True
    m = re.search(r"\b" + MON_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m:
        d = _mk(sent.year, MONTHS[m.group(1)[:3]], int(m.group(2)))
        if d and d > sent:
            d = _mk(sent.year - 1, d.month, d.day)
        return d, True
    # relative phrases
    if re.search(r"\byesterday\b", t):
        return sent - dt.timedelta(days=1), False
    if re.search(r"\btoday\b|\bcurrent(ly)?\b|\bas of now\b", t):
        return sent, False
    if re.search(r"(last|end of|close of|final)\s+(business\s+|trading\s+)?(day\s+of\s+)?(last|previous|prior)\s+month"
                 r"|(last|previous|prior)\s+month[- ]?end|end of (last|previous|prior) month", t):
        return _last_day_prev_month(sent), False
    if re.search(r"month[- ]?end|end of (the )?month|\beom\b", t):
        return _last_day_prev_month(sent), True
    m = re.search(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(m.group(1))
        d = sent - dt.timedelta(days=1)
        while d.weekday() != wd:
            d -= dt.timedelta(days=1)
        return d, False
    if re.search(r"(year[- ]?end|end of (last )?year)", t):
        return dt.date(sent.year - 1, 12, 31), False
    return None, False


# ---------------------------------------------------------------- quantities
def parse_qty(s):
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mm|m|k|bn)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"k": 1e3, "m": 1e6, "mm": 1e6, "bn": 1e9, None: 1}[m.group(2)]
    return int(round(v * mult))


def client_figure(text):
    t = text.lower()
    num = r"(\d[\d,]*(?:\.\d+)?\s*(?:mm|bn|k|m)?)\b"
    pats = [r"records show\s+" + num, r"we show\s+" + num, r"we have\s+" + num,
            r"our figure is\s+" + num, r"we hold\s+" + num, r"books show\s+" + num,
            r"(?:figure|position|holding|balance) of\s+" + num, r"we see\s+" + num,
            r"we expect\s+" + num, r"should be\s+" + num]
    for p in pats:
        m = re.search(p, t)
        if m:
            q = parse_qty(m.group(1))
            if q is not None:
                return q
    return None


# ---------------------------------------------------------------- entity resolution
PREFIX_RE = re.compile(r"^(?:(?:our|the|my)\s+)?(?:account|acct|a/c|fund|portfolio|ac)(?:\.|:|#|\s)+(?:(?:no\.|number|#)\s*)?[:#]?\s*", re.I)


def _norm_mention(s):
    if not s:
        return None
    s = s.strip().strip(".,;:()[]\"'")
    s = PREFIX_RE.sub("", s).strip().strip(".,;:()[]\"'")
    return s or None


def resolve_account(tools, text, body):
    q = _norm_mention(text)
    if not q:
        m = re.search(r"\b(ACC-\d+|SA-\d+)\b", body, re.I)
        q = m.group(1) if m else None
    if not q:
        return None, "missing"
    raw = (text or "").strip()
    hits = tools.search_accounts(raw) if raw else []
    if len(hits) != 1:
        hits = tools.search_accounts(q)
    if not hits:
        m = re.search(r"\b(ACC-\d+|SA-\d+)\b", q, re.I)
        if m:
            hits = tools.search_accounts(m.group(1))
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    return None, ("ambiguous" if hits else "unknown")


def resolve_instrument(tools, text, body):
    q = _norm_mention(text)
    if not q:
        m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", body)
        q = m.group(1) if m else None
    if not q:
        return None, "missing"
    hits = tools.search_instruments(q)
    if not hits:
        m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", q)
        if m:
            hits = tools.search_instruments(m.group(1))
    if len(hits) > 1:
        cur = [h for h in hits if h["ticker"].lower() == q.lower() or h["id"].lower() == q.lower()]
        if len(cur) == 1:
            hits = cur
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    return None, ("ambiguous" if hits else "unknown")


# ---------------------------------------------------------------- figures
def settled_qty(tools, acc, ins, as_of):
    ledger = tools.get_ledger(acc, ins)
    splits = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    total = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        total += q
    return ledger, total


def pending_qty(tools, acc, ins, as_of):
    xs = [x for x in tools.get_instructions(acc, ins)
          if x.get("status") == "matched" and x["settle_date"] > as_of]
    if not xs:
        return None, None
    return sum(x["qty"] for x in xs), max(x["settle_date"] for x in xs)


def business_day(tools, d):
    c = tools.get_calendar(d.isoformat())
    return d.isoformat() if c["business_day"] else c["previous_business_day"]


# ---------------------------------------------------------------- main
def respond(request, tools):
    sender = (request.get("from") or "").strip().lower()
    m = re.search(r"<([^>]+)>", sender)
    if m:
        sender = m.group(1)
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    sent = dt.date.fromisoformat(str(request.get("sent"))[:10])
    body = _clean_body(request.get("body") or "")
    subject = request.get("subject") or ""
    mentions = request.get("mentions") or {}

    # 1. sender must write from a recognised corporate domain and be a known contact
    contact = tools.get_contact(sender) if sender else None
    if not domain or domain in PERSONAL or contact is None:
        return _out("REQUEST_AUTHORIZATION")

    # 2. account / instrument / date must be identifiable
    acc, acc_st = resolve_account(tools, mentions.get("account_text"), body)
    ins, ins_st = resolve_instrument(tools, mentions.get("instrument_text"), body + "\n" + subject)
    req_date, assumed = parse_date(body, sent)
    if acc is None or ins is None or req_date is None or req_date > sent:
        return _out("REQUEST_INFO")

    # 3. authorization: valid entitlement (level >= 2) and sender domain belongs to the client
    profile = tools.get_client_profile(acc) or {}
    ents = [e for e in tools.get_entitlements(contact["contact_id"])
            if e["account_id"] == acc and e["expires"] >= sent.isoformat() and e["level"] >= MIN_LEVEL]
    if not ents or domain not in [d.lower() for d in profile.get("domains", [])]:
        return _out("REQUEST_AUTHORIZATION")
    if profile.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    if profile.get("legal_hold"):
        return _out("ESCALATE", account_id=acc, instrument_id=ins)

    # 4. as-of date: previous business day if not a business day; today's figure is not final
    if req_date == sent:
        as_of = tools.get_calendar(sent.isoformat())["previous_business_day"]
        assumed = True
    else:
        as_of = business_day(tools, req_date)

    ledger, settled = settled_qty(tools, acc, ins, as_of)
    if not ledger:
        # no record of this security in the account at all: cannot locate the position
        return _out("REQUEST_INFO")

    fig = client_figure(body)
    pend, pend_date = pending_qty(tools, acc, ins, as_of)
    if fig is not None:
        cands = [settled] + ([settled + pend] if pend else [])
        ok = any((c == fig) or (c != 0 and abs(fig - c) <= TOLERANCE * abs(c)) for c in cands)
        if not ok:
            return _out("ESCALATE", account_id=acc, instrument_id=ins)

    if settled <= 0:
        return _out("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed,
                    settled=None)
    return _out("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed,
                settled=settled, pending=pend, pending_date=pend_date)
