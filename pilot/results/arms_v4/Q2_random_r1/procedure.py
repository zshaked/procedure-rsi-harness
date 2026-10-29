import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"


def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _prev_bd(tools, d):
    return dt.date.fromisoformat(tools.get_calendar(d.isoformat())["previous_business_day"])


def _to_bd(tools, d):
    c = tools.get_calendar(d.isoformat())
    if c["business_day"]:
        return d
    return dt.date.fromisoformat(c["previous_business_day"])


def _parse_date(body, sent):
    """Return (date or None). None means no date was given."""
    t = body
    # iso
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2]))
    m = re.search(r"\b(\d{1,2})-" + MON_RE + r"-(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1]))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON_RE + r",?\s+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1]))
    m = re.search(r"\b" + MON_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        return dt.date(int(m[3]), MONTHS[m[1].lower()[:3]], int(m[2]))
    low = t.lower()
    first = sent.replace(day=1)
    if re.search(r"end of last month|last day of (the )?last month|end of the previous month|last month-end|"
                 r"previous month-end|month[- ]end|end of (the )?month", low):
        return first - dt.timedelta(days=1)
    if "yesterday" in low:
        return sent - dt.timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return sent
    return None


def _parse_qty(s, suf):
    v = float(s.replace(",", ""))
    suf = (suf or "").lower()
    if suf == "k":
        v *= 1000
    elif suf in ("mm", "m"):
        v *= 1000000
    return int(round(v))


def _stated(body):
    m = re.search(r"(?:we show|records show|figure is|we have|show)\s*:?\s*(\d[\d,]*(?:\.\d+)?)\s*(mm|k|m)?\b", body, re.I)
    if m:
        return _parse_qty(m[1], m[2])
    return None


def _clean(s):
    return s.strip().rstrip(".,;:") if s else s


def _resolve_account(tools, text):
    if not text:
        return None
    r = tools.search_accounts(_clean(text))
    if len(r) == 1:
        return r[0]["id"]
    return None


def _resolve_instrument(tools, text):
    if not text:
        return None
    r = tools.search_instruments(_clean(text))
    if len(r) == 1:
        return r[0]["id"]
    return None


def _authorized(tools, request, acct, sent):
    sender = request["from"].strip().lower()
    prof = tools.get_client_profile(acct)
    if not prof:
        return False
    dom = sender.split("@")[-1]
    if dom not in [d.lower() for d in prof["domains"]]:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    ok = False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == acct and e["level"] >= 2 and e["expires"] >= sent.isoformat():
            ok = True
    return ok


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    body = re.sub(r"-{3,} Forwarded message -{3,}\s*\nFrom:[^\n]*\nDate:[^\n]*\n", "", request["body"])
    m = request.get("mentions") or {}
    acct = _resolve_account(tools, m.get("account_text"))
    inst = _resolve_instrument(tools, m.get("instrument_text"))
    if not acct:
        return _blank("REQUEST_INFO")
    if not _authorized(tools, request, acct, sent):
        return _blank("REQUEST_AUTHORIZATION")
    if not inst:
        return _blank("REQUEST_INFO")
    prof = tools.get_client_profile(acct)

    d = _parse_date(body, sent)
    assumed = d is None
    if assumed:
        d = sent
    d = _to_bd(tools, d)
    iso = d.isoformat()

    out = _blank("CONFIRMED")
    out.update(account_id=acct, instrument_id=inst, as_of=iso, as_of_assumed=assumed)

    if prof["legal_hold"] or prof["no_email_confirm"]:
        out["outcome"] = "ESCALATE"
        return out

    ledger = tools.get_ledger(acct, inst)
    splits = [a for a in tools.get_corporate_actions(inst) if a["type"] == "split"]
    total = 0
    for t in ledger:
        if t["date"] <= iso:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= iso:
                    q *= s["ratio"]
            total += q

    stated = _stated(body)
    if stated is not None and stated != total:
        out["outcome"] = "ESCALATE"
        out["settled"] = total
        return out

    if not ledger or total == 0:
        out["outcome"] = "NOT_HELD"
        return out

    out["settled"] = total
    pend = [x for x in tools.get_instructions(acct, inst) if x["status"] == "matched" and x["settle_date"] > iso]
    if pend:
        out["pending"] = sum(x["qty"] for x in pend)
        out["pending_date"] = max(x["settle_date"] for x in pend)
    return out
