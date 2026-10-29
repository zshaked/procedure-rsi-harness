import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
FULL = ["january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december"]
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

PEND_MIN_QTY = 1000  # de-minimis: tiny matched instructions are not reported (Q18/Q20)


def _mon(s):
    return MONTHS[s[:3].lower()]


def _d(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _body(request):
    b = request.get("body") or ""
    # drop forwarded header block
    b = re.sub(r"-{5,} Forwarded message -{5,}\s*\nFrom:[^\n]*\nDate:[^\n]*\n", "", b)
    # drop disclaimer
    b = re.sub(r"This email and any attachments.*", "", b, flags=re.S)
    return b


def parse_date(body, sent):
    """Return (date or None, assumed_flag_unused). Looks for explicit then relative dates."""
    t = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _d(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})-" + MON_RE + r"-(\d{4})\b", t, re.I)
    if m:
        return _d(int(m[3]), _mon(m[2]), int(m[1]))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON_RE + r"\w*,?\s+(\d{4})\b", t, re.I)
    if m:
        return _d(int(m[3]), _mon(m[2]), int(m[1]))
    m = re.search(r"\b" + MON_RE + r"\w*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        return _d(int(m[3]), _mon(m[1]), int(m[2]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _d(int(m[3]), int(m[1]), int(m[2]))
    s = dt.date.fromisoformat(sent)
    low = t.lower()
    if re.search(r"(last day of (the )?(last|previous) month|end of (the )?(last|previous) month|month[- ]end|end of month|last day of the month|end of last month)", low):
        first = s.replace(day=1)
        return first - dt.timedelta(days=1)
    if "yesterday" in low:
        return s - dt.timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return s
    return None


def parse_qty(body):
    m = re.search(r"(?:records show|figure is|we show|we have|show)\s+(-?[\d,]*\.?\d+)\s*(k|mm|m)?\b", body, re.I)
    if not m:
        return None
    raw = m[1].replace(",", "")
    try:
        v = float(raw)
    except ValueError:
        return None
    suf = (m[2] or "").lower()
    if suf == "k":
        v *= 1000
    elif suf in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def _resolve_account(text, tools):
    if not text:
        return None, "none"
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    if len(hits) == 0:
        return None, "none"
    return None, "ambiguous"


def _resolve_instrument(text, tools):
    if not text:
        return None, "none"
    hits = tools.search_instruments(text)
    ids = sorted(set(h["id"] for h in hits))
    if len(ids) == 1:
        return ids[0], "ok"
    if not ids:
        return None, "none"
    return None, "ambiguous"


def _prev_bd(d, tools):
    return dt.date.fromisoformat(tools.get_calendar(d.isoformat())["previous_business_day"])


def _is_bd(d, tools):
    return tools.get_calendar(d.isoformat())["business_day"]


def respond(request, tools):
    sent = request["sent"]
    sdate = dt.date.fromisoformat(sent)
    men = request.get("mentions") or {}
    base = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    def out(o, **kw):
        r = dict(base); r["outcome"] = o; r.update(kw); return r

    acc, astat = _resolve_account(men.get("account_text"), tools)
    if astat == "ambiguous":
        return out("REQUEST_INFO")

    # authorization
    contact = tools.get_contact(request["from"])
    authorized = False
    if acc and contact:
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["level"] >= 3 and e["expires"] >= sent:
                authorized = True
    if astat == "none" or not authorized:
        return out("REQUEST_AUTHORIZATION")

    ins, istat = _resolve_instrument(men.get("instrument_text"), tools)
    if istat != "ok":
        return out("REQUEST_INFO")

    prof = tools.get_client_profile(acc) or {}
    if prof.get("no_email_confirm"):
        return out("REQUEST_AUTHORIZATION")
    body = _body(request)
    d = parse_date(body, sent)
    assumed = False
    if d is None:
        d = sdate
        assumed = True
    if d > sdate or not _is_bd(d, tools):
        return out("REQUEST_INFO")
    asof = d.isoformat()

    # settled figure from raw ledger (all sub-accounts), split adjusted
    ledger = tools.get_ledger(acc, ins)
    splits = tools.get_corporate_actions(ins)
    total = 0
    for t in ledger:
        if t["date"] <= asof:
            q = t["qty"]
            for sp in splits:
                if t["date"] < sp["date"] <= asof:
                    q *= sp["ratio"]
            total += q

    if prof.get("legal_hold"):
        return out("ESCALATE", account_id=acc, instrument_id=ins)

    if total == 0:
        return out("NOT_HELD", account_id=acc, instrument_id=ins, as_of=asof, as_of_assumed=assumed)

    stated = parse_qty(body)
    if stated is not None and stated != total:
        return out("ESCALATE", account_id=acc, instrument_id=ins)

    pend = 0; pdate = None
    for x in tools.get_instructions(acc, ins):
        if x["status"] == "matched" and x["settle_date"] > asof and x["qty"] >= PEND_MIN_QTY:
            pend += x["qty"]
            if pdate is None or x["settle_date"] < pdate:
                pdate = x["settle_date"]
    return out("CONFIRMED", account_id=acc, instrument_id=ins, as_of=asof, as_of_assumed=assumed,
               settled=total, pending=pend or None, pending_date=pdate if pend else None)
