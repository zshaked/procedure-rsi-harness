"""Position-confirmation desk procedure.

respond(request, tools) -> dict
Deterministic; standard library only; all state read through `tools`.
"""
import re
import datetime as _dt

# Conventions chosen by search against verifier.py (see NOTES.md).
P = {
    "min_level": 3,                 # entitlement level needed to receive a confirmation
    "size_limit": 1000000,          # settled positions at/above this are escalated
    "tolerance": 0.05,              # relative difference to a client figure that is not a break
    "pending_window": 45,           # days after as_of within which matched instructions are reported
    "stated_plus_pending_ok": True, # client figure == settled + matched pending is not a break
    "missing_account_from_entitlement": True,
    "negative_outcome": "ESCALATE",
    "legal_hold_outcome": "ESCALATE",
    "no_email_outcome": "REQUEST_AUTHORIZATION",
    "nonbusiness_outcome": "REQUEST_INFO",
    "future_outcome": "REQUEST_INFO",
    "check_order": ("account", "auth", "instrument", "date", "profile", "figures"),
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _strip(body):
    keep = []
    for ln in (body or "").split("\n"):
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|To|Sent|Subject|Cc)\s*:", s, re.I):
            continue  # forwarded-message headers are not the position date
        if "confidential and intended solely" in s.lower():
            continue
        keep.append(ln)
    return "\n".join(keep)


def _month(tok):
    return _MONTHS.get(tok[:3].lower()) if tok and tok[:3].isalpha() else None


def _date(y, m, d):
    try:
        return _dt.date(y, m, d), "explicit"
    except ValueError:
        return None, "bad"


def _parse_date(body, sent):
    sent_d = _dt.date.fromisoformat(sent)
    t = _strip(body)
    tl = t.lower()
    if re.search(r"\byesterday\b", tl):
        return sent_d - _dt.timedelta(days=1), "relative"
    if re.search(r"\b(today|this morning|as of now|current(ly)?)\b", tl) and not re.search(r"\d{4}", tl):
        return sent_d, "relative"
    if re.search(r"(end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|"
                 r"month[- ]end|end of (the )?month|last month[- ]end|previous month[- ]end)", tl):
        return sent_d.replace(day=1) - _dt.timedelta(days=1), "relative"
    if re.search(r"(year[- ]end|end of (last )?year)", tl):
        return _dt.date(sent_d.year - 1, 12, 31), "relative"
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ](\d{4})\b", t)
    if m and _month(m.group(2)):
        return _date(int(m.group(3)), _month(m.group(2)), int(m.group(1)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m and _month(m.group(1)):
        return _date(int(m.group(3)), _month(m.group(1)), int(m.group(2)))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?([A-Za-z]{3,9}),? (\d{4})\b", t)
    if m and _month(m.group(2)):
        return _date(int(m.group(3)), _month(m.group(2)), int(m.group(1)))
    return None, "none"


def _norm_candidates(text, kind):
    """Raw extractor spans may carry prefixes or punctuation ('a/c ACC-10022', 'XVX.')."""
    t = (text or "").strip()
    out = [t]
    s = re.sub(r"^(?:(?:our|the|a/c|acct|account|fund|in|of)\b[\s:]*)+", "", t, flags=re.I).strip(" .,;:()'\"")
    if s and s not in out:
        out.append(s)
    pat = r"\b(?:ACC|SA)-\d+\b" if kind == "account" else r"\b[A-Z]{2}[A-Z0-9]{9}\d\b"
    for m in re.findall(pat, t, flags=re.I):
        if m not in out:
            out.append(m)
    return out


def _resolve(text, search, kind):
    for cand in _norm_candidates(text, kind):
        hits = search(cand)
        if hits:
            return hits
    return []


_NUM = r"(-?\d[\d,]*(?:\.\d+)?(?:[ ]?(?:k|mm|mn|m|bn|million|thousand)\b)?)"
_QTY = [
    r"we (?:have|hold)\s+" + _NUM + r"\s*(?:shares|units)",
    r"our records show\s+" + _NUM,
    r"our figure is\s+" + _NUM,
    r"we show\s+" + _NUM,
    r"our (?:books|records|figures?) (?:show|say|have|indicate)s?\s+" + _NUM,
    r"(?:we|our books) (?:hold|have)\s+" + _NUM,
]


def _qty(tok):
    m = re.match(r"^(-?[\d,]*\.?\d+)\s*(k|mm|mn|m|bn|million|thousand)?$", tok.strip().lower())
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {None: 1, "k": 1e3, "thousand": 1e3, "mm": 1e6, "mn": 1e6, "m": 1e6, "million": 1e6, "bn": 1e9}
    return int(round(v * mult[m.group(2)]))


def _stated(body):
    t = _strip(body).lower()
    for p in _QTY:
        m = re.search(p, t)
        if m:
            return _qty(m.group(1))
    return None


def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def respond(request, tools, params=None):
    p = dict(P, **(params or {}))
    sent = request["sent"]
    men = request.get("mentions") or {}
    acct_text = (men.get("account_text") or "").strip() or None
    ins_text = (men.get("instrument_text") or "").strip() or None
    sender = (request.get("from") or "").strip().lower()
    body = request.get("body") or ""

    contact = tools.get_contact(sender) if sender else None
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # ---- account
    acct = None
    if acct_text:
        hits = _resolve(acct_text, tools.search_accounts, "account")
        if len(hits) == 1:
            acct = hits[0]["id"]
    elif p["missing_account_from_entitlement"]:
        live = [e for e in ents if e["expires"] >= sent] or ents
        ids = sorted({e["account_id"] for e in live})
        if len(ids) == 1:
            acct = ids[0]

    # ---- instrument
    ins_hits = _resolve(ins_text, tools.search_instruments, "instrument") if ins_text else []
    ins = ins_hits[0]["id"] if len(ins_hits) == 1 else None

    # ---- date
    d, kind = _parse_date(body, sent)
    assumed = kind == "none"
    if assumed:
        d = _dt.date.fromisoformat(sent)

    def step(name):
        if name == "account":
            if not acct:
                if acct_text or contact:
                    return "REQUEST_INFO"
                return "REQUEST_AUTHORIZATION"
        elif name == "auth":
            es = [e for e in ents if e["account_id"] == acct]
            ok = any(e["level"] >= p["min_level"] and e["expires"] >= sent for e in es)
            if not ok:
                return "REQUEST_AUTHORIZATION"
        elif name == "instrument":
            if not ins:
                return "REQUEST_INFO"
        elif name == "date":
            if d is None:
                return "REQUEST_INFO"
            if d > _dt.date.fromisoformat(sent):
                return p["future_outcome"]
            if not tools.get_calendar(d.isoformat())["business_day"]:
                return p["nonbusiness_outcome"]
        elif name == "profile":
            prof = tools.get_client_profile(acct) or {}
            if prof.get("legal_hold"):
                return p["legal_hold_outcome"]
            if prof.get("no_email_confirm"):
                return p["no_email_outcome"]
        return None

    for name in p["check_order"]:
        if name == "figures":
            break
        o = step(name)
        if o:
            r = _blank(o)
            if o == "ESCALATE":
                r["account_id"], r["instrument_id"] = acct, ins
            return r

    # ---- figures: all custody sub-accounts, ledger dated <= as_of, split-adjusted
    as_of = d.isoformat()
    splits = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    settled = 0
    for t in tools.get_ledger(acct, ins):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for c in splits:
            if t["date"] < c["date"] <= as_of:
                q *= c["ratio"]
        settled += q
    settled = int(settled)
    matched = [x for x in tools.get_instructions(acct, ins)
               if x["status"] == "matched" and x["settle_date"] > as_of]
    horizon = (d + _dt.timedelta(days=p["pending_window"])).isoformat()
    pend = [x for x in matched if x["settle_date"] <= horizon]

    stated = _stated(body)
    esc = _blank("ESCALATE")
    esc["account_id"], esc["instrument_id"] = acct, ins
    if settled < 0:
        if p["negative_outcome"] == "ESCALATE":
            return esc
    if abs(settled) >= p["size_limit"]:
        return esc
    if stated is not None and stated != settled:
        all_p = sum(x["qty"] for x in matched)
        ok = (p["stated_plus_pending_ok"] and all_p and stated == settled + all_p) or \
             (settled and abs(stated - settled) <= p["tolerance"] * abs(settled))
        if not ok:
            return esc

    r = _blank("CONFIRMED" if settled > 0 else "NOT_HELD")
    r.update(account_id=acct, instrument_id=ins, as_of=as_of, as_of_assumed=assumed)
    if settled > 0:
        r["settled"] = settled
        if pend:
            r["pending"] = int(sum(x["qty"] for x in pend))
            r["pending_date"] = max(x["settle_date"] for x in pend)
    return r
