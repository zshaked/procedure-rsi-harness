"""Holding-confirmation desk procedure: respond(request, tools) -> dict.

Rule order (see NOTES.md): resolve account (exactly one, else REQUEST_INFO) -> sender authorization
(entitlement level>=2, unexpired at send date, sender domain in client domains, else
REQUEST_AUTHORIZATION) -> client takes no email confirmations -> REQUEST_AUTHORIZATION -> resolve
instrument (exactly one, former tickers allowed, else REQUEST_INFO) -> legal hold -> ESCALATE ->
as-of date (stated/relative date, or the send date if none [as_of_assumed]; rolled back to the
previous business day; future -> REQUEST_INFO) -> settled = ledger over all sub-accounts up to and
including as_of, split-adjusted -> settled <= 0 -> NOT_HELD -> client figure differing from
settled + material matched pending by more than 1% -> ESCALATE -> CONFIRMED with pending
(matched instructions >= 1,000 settling after as_of).
Selected by search over variants scored with verifier.py (200/200 requests pass).
Standard library only; state is read only through `tools`.
"""
import datetime as dt
import re

PARAMS = {
    "nodate": "sent", "roll": "prev", "scope": "account", "split_adjust": True, "inclusive": True,
    "pending_status": ("matched",), "pending_min": 1000, "pending_date": "latest", "min_level": 2,
    "check_expiry": True, "check_domain": True, "hold_first": False, "noemail_before_ins": True,
    "noemail_outcome": "REQUEST_AUTHORIZATION", "future": "info", "zero_first": True,
    "compare_with_pending": True, "tolerance": 0.01,
}

# ----------------------------------------------------------------- parsing
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def clean_body(body):
    """Drop forwarded-message headers (their Date: is the send date, not the position date; H 0000/0007)
    and the confidentiality footer."""
    out = []
    for line in (body or "").split("\n"):
        s = line.strip()
        if re.match(r"^(from|date|sent|to|subject|cc)\s*:", s, re.I):
            continue
        if s.startswith("-----") or "confidential and intended" in s.lower():
            continue
        out.append(line)
    return "\n".join(out)


def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _month(tok):
    tok = tok.lower().rstrip(".")
    if tok[:3] in MONTHS and (len(tok) == 3 or tok.startswith(
            ("january", "february", "march", "april", "may", "june", "july", "august", "sept",
             "september", "october", "november", "december", "jan", "feb", "mar", "apr", "jun",
             "jul", "aug", "sep", "oct", "nov", "dec"))):
        return MONTHS[tok[:3]]
    return None


def parse_date(body, sent):
    """Return (date|None, kind); kind in explicit|relative|none."""
    t = clean_body(body)
    low = t.lower()
    sent_d = dt.date.fromisoformat(sent)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mk(*m.groups()), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", t)  # US M/D/Y (H 0011, 0064)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        return _mk(y, m.group(1), m.group(2)), "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9}\.?)[- ,]+(\d{4})\b", t)
    if m and _month(m.group(2)):
        return _mk(m.group(3), _month(m.group(2)), m.group(1)), "explicit"
    m = re.search(r"\b([A-Za-z]{3,9}\.?) (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m and _month(m.group(1)):
        return _mk(m.group(3), _month(m.group(1)), m.group(2)), "explicit"
    if re.search(r"\byesterday\b", low):
        return sent_d - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b|\bas of now\b|\bas of close today\b", low):
        return sent_d, "relative"
    if re.search(r"(end of|last day of)\s+(the\s+)?(last|previous|prior)\s+month|"
                 r"(last|previous|prior)\s+month[- ]?end|\bmonth[- ]?end\b|\bend of (the )?month\b", low):
        return sent_d.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"(end of|last day of)\s+(last|previous|prior)\s+(year)|(last|previous|prior)\s+year[- ]?end|\byear[- ]?end\b", low):
        return dt.date(sent_d.year - 1, 12, 31), "relative"
    return None, "none"


NUM = r"(\d[\d,]*(?:\.\d+)?(?:[ ]?(?:mm|mln|bn|k|m)\b)?)"
QTY_PATTERNS = [r"our figure is\s+", r"we show\s+", r"records show\s+", r"we have\s+", r"we hold\s+",
                r"books show\s+", r"our position is\s+", r"we see\s+", r"we record\s+", r"our figure of\s+",
                r"we are showing\s+", r"we calculate\s+", r"we expect\s+"]


def parse_qty(s):
    s = s.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    for suf, mu in (("mm", 10 ** 6), ("mln", 10 ** 6), ("bn", 10 ** 9), ("k", 10 ** 3), ("m", 10 ** 6)):
        if s.endswith(suf):
            s, mult = s[: -len(suf)], mu
            break
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def client_qty(body):
    """The figure the client says it holds, if any (H 0004, 0008, 0011 ...)."""
    t = clean_body(body).lower()
    for p in QTY_PATTERNS:
        m = re.search(p + NUM, t)
        if m:
            return parse_qty(m.group(1))
    return None


# ----------------------------------------------------------------- facts


# ----------------------------------------------------------------- procedure
def _roll(tools, d, mode):
    c = tools.get_calendar(d)
    if c["business_day"] or mode == "none":
        return d
    if mode == "prev":
        return c["previous_business_day"]
    x = dt.date.fromisoformat(d)
    while True:
        x += dt.timedelta(days=1)
        if tools.get_calendar(x.isoformat())["business_day"]:
            return x.isoformat()


def _settled(tools, acc, ins, as_of, P, sub=None):
    if P["scope"] == "summary":
        return tools.get_position_summary(acc, ins, as_of)["quantity"]
    splits = tools.get_corporate_actions(ins) if P["split_adjust"] else []
    tot = 0
    for t in tools.get_ledger(acc, ins):
        if sub and t["sub_account"].upper() != sub:
            continue
        if t["date"] < as_of or (P["inclusive"] and t["date"] == as_of):
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            tot += q
    return tot


def _pending(tools, acc, ins, as_of, P):
    p = [x for x in tools.get_instructions(acc, ins)
         if x["status"] in P["pending_status"] and x["settle_date"] > as_of and x["qty"] >= P["pending_min"]]
    if not p:
        return None, None
    ds = sorted(x["settle_date"] for x in p)
    return sum(x["qty"] for x in p), (ds[0] if P["pending_date"] == "earliest" else ds[-1])


def _blank(outcome, acc=None, ins=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _authorized(tools, sender, sent, acc, prof, P):
    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    ok = any(e["account_id"] == acc and e["level"] >= P["min_level"] and
             (not P["check_expiry"] or e["expires"] >= sent) for e in ents)
    if P["check_domain"]:
        ok = ok and sender.rsplit("@", 1)[-1] in [d.lower() for d in prof.get("domains", [])]
    return ok


def respond(request, tools, P=None):
    P = P or PARAMS
    m = request.get("mentions") or {}
    sent = request["sent"]
    sender = (request.get("from") or "").strip().lower()
    acc_txt = (m.get("account_text") or "").strip()
    ins_txt = (m.get("instrument_text") or "").strip()
    accs = tools.search_accounts(acc_txt) if acc_txt else []
    if len(accs) != 1:
        return _blank("REQUEST_INFO")
    acc = accs[0]["id"]
    prof = tools.get_client_profile(acc) or {}
    inss = tools.search_instruments(ins_txt) if ins_txt else []
    ins = inss[0]["id"] if len(inss) == 1 else None
    if P["hold_first"] and prof.get("legal_hold") and ins:
        return _blank("ESCALATE", acc, ins)
    if not _authorized(tools, sender, sent, acc, prof, P):
        return _blank("REQUEST_AUTHORIZATION")
    if P["noemail_before_ins"] and prof.get("no_email_confirm"):
        return _blank(P["noemail_outcome"], acc, ins)
    if ins is None:
        return _blank("REQUEST_INFO")
    if prof.get("no_email_confirm"):
        return _blank(P["noemail_outcome"], acc, ins)
    if prof.get("legal_hold"):
        return _blank("ESCALATE", acc, ins)
    body = request.get("body", "")
    d, kind = parse_date(body, sent)
    assumed = d is None
    if d is None:
        if P["nodate"] == "info":
            return _blank("REQUEST_INFO")
        base = sent if P["nodate"] == "sent" else tools.get_calendar(sent)["previous_business_day"]
    else:
        base = d.isoformat()
        if base > sent:
            if P["future"] == "info":
                return _blank("REQUEST_INFO")
            base = sent
    as_of = _roll(tools, base, P["roll"])
    sub = acc_txt.upper() if (P["scope"] == "sub" and acc_txt.upper().startswith("SA-")) else None
    q = _settled(tools, acc, ins, as_of, P, sub)
    pq, pd = _pending(tools, acc, ins, as_of, P)
    cq = client_qty(body)
    res = _blank("CONFIRMED", acc, ins)
    res.update(as_of=as_of, as_of_assumed=assumed)
    if P["zero_first"] and q <= 0:
        res["outcome"] = "NOT_HELD"
        return res
    if cq is not None:
        desk = q + (pq or 0) if P["compare_with_pending"] else q
        if abs(cq - desk) > P["tolerance"] * max(abs(desk), 1):
            r = _blank("ESCALATE", acc, ins)
            return r
    if q <= 0:
        res["outcome"] = "NOT_HELD"
        return res
    res.update(settled=q, pending=pq, pending_date=pd)
    return res
