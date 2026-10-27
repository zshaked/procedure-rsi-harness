"""Reference-free verifier for position-confirmation replies.

verify(request, response, tools) -> (ok, failures)

Each check below is an independent condition a correct response must satisfy,
derived from the histories, the unlabeled requests and the tool docstrings.
Evidence for each check is given in its comment. No labels are used.
"""
import re
import datetime as dt

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}
KEYS = ["outcome", "account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date"]

# Conventions that the oracle calibrated (see NOTES.md). Kept as switches so the
# procedure search in phase 3 can vary them.
CONV = {
    "nonbusiness": "REQUEST_INFO",  # weekend/holiday as_of -> ask which date (oracle Q2, Q4, Q12)
    "free_mail_ok": True,           # entitlement, not sender domain, authorises (Q3-0023, oracle Q6)
    "subaccount_scope": "account",  # sub-account mention -> whole account total (untested; tools sum all sub-accounts)
    "pending_window": 45,           # matched instr. settling in (as_of, as_of+45d] (Q3-0008 36d yes; Q3-0018/0020 no; oracle Q13 52d no; Q15 17d yes)
    "future_date": "REQUEST_INFO",  # as_of after the email date (oracle Q7)
    "legal_hold": "ESCALATE",       # untested guess
    "no_email_confirm": "REQUEST_AUTHORIZATION",  # Q3-0024, oracle Q8
    "missing_account": "entitlement",  # no account text -> sender's single entitled account (Q3-0024, oracle Q10)
    "tolerance": 0.05,              # |stated-settled|/settled within 5% is not a break (Q3-0012 7% escalated; guess)
    "stated_plus_pending_ok": True, # stated == settled + matched pending is a match (oracle Q13/Q14)
    "size_limit": 1000000,          # settled >= 1m -> ESCALATE (oracle Q9 2.79m, Q11 1.22m; Q3-0011 855k confirmed)
    "negative": "ESCALATE",         # negative settled position -> review (guess)
    "min_level": 3,
}

MONTHS = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com",
             "icloud.com", "aol.com", "live.com", "msn.com"}


# ---------------------------------------------------------------- parsing helpers
def clean_body(body):
    """Drop forwarded-message headers ('Date: 2026-01-27' in Q3-0002 is not the position date)
    and the confidentiality footer."""
    out = []
    for ln in (body or "").split("\n"):
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|To|Sent|Subject|Cc)\s*:", s, re.I):
            continue
        if "confidential and intended solely" in s.lower():
            continue
        out.append(ln)
    return "\n".join(out)


def _mon(tok):
    return MONTHS.get(tok[:3].lower()) if tok and tok[:3].isalpha() else None


def _mk(y, m, d):
    try:
        return dt.date(y, m, d), "explicit"
    except ValueError:
        return None, "bad"


def parse_date(body, sent):
    """Position date from the free text. Returns (date|None, kind) with kind in
    explicit | relative | none | bad.  Relative phrases are anchored on `sent`
    (Q3-0008: 'end of last month' sent 2026-01-29 -> 2025-12-31)."""
    sent_d = dt.date.fromisoformat(sent)
    t = clean_body(body)
    tl = t.lower()
    if re.search(r"\byesterday\b", tl):
        return sent_d - dt.timedelta(days=1), "relative"
    if re.search(r"\b(today|this morning|as of now|current(ly)?)\b", tl) and not re.search(r"\d{4}", tl):
        return sent_d, "relative"
    if re.search(r"(end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|"
                 r"month[- ]end|end of (the )?month|last month[- ]end|previous month[- ]end)", tl):
        return sent_d.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"(year[- ]end|end of (last )?year)", tl):
        return dt.date(sent_d.year - 1, 12, 31), "relative"
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ](\d{4})\b", t)
    if m and _mon(m.group(2)):
        return _mk(int(m.group(3)), _mon(m.group(2)), int(m.group(1)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:  # US month/day/year (Q3-0015 '1/16/2026')
        return _mk(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", t)
    if m and _mon(m.group(1)):
        return _mk(int(m.group(3)), _mon(m.group(1)), int(m.group(2)))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?([A-Za-z]{3,9}),? (\d{4})\b", t)
    if m and _mon(m.group(2)):
        return _mk(int(m.group(3)), _mon(m.group(2)), int(m.group(1)))
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
QTY_PATTERNS = [
    r"we (?:have|hold)\s+" + _NUM + r"\s*(?:shares|units)",
    r"our records show\s+" + _NUM,
    r"our figure is\s+" + _NUM,
    r"we show\s+" + _NUM,
    r"our (?:books|records|figures?) (?:show|say|have|indicate)s?\s+" + _NUM,
    r"(?:we|our books) (?:hold|have)\s+" + _NUM,
]


def parse_qty_token(tok):
    """'12,500' / '12500' / '12.5k' / '1.2mm' -> int."""
    m = re.match(r"^(-?[\d,]*\.?\d+)\s*(k|mm|mn|m|bn|million|thousand)?$", tok.strip().lower())
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {None: 1, "k": 1e3, "thousand": 1e3, "mm": 1e6, "mn": 1e6, "m": 1e6, "million": 1e6, "bn": 1e9}[m.group(2)]
    return int(round(v * mult))


def parse_stated_qty(body):
    t = clean_body(body).lower()
    for p in QTY_PATTERNS:
        m = re.search(p, t)
        if m:
            return parse_qty_token(m.group(1))
    return None


# ---------------------------------------------------------------- reference facts
def facts(request, tools, conv=None):
    """Everything the checklist needs, computed only through `tools`."""
    c = dict(CONV, **(conv or {}))
    f = {"conv": c}
    sent = request["sent"]
    men = request.get("mentions") or {}
    at = (men.get("account_text") or "").strip() or None
    it = (men.get("instrument_text") or "").strip() or None
    sender = (request.get("from") or "").strip().lower()
    contact = tools.get_contact(sender) if sender else None
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    f.update(sender=sender, contact=contact, ents=ents, account_text=at, instrument_text=it)

    # account resolution
    f["sub_account"] = None
    if at:
        hits = _resolve(at, tools.search_accounts, "account")
        f["acct_hits"] = [h["id"] for h in hits]
        f["account_id"] = hits[0]["id"] if len(hits) == 1 else None
        if f["account_id"] and at.upper().startswith("SA-"):
            f["sub_account"] = at.upper()
    else:
        f["acct_hits"] = []
        f["account_id"] = None
        if c["missing_account"] == "entitlement":
            live = [e for e in ents if e["expires"] >= sent]
            pool = live if live else ents
            ids = sorted({e["account_id"] for e in pool})
            if len(ids) == 1:
                f["account_id"] = ids[0]
                f["acct_hits"] = ids
    acc = f["account_id"]

    # entitlement of the sender on that account
    ent = None
    if acc:
        es = [e for e in ents if e["account_id"] == acc]
        if es:
            ent = max(es, key=lambda e: (e["expires"] >= sent, e["level"], e["expires"]))
    f["entitlement"] = ent
    f["authorized"] = bool(ent and ent["level"] >= c["min_level"] and ent["expires"] >= sent)
    prof = tools.get_client_profile(acc) if acc else None
    f["profile"] = prof
    dom = sender.split("@")[-1] if "@" in sender else ""
    f["domain_ok"] = bool(prof and dom in [d.lower() for d in prof.get("domains", [])])
    f["free_mail"] = dom in FREE_MAIL

    # instrument
    ins = _resolve(it, tools.search_instruments, "instrument") if it else []
    f["ins_hits"] = [i["id"] for i in ins]
    f["instrument_id"] = ins[0]["id"] if len(ins) == 1 else None

    # date
    d, kind = parse_date(request.get("body", ""), sent)
    f["date_kind"] = kind
    if kind == "none":
        d = dt.date.fromisoformat(sent)
    f["req_date"] = d
    f["as_of_assumed"] = kind == "none"
    f["future"] = bool(d and d > dt.date.fromisoformat(sent))
    f["as_of"] = d.isoformat() if d else None
    f["business_day"] = bool(d) and tools.get_calendar(d.isoformat())["business_day"]
    f["stated"] = parse_stated_qty(request.get("body", ""))

    # holdings
    f["settled"] = f["pending"] = f["pending_date"] = None
    f["all_pending"] = 0
    if acc and f["instrument_id"] and f["as_of"]:
        iid = f["instrument_id"]
        ca = [x for x in tools.get_corporate_actions(iid) if x.get("type") == "split"]
        tot = 0
        for t in tools.get_ledger(acc, iid):
            if t["date"] > f["as_of"]:
                continue
            if c["subaccount_scope"] == "sub" and f["sub_account"] and t["sub_account"].upper() != f["sub_account"]:
                continue
            q = t["qty"]
            for s in ca:  # split multiplies holdings recorded before its date, if effective by as_of
                if t["date"] < s["date"] <= f["as_of"]:
                    q *= s["ratio"]
            tot += q
        f["settled"] = int(tot)
        matched = [x for x in tools.get_instructions(acc, iid) if x["status"] == "matched"
                   and x["settle_date"] > f["as_of"]]
        f["all_pending"] = sum(x["qty"] for x in matched)
        horizon = (dt.date.fromisoformat(f["as_of"]) + dt.timedelta(days=c["pending_window"])).isoformat()
        pend = [x for x in matched if x["settle_date"] <= horizon]
        if pend:
            f["pending"] = int(sum(x["qty"] for x in pend))
            f["pending_date"] = max(x["settle_date"] for x in pend)
    return f


def expected_outcome(f):
    """Decision order evidenced by the histories (comments cite cases)."""
    c = f["conv"]
    # 1. account must resolve to exactly one account (Q3-0000, 0006, 0017, 0021: several
    #    matches -> REQUEST_INFO even when the sender is entitled to one of them).
    if f["account_text"] and not f["account_id"]:
        return "REQUEST_INFO"
    if not f["account_id"]:
        # no account text and no single entitled account to fall back on
        return "REQUEST_INFO" if f["contact"] else "REQUEST_AUTHORIZATION"
    # 2. sender must hold a live entitlement of level >= 3 on that account
    #    (Q3-0002/0009 level 2, Q3-0003/0010/0015 level 1, Q3-0005/0014/0016 other account).
    if not f["authorized"]:
        return "REQUEST_AUTHORIZATION"
    if not c["free_mail_ok"] and not f["domain_ok"]:
        return "REQUEST_AUTHORIZATION"
    # 3. instrument and date must be usable (Q3-0004, Q3-0019: no security -> REQUEST_INFO).
    if not f["instrument_id"]:
        return "REQUEST_INFO"
    if f["date_kind"] == "bad":
        return "REQUEST_INFO"
    if f["future"]:
        return c["future_date"]
    # 4. the position date must be a business day (oracle: 'That date isn't a business day;
    #    we ask them which date they want').
    if not f["business_day"]:
        return c["nonbusiness"]
    # 5. client restrictions in the profile (Q3-0024 no_email_confirm -> REQUEST_AUTHORIZATION).
    prof = f["profile"] or {}
    if prof.get("legal_hold"):
        return c["legal_hold"]
    if prof.get("no_email_confirm"):
        return c["no_email_confirm"]
    s_ = f["settled"]
    # 6. anomalies / size go for review (oracle: 'Positions that size always go to escalation').
    if s_ < 0:
        return c["negative"]
    if abs(s_) >= c["size_limit"]:
        return "ESCALATE"
    # 7. a client-stated figure that breaks against ours goes for review (Q3-0012).
    if f["stated"] is not None and not stated_matches(f):
        return "ESCALATE"
    # 8. otherwise report (Q3-0023: nothing held -> NOT_HELD).
    return "CONFIRMED" if s_ > 0 else "NOT_HELD"


def stated_matches(f):
    c = f["conv"]
    st, se = f["stated"], f["settled"]
    if st == se:
        return True
    if c["stated_plus_pending_ok"] and f["all_pending"] and st == se + f["all_pending"]:
        return True
    if se and abs(st - se) <= c["tolerance"] * abs(se):
        return True
    return False


def verify(request, response, tools, conv=None):
    fails = []
    # C0: response shape: every key present, outcome in the allowed set.
    if not isinstance(response, dict):
        return False, ["response is not a dict"]
    for k in KEYS:
        if k not in response:
            fails.append("missing key %s" % k)
    out = response.get("outcome")
    if out not in OUTCOMES:
        fails.append("invalid outcome %r" % out)
        return False, fails
    f = facts(request, tools, conv)
    exp = expected_outcome(f)

    # C1: ambiguity / unresolved account -> REQUEST_INFO (Q3-0000/0006/0007/0017/0021).
    if f["account_text"] and not f["account_id"] and out != "REQUEST_INFO":
        fails.append("C1 account text does not resolve to exactly one account (%s) -> REQUEST_INFO" % f["acct_hits"])
    # C2: never disclose (CONFIRMED/NOT_HELD/ESCALATE with figures) to an unauthorised sender
    #     (Q3-0002/0003/0005/0009/0010/0014/0015/0016).
    if f["account_id"] and not f["authorized"] and out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        fails.append("C2 sender lacks a live level>=%d entitlement on %s" % (f["conv"]["min_level"], f["account_id"]))
    if f["account_id"] and not f["authorized"] and out == "REQUEST_INFO" and not f["account_text"] is None:
        fails.append("C2b unauthorised sender should get REQUEST_AUTHORIZATION, not REQUEST_INFO (Q3-0015)")
    # C3: missing/unknown security for an authorised sender -> REQUEST_INFO (Q3-0004/0019).
    if f["authorized"] and not f["instrument_id"] and out != "REQUEST_INFO":
        fails.append("C3 security missing or unresolved -> REQUEST_INFO")
    # C4: profile restrictions (legal_hold / no_email_confirm) block a confirmation (Q3-0024).
    prof = f["profile"] or {}
    if (prof.get("legal_hold") or prof.get("no_email_confirm")) and out in ("CONFIRMED", "NOT_HELD"):
        fails.append("C4 client profile forbids e-mail confirmation (legal_hold/no_email_confirm)")
    # C5: a stated client figure that disagrees with the settled figure is never CONFIRMED (Q3-0012).
    if f["stated"] is not None and f["settled"] is not None and not stated_matches(f) and out == "CONFIRMED":
        fails.append("C5 client's figure %s differs from settled %s -> ESCALATE" % (f["stated"], f["settled"]))
    # C5b: large or negative positions are never confirmed by e-mail (oracle Q9/Q11).
    if f["settled"] is not None and (f["settled"] < 0 or abs(f["settled"]) >= f["conv"]["size_limit"]) and out == "CONFIRMED":
        fails.append("C5b position %s needs escalation" % f["settled"])
    # C5c: non-business or future position dates are queried, never confirmed (oracle Q2/Q7).
    if f["as_of"] and (not f["business_day"] or f["future"]) and out in ("CONFIRMED", "NOT_HELD"):
        fails.append("C5c position date %s is not a usable business day" % f["as_of"])
    # C6: overall decision must equal the decision order.
    if out != exp:
        fails.append("C6 outcome %s, decision order gives %s" % (out, exp))

    # Field checks
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        # C7: account/instrument ids are the system ids, not the raw text (Q3-0013 ISIN->XVX, ACC id).
        if response.get("account_id") != f["account_id"]:
            fails.append("C7 account_id %r != %r" % (response.get("account_id"), f["account_id"]))
        if response.get("instrument_id") != f["instrument_id"]:
            fails.append("C7 instrument_id %r != %r" % (response.get("instrument_id"), f["instrument_id"]))
    if out in ("CONFIRMED", "NOT_HELD"):
        # C8: as_of is the date the figure is given for; email date when none given (Q3-0023).
        if response.get("as_of") != f["as_of"]:
            fails.append("C8 as_of %r != %r" % (response.get("as_of"), f["as_of"]))
        # C9: as_of_assumed true exactly when no date was given (Q3-0023 reply text).
        if bool(response.get("as_of_assumed")) != f["as_of_assumed"]:
            fails.append("C9 as_of_assumed %r != %r" % (response.get("as_of_assumed"), f["as_of_assumed"]))
    if out == "CONFIRMED":
        # C10: settled = all custody sub-accounts, ledger dated <= as_of, split-adjusted
        #      (Q3-0001 534873+16498, Q3-0018 three sub-accounts; get_position_summary is primary-only).
        if response.get("settled") != f["settled"]:
            fails.append("C10 settled %r != %r" % (response.get("settled"), f["settled"]))
        # C11: pending = matched (not unmatched/cancelled) instructions settling within 45 days after
        #      as_of (Q3-0008 reported; Q3-0018/0020 not; oracle Q13 rejected a 52-day one).
        if response.get("pending") != f["pending"] or response.get("pending_date") != f["pending_date"]:
            fails.append("C11 pending %r/%r != %r/%r" % (response.get("pending"), response.get("pending_date"),
                                                         f["pending"], f["pending_date"]))
    # C12: no figures leak on non-disclosing outcomes.
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION", "ESCALATE"):
        if response.get("settled") is not None or response.get("pending") is not None:
            fails.append("C12 figures disclosed on %s" % out)
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION") and (response.get("account_id") or response.get("instrument_id")):
        pass  # ids on these outcomes are tolerated
    return (not fails), fails
