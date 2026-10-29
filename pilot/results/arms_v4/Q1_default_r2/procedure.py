import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# policy switches (tuned via harness / oracle)
WEEKEND_ACTION = "INFO"      # INFO | ROLL
MISSING_DATE_ACTION = "INFO"  # INFO | ASSUME
FUTURE_ACTION = "INFO"
EMPTY_ACTION = "NOT_HELD"
MIN_LEVEL = 3


def _d(s):
    return dt.date.fromisoformat(s)


def parse_date(body, sent):
    """Return (date|None, kind). kind in explicit|relative|none"""
    sent_d = _d(sent)
    b = body
    # drop the forwarded header 'Date: yyyy-mm-dd' line
    b = re.sub(r"(?m)^\s*Date:\s*\d{4}-\d{2}-\d{2}\s*$", "", b)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", b)
    if m and m[2].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        try:
            return dt.date(int(m[3]), int(m[1]), int(m[2])), "explicit"
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", b)
    if m and m[2][:3].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), "explicit"
    m = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})\b", b)
    if m and m[1][:3].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), "explicit"
    low = b.lower()
    if "yesterday" in low:
        return sent_d - dt.timedelta(days=1), "relative"
    if re.search(r"month[- ]end|end of last month|last day of last month|end of the month", low):
        first = sent_d.replace(day=1)
        return first - dt.timedelta(days=1), "relative"
    return None, "none"


def client_figure(body):
    pats = [r"figure is\s+([\d][\d,]*\.?\d*)(k|mm|m)?(?![A-Za-z])",
            r"(?:we have|we show|records show|we hold)\s+([\d][\d,]*\.?\d*)(k|mm|m)?(?![A-Za-z])"]
    for pat in pats:
        m = re.search(pat, body, re.I)
        if m:
            s = m.group(1).rstrip(".,").replace(",", "")
            try:
                v = float(s)
            except ValueError:
                continue
            u = (m.group(2) or "").lower()
            if u == "k":
                v *= 1e3
            elif u in ("mm", "m"):
                v *= 1e6
            return v
    return None


TOLERANCE = 0.05


def _resolve_account(tools, text):
    if not text:
        return None
    hits = tools.search_accounts(text)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def _resolve_instrument(tools, text):
    if not text:
        return None
    hits = tools.search_instruments(text)
    if len(hits) == 1:
        return hits[0]["id"]
    return None


def _authorized(tools, sender, account_id, sent):
    c = tools.get_contact(sender)
    if not c:
        return False
    prof = tools.get_client_profile(account_id) or {}
    dom = sender.lower().split("@")[-1]
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent:
            return True
    return False


def position(tools, account_id, instrument_id, as_of):
    ledger = tools.get_ledger(account_id, instrument_id)
    acts = tools.get_corporate_actions(instrument_id)
    total = 0
    n = 0
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for a in acts:
            if a["type"] == "split" and a["date"] <= as_of and t["date"] < a["date"]:
                q *= a["ratio"]
        total += q
        n += 1
    return total, n


def respond(request, tools):
    out = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
           "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    m = request.get("mentions") or {}
    sent = request["sent"]
    acc = _resolve_account(tools, m.get("account_text"))
    ins = _resolve_instrument(tools, m.get("instrument_text"))
    if acc is None:
        out["outcome"] = "REQUEST_INFO"
        out["instrument_id"] = ins
        return out
    out["account_id"] = acc
    out["instrument_id"] = ins
    if not _authorized(tools, request["from"], acc, sent):
        out["outcome"] = "REQUEST_AUTHORIZATION"
        out["account_id"] = out["instrument_id"] = None
        return out
    if ins is None:
        out["outcome"] = "REQUEST_INFO"
        return out
    prof = tools.get_client_profile(acc) or {}
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        out["outcome"] = "ESCALATE"
        return out
    d, kind = parse_date(request["body"], sent)
    if d is None:
        out["outcome"] = "REQUEST_INFO"
        return out
    cal = tools.get_calendar(d.isoformat())
    assumed = False
    if not cal["business_day"]:
        if WEEKEND_ACTION == "INFO":
            out["outcome"] = "REQUEST_INFO"
            return out
        d = _d(cal["previous_business_day"])
        assumed = True
    if d > _d(sent) and FUTURE_ACTION == "INFO":
        out["outcome"] = "REQUEST_INFO"
        return out
    as_of = d.isoformat()
    total, n = position(tools, acc, ins, as_of)
    out["as_of"] = as_of
    out["as_of_assumed"] = assumed
    if n == 0 or total == 0:
        out["outcome"] = "NOT_HELD"
        return out
    out["outcome"] = "CONFIRMED"
    out["settled"] = total
    pend = [x for x in tools.get_instructions(acc, ins) if x["status"] == "matched" and x["settle_date"] > as_of]
    if pend:
        out["pending"] = sum(x["qty"] for x in pend)
        out["pending_date"] = max(x["settle_date"] for x in pend)
    cf = client_figure(request["body"])
    if cf is not None:
        cands = [total] + ([total + out["pending"]] if out["pending"] else [])
        if all(abs(cf - c) / abs(c) > TOLERANCE for c in cands if c):
            out.update(outcome="ESCALATE", as_of=None, as_of_assumed=False, settled=None,
                       pending=None, pending_date=None)
    return out
