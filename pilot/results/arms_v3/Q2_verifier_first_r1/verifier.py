"""Reference-free verifier for the holding-confirmation desk.

verify(request, response, tools) -> (ok: bool, failures: list[str])

Each check below is independent and documents the evidence it is based on
(H = histories case, O = oracle answer recorded in NOTES.md, T = tool docstring).
The verifier recomputes the facts it needs through `tools` only.
"""
import datetime as dt
import re

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}

# Conventions that calibration may flip (see NOTES.md for the oracle evidence).
CFG = {
    "nodate": "sent",                        # missing date -> the send date (rolled back if not a business day), as_of_assumed=True (O3/O4/O5)
    "subaccount_scope": "account",           # figure for a SA-xxx mention: whole account or just that sub-account
    "pending_date": "latest",
    "pending_min": 1000,                     # matched instructions under this size are ignored (O6-O10)
    "tolerance": 0.01,                       # relative tolerance when comparing the client's figure (O1: "closely enough")
    "future": "REQUEST_INFO",
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
def _roll(tools, d):
    c = tools.get_calendar(d)
    return d if c["business_day"] else c["previous_business_day"]


def settled_qty(tools, acc, ins, as_of, sub=None):
    """All custody sub-accounts (H 0004, 0021, 0022: figure = sum over sub-accounts, NOT
    get_position_summary which uses only the primary sub-account and the previous day),
    trades dated <= as_of, quantities recorded before a split dated <= as_of multiplied by its ratio (T)."""
    splits = tools.get_corporate_actions(ins)
    tot = 0
    for t in tools.get_ledger(acc, ins):
        if sub and t["sub_account"].upper() != sub:
            continue
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if s.get("type", "split") == "split" and t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            tot += q
    return tot


def pending_info(tools, acc, ins, as_of, cfg=CFG):
    """Matched instructions settling after as_of (H 0021); cancelled/unmatched excluded."""
    p = [x for x in tools.get_instructions(acc, ins)
         if x["status"] == "matched" and x["settle_date"] > as_of and x["qty"] >= cfg["pending_min"]]
    if not p:
        return None, None
    dates = sorted(x["settle_date"] for x in p)
    return sum(x["qty"] for x in p), (dates[0] if cfg["pending_date"] == "earliest" else dates[-1])


def expected(request, tools, cfg=CFG):
    """Derive the expected decision. Returns dict with outcome and, where applicable, fields."""
    m = request.get("mentions") or {}
    sent = request["sent"]
    sender = (request.get("from") or "").strip().lower()
    acc_txt = (m.get("account_text") or "").strip()
    ins_txt = (m.get("instrument_text") or "").strip()
    E = {"why": []}
    # 1. account must resolve to exactly one account (H 0002, 0005, 0023 ambiguous; H 0003 missing).
    #    A sub-account id resolves to its parent account (T search_accounts; H 0015).
    accs = tools.search_accounts(acc_txt) if acc_txt else []
    if len(accs) != 1:
        E.update(outcome="REQUEST_INFO"); E["why"].append("account unresolved/ambiguous"); return E
    acc = accs[0]["id"]
    prof = tools.get_client_profile(acc) or {}
    # 2. authorization: known contact, entitlement on this account, level>=2 (H 0018 level 1 refused,
    #    H 0001/0017 level 2 confirmed), not expired at send date (H 0009, unlabeled 0121), sender domain
    #    is one of the client's domains (H 0014: proton.me with a level-3 entitlement was refused).
    #    Checked before legal hold (O12: Q2-0081).
    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    dom = sender.rsplit("@", 1)[-1]
    ok = any(e["account_id"] == acc and e["level"] >= 2 and e["expires"] >= sent for e in ents) \
        and dom in [d.lower() for d in prof.get("domains", [])]
    if not ok:
        E.update(outcome="REQUEST_AUTHORIZATION"); E["why"].append("not authorized"); return E
    # 3. client that takes no email confirmations -> authorization route, even before the
    #    instrument is resolved (O15: Q2-0105 had no instrument)
    if prof.get("no_email_confirm"):
        E.update(outcome="REQUEST_AUTHORIZATION"); E["why"].append("no email confirmation"); return E
    # 4. instrument must resolve to exactly one instrument; former tickers are fine (O14: Q2-0053)
    inss = tools.search_instruments(ins_txt) if ins_txt else []
    if len(inss) != 1:
        E.update(outcome="REQUEST_INFO"); E["why"].append("instrument unresolved/ambiguous"); return E
    ins = inss[0]["id"]
    E["account_id"], E["instrument_id"] = acc, ins
    # 5. legal hold -> escalate (after authorization, O12)
    if prof.get("legal_hold"):
        E.update(outcome="ESCALATE"); E["why"].append("legal hold"); return E
    # 6. date: stated date rolled back to the previous business day (H 0017); relative dates from the
    #    send date; "month-end" = last month-end (O14); no date -> send date, as_of_assumed (O4/O5)
    d, kind = parse_date(request.get("body", ""), sent)
    assumed = False
    if d is None:
        assumed = True
        if cfg["nodate"] == "REQUEST_INFO":
            E.update(outcome="REQUEST_INFO"); E["why"].append("no date"); return E
        base = sent if cfg["nodate"] == "sent" else tools.get_calendar(sent)["previous_business_day"]
        as_of = _roll(tools, base)
    else:
        if d.isoformat() > sent and cfg["future"] == "REQUEST_INFO":   # unverified convention
            E.update(outcome="REQUEST_INFO"); E["why"].append("date in the future"); return E
        as_of = _roll(tools, min(d.isoformat(), sent))
    # 7. figure: whole account even when a sub-account was named (O11: Q2-0153)
    sub = acc_txt.upper() if (cfg["subaccount_scope"] == "sub" and acc_txt.upper().startswith("SA-")) else None
    q = settled_qty(tools, acc, ins, as_of, sub)
    cq = client_qty(request.get("body", ""))
    E.update(as_of=as_of, as_of_assumed=assumed, settled=q, client=cq)
    pq, pd = pending_info(tools, acc, ins, as_of, cfg)
    # 8. nothing settled -> NOT_HELD, even when the client quotes a figure (O13: Q2-0157)
    if q <= 0:
        E.update(outcome="NOT_HELD"); return E
    # 9. client's figure vs desk figure = settled + material matched pending (O1, O2, O10); mismatch -> escalate
    desk = q + (pq or 0)
    if cq is not None and abs(cq - desk) > cfg["tolerance"] * max(abs(desk), 1):
        E.update(outcome="ESCALATE"); E["why"].append("client figure %s != %s" % (cq, desk)); return E
    E.update(outcome="CONFIRMED", pending=pq, pending_date=pd)
    return E


# ----------------------------------------------------------------- checks
def verify(request, response, tools, cfg=CFG):
    fails = []
    r = response if isinstance(response, dict) else {}
    out = r.get("outcome")
    # C0 schema: outcome is one of the five; all keys present (README)
    if out not in OUTCOMES:
        return False, ["C0 outcome not in enum: %r" % (out,)]
    for k in ("account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date"):
        if k not in r:
            fails.append("C0 missing key " + k)
    E = expected(request, tools, cfg)
    # C1 outcome matches the decision derived from the rules
    if out != E["outcome"]:
        fails.append("C1 outcome %s, expected %s (%s)" % (out, E["outcome"], "; ".join(E["why"])))
        return False, fails
    # C2 ids filled for CONFIRMED/NOT_HELD/ESCALATE and equal to the resolved ones (README; H 0010 uses ACC id)
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        if r.get("account_id") != E.get("account_id"):
            fails.append("C2 account_id %r != %r" % (r.get("account_id"), E.get("account_id")))
        if r.get("instrument_id") != E.get("instrument_id"):
            fails.append("C2 instrument_id %r != %r" % (r.get("instrument_id"), E.get("instrument_id")))
    # C3 as_of: business day actually used (H 0017: Sat 31 Jan -> 30 Jan), as_of_assumed iff no date given
    if out in ("CONFIRMED", "NOT_HELD"):
        if r.get("as_of") != E.get("as_of"):
            fails.append("C3 as_of %r != %r" % (r.get("as_of"), E.get("as_of")))
        if bool(r.get("as_of_assumed")) != E.get("as_of_assumed"):
            fails.append("C3 as_of_assumed %r != %r" % (r.get("as_of_assumed"), E.get("as_of_assumed")))
    # C4 settled figure: all sub-accounts, split-adjusted, inclusive of as_of (H 0004, 0021, 0022; T)
    if out == "CONFIRMED" and r.get("settled") != E.get("settled"):
        fails.append("C4 settled %r != %r" % (r.get("settled"), E.get("settled")))
    if out != "CONFIRMED" and r.get("settled") not in (None, 0):
        fails.append("C4 settled reported for non-confirmation")
    # C5 pending: only matched instructions settling after as_of; date of settlement (H 0021)
    if out == "CONFIRMED":
        if r.get("pending") != E.get("pending") or r.get("pending_date") != E.get("pending_date"):
            fails.append("C5 pending %r/%r != %r/%r" % (r.get("pending"), r.get("pending_date"),
                                                       E.get("pending"), E.get("pending_date")))
    elif r.get("pending") not in (None, 0) or r.get("pending_date"):
        fails.append("C5 pending reported for non-confirmation")
    # C6 nothing about the position leaks on REQUEST_* outcomes (H 0000/0007 replies disclose nothing)
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION") and r.get("settled") is not None:
        fails.append("C6 figure disclosed without confirmation")
    return (not fails), fails
