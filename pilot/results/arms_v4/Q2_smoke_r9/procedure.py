"""Operations-desk procedure: confirm a client's holding of a security.

Deterministic; standard library + the `tools` argument only.

Decision cascade
  1. Identify account and security from the extracted mentions; ambiguous / missing -> REQUEST_INFO.
  2. Sender must be a known contact, write from a domain registered to the client, and hold an
     unexpired entitlement of level >= 2 on that account; else REQUEST_AUTHORIZATION.
  3. Legal hold on the account -> ESCALATE.
  4. Position = ledger summed over every custody sub-account up to the (business-day) as-of date,
     restated for splits already effective at that date.  If the client quoted a figure that does
     not agree -> ESCALATE.
  5. Zero position -> NOT_HELD, otherwise CONFIRMED (with matched, not-yet-settled instructions
     reported as pending).
"""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
            r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _mon(s):
    return MONTHS[s[:3].lower()]


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _prev_month_end(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _strip_body(body):
    """Remove forwarded-message header and trailing disclaimer."""
    b = (body or "").replace("\r", "")
    b = re.sub(r"-{3,}\s*Forwarded message\s*-{3,}\s*\n(?:(?:From|Date|Sent|To|Cc|Subject):[^\n]*\n)+", "", b,
               flags=re.I)
    b = re.split(r"\n\s*This email and any attachments", b, flags=re.I)[0]
    return b


# ------------------------------------------------------------------ dates
def _date_candidates(b, sent_d):
    """All date expressions in b as (start, end, date, kind)."""
    out = []

    def add(m, d, kind):
        if d:
            out.append((m.start(), m.end(), d, kind))

    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b):
        add(m, _safe_date(int(m[1]), int(m[2]), int(m[3])), "explicit")
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", b):
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        add(m, _safe_date(y, int(m[1]), int(m[2])), "explicit")
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s]+" + MONTH_RE + r"\.?[-\s,]+(\d{4})\b", b, flags=re.I):
        add(m, _safe_date(int(m[3]), _mon(m[2]), int(m[1])), "explicit")
    for m in re.finditer(MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b, flags=re.I):
        add(m, _safe_date(int(m[3]), _mon(m[1]), int(m[2])), "explicit")
    # day + month without a year
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MONTH_RE + r"\b(?![\s,.-]*\d{4})", b, flags=re.I):
        d = _safe_date(sent_d.year, _mon(m[2]), int(m[1]))
        if d and d > sent_d:
            d = _safe_date(sent_d.year - 1, _mon(m[2]), int(m[1]))
        add(m, d, "explicit")
    for m in re.finditer(MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?![\s,.-]*\d{4})(?!:)", b, flags=re.I):
        d = _safe_date(sent_d.year, _mon(m[1]), int(m[2]))
        if d and d > sent_d:
            d = _safe_date(sent_d.year - 1, _mon(m[1]), int(m[2]))
        add(m, d, "explicit")

    low = b.lower()

    def rel(pattern, fn):
        for m in re.finditer(pattern, low):
            add(m, fn(m), "relative")

    pme = _prev_month_end(sent_d)
    rel(r"\b(?:the\s+)?(?:last|final)\s+(?:calendar\s+|business\s+|working\s+)?day\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+month\b",
        lambda m: pme)
    rel(r"\bend\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+month\b", lambda m: pme)
    rel(r"\b(?:last|previous|prior)\s+month[-\s]?end\b", lambda m: pme)
    rel(r"\bmonth[-\s]?end\b", lambda m: pme)
    rel(r"\bend\s+of\s+(?:the\s+)?month\b", lambda m: pme)
    rel(r"\bend\s+of\s+(?:last|previous|prior)\s+week\b",
        lambda m: sent_d - dt.timedelta(days=sent_d.weekday() + 3))
    rel(r"\b(?:end\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+quarter|(?:last|previous|prior)\s+quarter[-\s]?end|quarter[-\s]?end)\b",
        lambda m: dt.date(sent_d.year, 3 * ((sent_d.month - 1) // 3) + 1, 1) - dt.timedelta(days=1))
    rel(r"\b(?:year[-\s]?end|end\s+of\s+(?:the\s+)?(?:last|previous|prior)\s+year|end\s+of\s+(?:the\s+)?year)\b",
        lambda m: dt.date(sent_d.year - 1, 12, 31))
    rel(r"\bthe\s+day\s+before\s+yesterday\b", lambda m: sent_d - dt.timedelta(days=2))
    rel(r"(?<!before )\byesterday\b", lambda m: sent_d - dt.timedelta(days=1))
    rel(r"\b(\d+)\s+(?:calendar\s+)?days?\s+ago\b", lambda m: sent_d - dt.timedelta(days=int(m[1])))
    rel(r"\b(?:last|previous)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        lambda m: sent_d - dt.timedelta(days=((sent_d.weekday() - WEEKDAYS[m[1][:3]] - 1) % 7) + 1))
    rel(r"\b(?:today|close of business today|as of now)\b", lambda m: sent_d)
    return out


def parse_date(body, sent):
    """Return (date|None, kind) with kind in explicit / relative / none."""
    b = _strip_body(body)
    sent_d = dt.date.fromisoformat(sent)
    cands = sorted(_date_candidates(b, sent_d), key=lambda x: x[0])
    if not cands:
        return None, "none"
    cue = re.compile(r"(?:as\s+of|as\s+at|position\s+date|dated?|on)\b[^0-9A-Za-z]{0,3}"
                     r"(?:the\s+|close\s+of\s+business\s+|cob\s+)*", re.I)
    for m in cue.finditer(b):
        for s, e, d, k in cands:
            if m.end() - 1 <= s <= m.end() + 30:
                return d, k
    return cands[0][2], cands[0][3]


def business_day_on_or_before(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


# ------------------------------------------------------------------ quantities
_NUM = r"\d[\d,]*(?:\.\d+)?\s?(?:mm|k|m)?\b"


def _num(s):
    """Return (value, tolerance) for strings like 12,500 / 12500 / 12.5k / 1.2mm."""
    s = s.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    if s.endswith("mm"):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    tol = 0
    if mult > 1:
        dec = len(s.split(".")[1]) if "." in s else 0
        tol = 0.5 * mult / (10 ** dec)
    return int(round(v * mult)), tol


def stated_figure(body):
    """The holding figure the client quotes, as (value, tolerance) or None."""
    b = _strip_body(body)
    pats = [
        r"(?:we|they)\s+(?:currently\s+)?(?:show|have|hold|see|list|record)\s+(?:a\s+(?:figure|position|balance)\s+of\s+)?(" + _NUM + r")",
        r"(?:our|the)\s+(?:records|books|figure|balance|position)\s+(?:show|shows|is|are|of|says?|reads?)\s+(?:a\s+(?:figure|position|balance)\s+of\s+)?(" + _NUM + r")",
        r"(?:records|books)\s+(?:show|shows)\s+(" + _NUM + r")",
        r"figure\s+(?:of|is|shows?)\s+(" + _NUM + r")",
        r"(?:we|they)\s+are\s+(?:showing|carrying)\s+(" + _NUM + r")",
        r"(?:our|the)\s+(?:own\s+)?(?:records|books|ledger)\s+(?:indicate|reflect|list)s?\s+(" + _NUM + r")",
        r"(?:position|balance)\s+(?:of|is)\s+(" + _NUM + r")\s+(?:shares|units)",
    ]
    for p in pats:
        m = re.search(p, b, flags=re.I)
        if m:
            r = _num(m[1])
            if r:
                return r
    return None


# ------------------------------------------------------------------ lookups
def _clean(text):
    t = re.sub(r"\s+", " ", (text or "")).strip()
    return t.strip(" .,;:()[]\"'")


def _unique(hits):
    ids = sorted({h["id"] for h in hits})
    return ids[0] if len(ids) == 1 else None


_ACCT_PREFIX = re.compile(r"^(?:our\s+|the\s+)?(?:account|acct|a/c|fund|portfolio)\s+", re.I)


def resolve_account(text, tools):
    t = _clean(text)
    if not t:
        return None
    hits = tools.search_accounts(t)
    if not hits:
        t2 = _ACCT_PREFIX.sub("", t)
        m = re.search(r"\b(?:ACC|SA)-\d+\b", t2, flags=re.I)
        for cand in ([m[0]] if m else []) + [t2]:
            hits = tools.search_accounts(cand)
            if hits:
                break
    return _unique(hits)


def resolve_instrument(text, tools):
    t = _clean(text)
    if not t:
        return None
    hits = tools.search_instruments(t)
    if not hits:
        m = re.search(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", t.upper())
        for cand in ([m[0]] if m else []) + [re.sub(r"\s+(?:shares|stock|units)$", "", t, flags=re.I)]:
            hits = tools.search_instruments(cand)
            if hits:
                break
    if len(hits) > 1:  # prefer a current identifier over a former ticker
        cur = [h for h in hits if t.lower() in (h["ticker"].lower(), h["name"].lower(), h["id"].lower())]
        if cur:
            hits = cur
    return _unique(hits)


def _email(sender):
    m = re.search(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]+", sender or "")
    return (m[0] if m else (sender or "")).strip().lower()


def authorized(sender, account_id, sent, tools):
    sender = _email(sender)
    c = tools.get_contact(sender)
    if not c:
        return False
    prof = tools.get_client_profile(account_id)
    if not prof:
        return False
    dom = sender.split("@")[-1]
    domains = [d.lower() for d in prof.get("domains", [])]
    if not any(dom == d or dom.endswith("." + d) for d in domains):
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= 2 and e["expires"] >= sent:
            return True
    return False


def position(account_id, instrument_id, as_of, tools, adjust=True):
    """Settled quantity at as_of across all sub-accounts, restated for splits effective by then."""
    splits = [a for a in tools.get_corporate_actions(instrument_id) if a.get("type") == "split"]
    if not adjust:
        splits = []
    iso = as_of.isoformat()
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= iso and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q
    return total


def pending_info(account_id, instrument_id, as_of, tools):
    iso = as_of.isoformat()
    items = [x for x in tools.get_instructions(account_id, instrument_id)
             if x["status"] == "matched" and x["settle_date"] > iso]
    if not items:
        return None, None
    return sum(x["qty"] for x in items), max(x["settle_date"] for x in items)


# ------------------------------------------------------------------ main
def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:  # never crash on an odd email: ask for clarification
        return _blank("REQUEST_INFO")


def _respond(request, tools):
    m = request.get("mentions") or {}
    sent = request["sent"]
    acct = resolve_account(m.get("account_text"), tools)
    if not acct:
        return _blank("REQUEST_INFO")

    prof = tools.get_client_profile(acct) or {}
    if prof.get("no_email_confirm") or not authorized(request["from"], acct, sent, tools):
        return _blank("REQUEST_AUTHORIZATION")

    inst = resolve_instrument(m.get("instrument_text"), tools)
    if not inst:
        return _blank("REQUEST_INFO")

    d, _kind = parse_date(request.get("body", ""), sent)
    assumed = d is None
    if d is None:
        d = dt.date.fromisoformat(sent)
    as_of = business_day_on_or_before(d, tools)

    out = _blank("ESCALATE")
    out.update(account_id=acct, instrument_id=inst, as_of=as_of.isoformat(), as_of_assumed=assumed)

    if prof.get("legal_hold"):
        return out

    settled = position(acct, inst, as_of, tools)
    pend, pdate = pending_info(acct, inst, as_of, tools)
    stated = stated_figure(request.get("body", ""))
    out["settled"] = settled
    if settled == 0:  # nothing settled at that date -> not held, whatever the client believes
        out["outcome"] = "NOT_HELD"
        out["settled"] = None
        return out
    if settled < 0:
        return out
    # The client's figure is compared with the full position (settled plus matched pending).  A
    # figure that is merely stale across a split (quantities as originally recorded) is accepted too.
    if stated is not None:
        raw = position(acct, inst, as_of, tools, adjust=False)
        targets = {settled + (pend or 0), raw + (pend or 0)}
        if all(abs(stated[0] - t) > stated[1] for t in targets):
            return out
    out["outcome"] = "CONFIRMED"
    out["pending"] = pend
    out["pending_date"] = pdate
    return out
