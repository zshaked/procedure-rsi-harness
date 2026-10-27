"""Position-confirmation desk procedure. respond(request, tools) -> dict.
Deterministic; standard library + `tools` only. P holds the conventions chosen by search against verifier.py."""
import re
import datetime as dt

P = {
    "order": "auth_then_info",   # freemail -> account -> domain/entitlement -> instrument/date -> future -> hold
    "qty_source": "ledger",      # sum all sub-accounts from the raw ledger, split-adjusted
    "roll": "prev_business",     # non-business position date -> previous business day
    "tolerance": 0.10,
    "compare_with_pending": True,
    "pending_cut": "as_of",      # matched instructions settling after as_of
    "pending_date": "latest",
    "assumed": "never",
    "min_level": 2,
}

OUT_KEYS = ("outcome", "account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "proton.me",
            "protonmail.com", "live.com", "msn.com", "mail.com", "gmx.com", "yahoo.co.uk", "googlemail.com"}


def _strip(body):
    out = []
    for line in (body or "").split("\n"):
        s = line.strip()
        if re.match(r"^-+\s*(Forwarded|Original) message", s, re.I):
            continue
        if re.match(r"^(From|Date|Sent|To|Cc|Subject):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        out.append(line)
    return "\n".join(out)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _date(body, sent):
    s = dt.date.fromisoformat(sent)
    b = _strip(body)
    bl = b.lower()
    som = s.replace(day=1)
    if re.search(r"\b(end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|"
                 r"(last|previous|prior) month[- ]?end|month[- ]?end|end of (the )?month)\b", bl):
        return som - dt.timedelta(days=1), "relative"
    if re.search(r"\b(end of (the )?(last|previous|prior) year|year[- ]?end)\b", bl):
        return dt.date(s.year - 1, 12, 31), "relative"
    if re.search(r"\byesterday\b", bl):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"\b(last|previous|prior) business day\b", bl):
        return s - dt.timedelta(days=1), "relative"
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (d, "explicit") if d else (None, "invalid")
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", b)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        d = _mk(y, int(m.group(1)), int(m.group(2)))
        return (d, "explicit") if d else (None, "invalid")
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\.?[- ,]+(\d{4})\b", b)
    if m and m.group(2).lower()[:3] in MON3:
        d = _mk(int(m.group(3)), MON3[m.group(2).lower()[:3]], int(m.group(1)))
        return (d, "explicit") if d else (None, "invalid")
    m = re.search(r"\b(" + "|".join(MONTHS) + "|" + "|".join(MON3) + r")\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?\b", b, re.I)
    if m:
        mo = MON3[m.group(1).lower()[:3]]
        day = int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
        else:
            y = s.year
            c = _mk(y, mo, day)
            if c and c > s:
                y -= 1
        d = _mk(y, mo, day)
        return (d, "explicit") if d else (None, "invalid")
    if re.search(r"\b(today|as of now|current(ly)?|latest)\b", bl):
        return s, "relative"
    return None, "none"


def _qty(body):
    b = _strip(body)
    m = re.search(r"(?:records show|our figure is|we show|we have|we hold|our books show|books reflect|we see|"
                  r"our position is|we record)\s+(-?[\d,]*\.?\d+)\s*(k|mm|mn|m|million|thousand|bn)?\b", b, re.I)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    if suf in ("k", "thousand"):
        v *= 1000
    elif suf in ("mm", "mn", "m", "million"):
        v *= 1_000_000
    elif suf == "bn":
        v *= 1_000_000_000
    return int(round(v))


def _resp(outcome, **kw):
    r = {k: None for k in OUT_KEYS}
    r["outcome"] = outcome
    r["as_of_assumed"] = False
    r.update(kw)
    return r


def respond(request, tools, p=None):
    p = p or P
    sent = request["sent"]
    m = request.get("mentions") or {}
    body = request.get("body", "")
    sender = (request.get("from") or "").strip().lower()
    domain = sender.split("@")[-1]
    contact = tools.get_contact(sender) if sender else None

    at = (m.get("account_text") or "").strip()
    it = (m.get("instrument_text") or "").strip()
    ah = tools.search_accounts(at) if at else []
    acc = ah[0]["id"] if len(ah) == 1 else None
    ih = tools.search_instruments(it) if it else []
    ins = ih[0]["id"] if len(ih) == 1 else None
    date, dkind = _date(body, sent)

    def auth_fail():
        prof = tools.get_client_profile(acc) or {}
        if domain not in [d.lower() for d in prof.get("domains", [])]:
            return True
        lvl = 0
        for e in tools.get_entitlements(contact["contact_id"]):
            if e["account_id"] == acc and e["expires"] >= sent:
                lvl = max(lvl, e["level"])
        return lvl < p["min_level"]

    # 1. sender identity
    if domain in FREEMAIL or not contact:
        return _resp("REQUEST_AUTHORIZATION")
    if p["order"] == "info_then_auth":
        if not acc or not ins or dkind in ("none", "invalid"):
            return _resp("REQUEST_INFO")
        if auth_fail():
            return _resp("REQUEST_AUTHORIZATION")
    else:
        # 2. account must be unique; 3. sender authorised for it; 4. instrument and date present
        if not acc:
            return _resp("REQUEST_INFO")
        if auth_fail():
            return _resp("REQUEST_AUTHORIZATION")
        if not ins or dkind in ("none", "invalid"):
            return _resp("REQUEST_INFO")
    # 5. future position date
    if date.isoformat() > sent:
        return _resp("REQUEST_INFO")
    # 6. legal hold
    prof = tools.get_client_profile(acc) or {}
    if prof.get("legal_hold"):
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)

    # 7. figure date
    cal = tools.get_calendar(date.isoformat())
    rolled = not cal["business_day"]
    as_of = cal["previous_business_day"] if (rolled and p["roll"] == "prev_business") else date.isoformat()
    if p["assumed"] == "never":
        assumed = False
    elif p["assumed"] == "relative":
        assumed = dkind == "relative"
    else:
        assumed = rolled or dkind == "relative"

    # 8. settled quantity: all custody sub-accounts, split-adjusted to as_of
    if p["qty_source"] == "summary":
        settled = tools.get_position_summary(acc, ins, as_of)["quantity"]
    else:
        splits = [s for s in tools.get_corporate_actions(ins) if s.get("type") == "split"]
        settled = 0
        for t in tools.get_ledger(acc, ins):
            if t["date"] > as_of:
                continue
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            settled += q

    # 9. pending: matched instructions settling after the cut-off
    cut = as_of if p["pending_cut"] == "as_of" else sent
    pend = [x for x in tools.get_instructions(acc, ins) if x["status"] == "matched" and x["settle_date"] > cut]
    pending = sum(x["qty"] for x in pend) if pend else None
    if pend:
        ds = [x["settle_date"] for x in pend]
        pending_date = max(ds) if p["pending_date"] == "latest" else min(ds)
    else:
        pending_date = None

    if settled < 0:
        return _resp("ESCALATE", account_id=acc, instrument_id=ins)
    if settled == 0:
        return _resp("NOT_HELD", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed)

    # 10. client's own figure must agree (settled, or settled + pending) within tolerance
    claim = _qty(body)
    if claim is not None:
        cands = [settled] + ([settled + pending] if (pending and p["compare_with_pending"]) else [])
        if not any(abs(claim - c) <= p["tolerance"] * abs(c) for c in cands):
            return _resp("ESCALATE", account_id=acc, instrument_id=ins)

    return _resp("CONFIRMED", account_id=acc, instrument_id=ins, as_of=as_of, as_of_assumed=assumed,
                 settled=settled, pending=pending, pending_date=pending_date)
