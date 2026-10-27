"""Induced procedure for the holdings-confirmation desk. Deterministic, stdlib only."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com",
             "icloud.com", "aol.com", "live.com", "msn.com", "mail.com", "gmx.com"}


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


# ---------------------------------------------------------------- text helpers
def _clean_body(body):
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if s.startswith("-----") or s.lower().startswith("this email and any attachments"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _qty(tok):
    t = tok.strip().lower().replace(",", "").replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)(k|thousand|mm|mn|m|million|bn|b|billion)?$", t)
    if not m:
        return None
    v = float(m.group(1))
    mult = {None: 1, "k": 1e3, "thousand": 1e3, "mm": 1e6, "mn": 1e6, "m": 1e6, "million": 1e6,
            "bn": 1e9, "b": 1e9, "billion": 1e9}[m.group(2)]
    return int(round(v * mult))


_NUM = r"(\d[\d,]*(?:\.\d+)?\s?(?:k|thousand|mm|mn|million|m|bn|billion)?)\b"


def _client_figure(text):
    pats = [
        r"figure\s+(?:is|of|shows?)\s*:?\s*" + _NUM,
        r"(?:records|books|ledger|system|statement)s?\s+(?:show|shows|reflect|reflects|indicate|indicates|have|has)\s*:?\s*" + _NUM,
        r"\bwe\s+(?:show|have|hold|see|record|expect|carry)\s*:?\s*" + _NUM,
        r"\b(?:our|the)\s+(?:position|holding|balance)\s+(?:is|of|shows?)\s*:?\s*" + _NUM,
        _NUM + r"\s*(?:shares|units|sh)\b[^.\n]*\b(?:books|records)",
        r"\b(?:holding|position|balance)\s+of\s+" + _NUM + r"\s*(?:shares|units)",
    ]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            q = _qty(m.group(1))
            if q is not None:
                return q
    return None


# ---------------------------------------------------------------- dates
def _iso(d):
    return d.isoformat()


def _mk(y, mo, d):
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def _month_end(d):
    first = d.replace(day=1)
    return first - dt.timedelta(days=1)  # last day of previous month


def _pick_year(mo, d, sent):
    for y in (sent.year, sent.year - 1):
        c = _mk(y, mo, d)
        if c and c <= sent:
            return c
    return _mk(sent.year, mo, d)


def _find_dates(text, sent):
    """Return list of (pos, date) found in text."""
    out = []
    mon = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        c = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if c: out.append((m.start(), c))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text):
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        c = _mk(y, int(m.group(1)), int(m.group(2)))
        if c is None:
            c = _mk(y, int(m.group(2)), int(m.group(1)))
        if c: out.append((m.start(), c))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?" + mon + r"[\s\-,]+(\d{4})\b", text, re.I):
        c = _mk(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        if c: out.append((m.start(), c))
    for m in re.finditer(r"\b" + mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text, re.I):
        c = _mk(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        if c: out.append((m.start(), c))
    taken = [p for p, _ in out]
    # year-less forms
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?" + mon + r"\b(?![\s\-,]+\d{4})", text, re.I):
        if any(abs(m.start() - p) < 3 for p in taken): continue
        c = _pick_year(MONTHS[m.group(2)[:3].lower()], int(m.group(1)), sent)
        if c: out.append((m.start(), c))
    for m in re.finditer(r"\b" + mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!,?\s+\d{4})(?!\d)", text, re.I):
        if any(abs(m.start() - p) < 3 for p in taken): continue
        c = _pick_year(MONTHS[m.group(1)[:3].lower()], int(m.group(2)), sent)
        if c: out.append((m.start(), c))
    low = text.lower()
    rel = [
        (r"\b(?:the\s+)?day before yesterday\b", lambda: sent - dt.timedelta(days=2)),
        (r"\byesterday\b", lambda: sent - dt.timedelta(days=1)),
        (r"\btoday\b|\bthis morning\b|\bclose of business today\b", lambda: sent),
        (r"\b(?:end of|last day of)\s+(?:last|the previous|previous|prior)\s+month\b|\blast month[\s\-]?end\b|\bprevious month[\s\-]?end\b|\bprior month[\s\-]?end\b|\bmonth[\s\-]?end\b|\bend of month\b|\beom\b",
         lambda: _month_end(sent)),
        (r"\b(?:end of|last day of)\s+(?:last|the previous|previous|prior)\s+year\b|\byear[\s\-]?end\b|\bend of year\b",
         lambda: dt.date(sent.year - 1, 12, 31)),
        (r"\b(?:end of|last day of)\s+(?:last|the previous|previous|prior)\s+quarter\b|\bquarter[\s\-]?end\b",
         lambda: _quarter_end(sent)),
    ]
    for p, f in rel:
        m = re.search(p, low)
        if m and not any(abs(m.start() - q) < 2 for q, _ in out):
            out.append((m.start(), f()))
    m = re.search(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(m.group(1))
        d = sent - dt.timedelta(days=1)
        while d.weekday() != wd:
            d -= dt.timedelta(days=1)
        out.append((m.start(), d))
    for mo_name, mo_i in MONTHS.items():
        pass
    m = re.search(r"\b(?:end of|last day of)\s+" + mon + r"(?:\s+(\d{4}))?\b", low)
    if m:
        mi = MONTHS[m.group(1)[:3]]
        y = int(m.group(2)) if m.group(2) else (sent.year if mi < sent.month else sent.year - 1)
        nxt = dt.date(y + (mi == 12), mi % 12 + 1, 1)
        out.append((m.start(), nxt - dt.timedelta(days=1)))
    out.sort(key=lambda x: x[0])
    return out


def _quarter_end(sent):
    q_start_month = 3 * ((sent.month - 1) // 3) + 1
    return dt.date(sent.year, q_start_month, 1) - dt.timedelta(days=1)


def _requested_date(text, sent):
    ds = _find_dates(text, sent)
    if not ds:
        return None
    anchors = [m.end() for m in re.finditer(r"as\s+(?:of|at)|position\s+date|close\s+of\s+business|\bcob\b|\bdated?\b|\bon\b", text, re.I)]
    best = None
    for pos, d in ds:
        for a in anchors:
            if 0 <= pos - a <= 40:
                return d
        if best is None:
            best = d
    return best


# ---------------------------------------------------------------- resolution
def _resolve_account(text, tools):
    if not text:
        return None, "missing"
    t = text.strip().strip(".,;:()\"'")
    cands = [t]
    m = re.search(r"\b(ACC-\d+|SA-\d+)\b", t, re.I)
    if m:
        cands.insert(0, m.group(1).upper())
    stripped = re.sub(r"^(?:our\s+|the\s+)?(?:account|acct\.?|a/c|fund|portfolio)\s+", "", t, flags=re.I).strip()
    if stripped and stripped != t:
        cands.append(stripped)
    for c in cands:
        hits = tools.search_accounts(c)
        if len(hits) == 1:
            return hits[0]["id"], None
        if len(hits) > 1:
            return None, "ambiguous"
    return None, "unknown"


def _resolve_instrument(text, tools):
    if not text:
        return None, "missing"
    t = text.strip().strip(".,;:()\"'")
    cands = [t]
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", t)
    if m:
        cands.insert(0, m.group(1))
    s2 = re.sub(r"\b(?:shares?|stock|common|ordinary|units?)\b", "", t, flags=re.I).strip()
    if s2 and s2 != t:
        cands.append(s2)
    for c in cands:
        hits = tools.search_instruments(c)
        ids = sorted({h["id"] for h in hits})
        if len(ids) == 1:
            return ids[0], None
        if len(ids) > 1:
            return None, "ambiguous"
    return None, "unknown"


def _authorized(sender, account_id, sent, tools):
    sender = (sender or "").strip().lower()
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    prof = tools.get_client_profile(account_id) or {}
    domains = [d.lower() for d in prof.get("domains", [])]
    if not domain or domain in FREE_MAIL or domain not in domains:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e.get("account_id") != account_id:
            continue
        try:
            lvl = int(e.get("level") or 0)
        except (TypeError, ValueError):
            lvl = 0
        exp = e.get("expires")
        if lvl >= 2 and (not exp or exp >= _iso(sent)):
            return True
    return False


def _roll_back(date_iso, tools):
    cal = tools.get_calendar(date_iso)
    return date_iso if cal["business_day"] else cal["previous_business_day"]


# ---------------------------------------------------------------- main
def respond(request, tools):
    sent = dt.date.fromisoformat(str(request.get("sent"))[:10])
    mentions = request.get("mentions") or {}
    body = _clean_body(request.get("body") or "")
    text = (request.get("subject") or "") + "\n" + body

    acc, aerr = _resolve_account(mentions.get("account_text"), tools)
    ins, ierr = _resolve_instrument(mentions.get("instrument_text"), tools)
    if acc is None or ins is None:
        return _out("REQUEST_INFO")

    req_date = _requested_date(body, sent)
    assumed = req_date is None
    if req_date is not None and req_date > sent:
        return _out("REQUEST_INFO")

    if not _authorized(request.get("from"), acc, sent, tools):
        return _out("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(acc) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", acc, ins)

    if req_date is None or req_date >= sent:
        as_of = tools.get_calendar(_iso(sent))["previous_business_day"]
    else:
        as_of = _roll_back(_iso(req_date), tools)

    # settled position: all custody sub-accounts, split-adjusted
    splits = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    settled = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q = q * s["ratio"]
        settled += q
    settled = int(round(settled))

    if settled < 0:
        return _out("ESCALATE", acc, ins)

    figure = _client_figure(body)
    if figure is not None and figure != settled:
        return _out("ESCALATE", acc, ins)

    pend = [x for x in tools.get_instructions(acc, ins)
            if x.get("status") == "matched" and x.get("settle_date", "") > as_of]
    pending = sum(x["qty"] for x in pend) if pend else None
    pdate = max(x["settle_date"] for x in pend) if pend else None

    if settled == 0:
        return _out("NOT_HELD", acc, ins, as_of, assumed, None, pending, pdate)
    return _out("CONFIRMED", acc, ins, as_of, assumed, settled, pending, pdate)
