import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
NOPOS = {}


def _d(s):
    return dt.date.fromisoformat(s)


def _lastday_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent_s):
    """Return (kind, date|None). kind in none|explicit|relative|bad."""
    sent = _d(sent_s)
    b = body
    # drop forwarded header "Date: 2026-01-28"
    b = re.sub(r"(?m)^Date:.*$", "", b)
    b = re.sub(r"(?m)^From:.*$", "", b)
    seg = None
    for m in re.finditer(r"(?:as of|as at|position date)\s*,?\s*(?:close of business\s+)?([^\n]*)", b, re.I):
        seg = m.group(1)
        break
    if seg is None:
        return "none", None
    s = seg.strip()
    sl = s.lower()
    if sl.startswith("yesterday"):
        return "relative", sent - dt.timedelta(days=1)
    if re.match(r"(month-end|end of last month|the last day of last month|last day of last month|the end of last month)", sl):
        return "relative", _lastday_prev_month(sent)
    mm = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if mm:
        return "explicit", dt.date(int(mm[1]), int(mm[2]), int(mm[3]))
    mm = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if mm:
        return "explicit", dt.date(int(mm[3]), int(mm[1]), int(mm[2]))
    mm = re.match(r"(?:[A-Za-z]{3,9},?\s+)?(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]\s*(\d{4})", s)
    if mm and mm[2][:3].lower() in MONTHS:
        return "explicit", dt.date(int(mm[3]), MONTHS[mm[2][:3].lower()], int(mm[1]))
    mm = re.match(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if mm and mm[1][:3].lower() in MONTHS:
        return "explicit", dt.date(int(mm[3]), MONTHS[mm[1][:3].lower()], int(mm[2]))
    return "bad", None


def _resolve_account(text, tools):
    if not text:
        return None
    hits = tools.search_accounts(text.strip())
    if len(hits) != 1:
        return None
    return hits[0]["id"]


def _resolve_instrument(text, tools):
    if not text:
        return None
    hits = tools.search_instruments(text.strip())
    if len(hits) != 1:
        return None
    return hits[0]["id"]


def _base(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


FIG = re.compile(r"(?:our figure is|we have|we show|our records show|our records indicate|our books show|we are showing|we're showing)\s+(\d[\d,]*(?:\.\d+)?)\s*(mm|k|m)?\b", re.I)
TOL = 0.05


def stated_figure(body):
    m = FIG.search(body)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    mult = {"mm": 1_000_000, "m": 1_000_000, "k": 1000}.get((m.group(2) or "").lower(), 1)
    return round(n * mult)


def decide(request, tools):
    m = request.get("mentions") or {}
    sent = _d(request["sent"])
    acc = _resolve_account(m.get("account_text"), tools)
    if acc is None:
        return _base("REQUEST_INFO"), "account_unresolved"
    contact = tools.get_contact(request["from"])
    prof = tools.get_client_profile(acc) or {"domains": [], "legal_hold": False, "no_email_confirm": False}
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    mine = [e for e in ents if e["account_id"] == acc]
    if not mine:
        return _base("REQUEST_INFO"), "no_entitlement"
    good = [e for e in mine if e["level"] >= 3 and _d(e["expires"]) >= sent]
    domain = request["from"].split("@")[-1].lower()
    if not good:
        return _base("REQUEST_AUTHORIZATION"), "auth_level"
    if domain not in [d.lower() for d in prof["domains"]]:
        return _base("REQUEST_AUTHORIZATION"), "auth_domain"
    ins = _resolve_instrument(m.get("instrument_text"), tools)
    if ins is None:
        return _base("REQUEST_INFO", acc), "instrument_unresolved"
    try:
        kind, d = parse_date(request["body"], request["sent"])
    except Exception:
        kind, d = "bad", None
    if kind in ("none", "bad"):
        return _base("REQUEST_INFO", acc, ins), "date_missing"
    if d > sent:
        return _base("REQUEST_INFO", acc, ins), "date_future"
    cal = tools.get_calendar(d.isoformat())
    if not cal["business_day"]:
        return _base("REQUEST_INFO", acc, ins), "date_nonbusiness"
    asof = d.isoformat()
    if prof.get("legal_hold"):
        return _base("ESCALATE", acc, ins), "legal_hold"
    if prof.get("no_email_confirm"):
        return _base("ESCALATE", acc, ins), "no_email_confirm"
    led = tools.get_ledger(acc, ins)
    splits = tools.get_corporate_actions(ins)
    settled = 0
    for t in led:
        if t["date"] <= asof:
            q = t["qty"]
            for s in splits:
                if s["date"] <= asof and t["date"] < s["date"]:
                    q *= s["ratio"]
            settled += q
    if settled == 0:
        return _base("NOT_HELD", acc, ins, asof, False), "not_held"
    pend = [x for x in tools.get_instructions(acc, ins) if x["status"] == "matched" and x["settle_date"] > asof]
    pq = sum(x["qty"] for x in pend) or None
    pd = max((x["settle_date"] for x in pend), default=None)
    fig = stated_figure(request["body"])
    if fig is not None:
        ok = abs(fig - settled) <= TOL * abs(settled) or (pq and abs(fig - (settled + pq)) <= TOL * (settled + pq))
        if not ok:
            return _base("ESCALATE", acc, ins), "figure_mismatch"
    return _base("CONFIRMED", acc, ins, asof, False, settled, pq, pd), "confirmed"


def respond(request, tools):
    return decide(request, tools)[0]
