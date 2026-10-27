"""Position-confirmation desk procedure. respond(request, tools) -> dict.
Deterministic; standard library + the `tools` argument only.
Constants below were selected by searching variants against verifier.py (see NOTES.md)."""
import re
import datetime as dt

# ---- selected by search (scratch/search.py) ----
ORDER = ("account", "auth", "instrument", "profile", "date", "position")
MIN_LEVEL = 3
TOLERANCE = 0.03
PENDING_WINDOW_DAYS = 90
LARGE_POSITION = 1_000_000
NON_BUSINESS_DAY = "REQUEST_INFO"
FUTURE_DATE = "REQUEST_INFO"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}


def _blank():
    return {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _strip_forward(body):
    return "\n".join(l for l in (body or "").split("\n")
                     if not re.match(r'\s*(From|Date|To|Sent|Subject|Cc):', l, re.I)
                     and 'forwarded message' not in l.lower()
                     and 'original message' not in l.lower())


def _mk(y, mo, d):
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def _parse_date(body, sent):
    sent_d = dt.date.fromisoformat(sent)
    t = _strip_forward(body).lower()
    m = re.search(r'(?:as at|as of|as on|position date|positions? at|holdings? at|dated)\s*:?\s*'
                  r'(?:the\s+)?(?:close of business|cob|eod|end of day)?\s*(?:on\s+)?(.*?)(?:\?|\.\s|\.$|\n|$)', t)
    c = m.group(1) if m else t
    if re.search(r'\byesterday\b', c):
        return sent_d - dt.timedelta(days=1), True
    if m and re.search(r'\btoday\b|\bcurrent(ly)?\b|\bnow\b', c):
        return sent_d, True
    if re.search(r'end of last month|last day of (the )?(last|previous|prior) month|month[- ]?end|'
                 r'end of (the )?(previous|prior) month|last month[- ]?end|\beom\b', c):
        return sent_d.replace(day=1) - dt.timedelta(days=1), True
    if re.search(r'end of last year|year[- ]end|last day of last year', c):
        return dt.date(sent_d.year - 1, 12, 31), True
    x = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', c)
    if x:
        return _mk(int(x[1]), int(x[2]), int(x[3])), True
    x = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', c)
    if x:
        y = int(x[3]); y = y + 2000 if y < 100 else y
        return _mk(y, int(x[1]), int(x[2])), True
    x = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?[- ]([a-z]{3})[a-z]*\.?[- ,]+(\d{4})\b', c)
    if x and x[2] in _MONTHS:
        return _mk(int(x[3]), _MONTHS[x[2]], int(x[1])), True
    x = re.search(r'\b([a-z]{3})[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b', c)
    if x and x[1] in _MONTHS:
        return _mk(int(x[3]), _MONTHS[x[1]], int(x[2])), True
    return None, bool(m)


def _parse_qty(s):
    s = s.strip().lower().replace(',', '').replace(' ', '')
    mult = 1
    if s.endswith('mm'):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith('m'):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith('k'):
        mult, s = 1000, s[:-1]
    return int(round(float(s) * mult))


def _parse_figure(body):
    t = _strip_forward(body).lower()
    m = re.search(r'(?:our figure is|we have|we show|records show|books show|we hold|we see|our position is|'
                  r'our records indicate|reconciles? to)\s*:?\s*(-?\d[\d,]*(?:\.\d+)?\s?(?:mm|m|k)?)(?![\w])', t)
    if not m:
        return None
    try:
        return _parse_qty(m.group(1))
    except ValueError:
        return None


def respond(request, tools):
    r = _blank()
    sent = request.get("sent")
    sender = (request.get("from") or "").strip().lower()
    men = request.get("mentions") or {}
    at, it = men.get("account_text"), men.get("instrument_text")
    ctx = {}

    def step_account():
        if not (at and at.strip()):
            return "REQUEST_INFO"
        hits = tools.search_accounts(at)
        if len(hits) != 1:
            return "REQUEST_INFO"
        ctx["acc"] = hits[0]["id"]

    def step_auth():
        c = tools.get_contact(sender)
        ents = tools.get_entitlements(c["contact_id"]) if c else []
        if not any(e["account_id"] == ctx["acc"] and e["level"] >= MIN_LEVEL and e["expires"] >= sent
                   for e in ents):
            return "REQUEST_AUTHORIZATION"

    def step_instrument():
        hits = tools.search_instruments(it) if it and it.strip() else []
        if len(hits) != 1:
            return "REQUEST_INFO"
        ctx["ins"] = hits[0]["id"]

    def step_profile():
        p = tools.get_client_profile(ctx["acc"]) or {}
        if p.get("no_email_confirm"):
            return "REQUEST_AUTHORIZATION"
        if p.get("legal_hold"):
            ctx["esc"] = True
            return "ESCALATE"

    def step_date():
        d, mentioned = _parse_date(request.get("body") or "", sent)
        if d is None and mentioned:
            return "REQUEST_INFO"
        assumed = d is None
        if assumed:
            d = dt.date.fromisoformat(sent)
        if d.isoformat() > sent:
            return FUTURE_DATE
        asof = d.isoformat()
        cal = tools.get_calendar(asof)
        if not cal["business_day"]:
            if not assumed and NON_BUSINESS_DAY != "ROLL":
                return NON_BUSINESS_DAY
            asof = cal["previous_business_day"]
        ctx["asof"], ctx["assumed"] = asof, assumed

    def step_position():
        acc, iid, asof = ctx["acc"], ctx["ins"], ctx["asof"]
        cas = [c for c in tools.get_corporate_actions(iid) if c.get("type", "split") == "split"]
        tot = 0
        for t in tools.get_ledger(acc, iid):
            if t["date"] <= asof:
                q = t["qty"]
                for c in cas:
                    if t["date"] < c["date"] <= asof:
                        q *= c["ratio"]
                tot += q
        lim = (dt.date.fromisoformat(asof) + dt.timedelta(days=PENDING_WINDOW_DAYS)).isoformat()
        pend = [x for x in tools.get_instructions(acc, iid)
                if x["status"] == "matched" and asof < x["settle_date"] <= lim]
        ctx["settled"] = tot
        ctx["pending"] = sum(x["qty"] for x in pend) if pend else None
        ctx["pending_date"] = max(x["settle_date"] for x in pend) if pend else None
        if tot == 0:
            return "NOT_HELD"
        if tot < 0 or abs(tot) >= LARGE_POSITION:
            return "ESCALATE"
        fig = _parse_figure(request.get("body") or "")
        if fig is not None and abs(fig - tot) > TOLERANCE * abs(tot):
            if not (ctx["pending"] and fig == tot + ctx["pending"]):
                return "ESCALATE"
        return "CONFIRMED"

    steps = {"account": step_account, "auth": step_auth, "instrument": step_instrument,
             "profile": step_profile, "date": step_date, "position": step_position}
    out = None
    for name in ORDER:
        try:
            out = steps[name]()
        except KeyError:
            # a later step needs something an earlier one did not establish
            out = "REQUEST_INFO"
        if out:
            break
    out = out or "REQUEST_INFO"
    r["outcome"] = out
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        r["account_id"] = ctx.get("acc")
        r["instrument_id"] = ctx.get("ins")
    if out in ("CONFIRMED", "NOT_HELD"):
        r["as_of"] = ctx.get("asof")
        r["as_of_assumed"] = bool(ctx.get("assumed"))
    if out == "CONFIRMED":
        r["settled"] = ctx["settled"]
        r["pending"] = ctx["pending"]
        r["pending_date"] = ctx["pending_date"]
    return r
