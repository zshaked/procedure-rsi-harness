"""Holding-confirmation desk procedure (implements spec.md 'Final rules')."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RX = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
PENDING_MIN = 1000      # matched instructions below this are immaterial (not reported)
TOLERANCE = 0.005       # relative tolerance when comparing the client's figure

FREE_PREFIXES = r"^(?:our\s+|the\s+)?(?:account|acct|a/c|fund|portfolio|sub-account|subaccount)\s*[:#]?\s*"


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


def _mk(y, m, d):
    try:
        if y < 100:
            y += 2000
        return dt.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _body_lines(body):
    # drop forwarded-header lines (From:/Date:/Sent:/To:/Subject:)
    keep = []
    for line in (body or "").split("\n"):
        if re.match(r"\s*(date|sent|from|to|subject|cc)\s*:", line, re.I):
            continue
        keep.append(line)
    return "\n".join(keep)


def parse_date(body, sent):
    """Return (date or None, found_flag)."""
    s = dt.date.fromisoformat(sent)
    b = _body_lines(body)
    cands = []
    for m in re.finditer(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", b):
        cands.append((m.start(), _mk(int(m[1]), int(m[2]), int(m[3]))))
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2,4})\b", b):
        cands.append((m.start(), _mk(int(m[3]), int(m[1]), int(m[2]))))
    for m in re.finditer(r"\b(\d{1,2})[- ]" + MON_RX + r"[- ,]+(\d{2,4})\b", b, re.I):
        cands.append((m.start(), _mk(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?(?: of)? " + MON_RX + r",? (\d{4})\b", b, re.I):
        cands.append((m.start(), _mk(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))))
    for m in re.finditer(r"\b" + MON_RX + r" (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", b, re.I):
        cands.append((m.start(), _mk(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2]))))
    cands = [c for c in cands if c[1] is not None]
    if cands:
        cands.sort(key=lambda c: c[0])
        return cands[0][1], True
    lb = b.lower()
    if re.search(r"\byesterday\b", lb):
        return s - dt.timedelta(days=1), True
    if re.search(r"\btoday\b|\bcurrent(ly)?\b|\bas of now\b", lb) and not re.search(
            r"month|year|quarter", lb):
        return s, True
    if re.search(r"(end of|last day of) (the )?(last|previous|prior) month|(last|previous|prior) month[- ]end"
                 r"|\bmonth[- ]end\b|\bend of (the )?month\b", lb):
        return s.replace(day=1) - dt.timedelta(days=1), True
    if re.search(r"(end of|last day of) (the )?(last|previous|prior) year|year[- ]end|end of (the )?year", lb):
        return dt.date(s.year - 1, 12, 31), True
    if re.search(r"(end of|last day of) (the )?(last|previous|prior) quarter|quarter[- ]end", lb):
        q_start = dt.date(s.year, 3 * ((s.month - 1) // 3) + 1, 1)
        return q_start - dt.timedelta(days=1), True
    return None, False


def _num(tok):
    t = tok.lower().replace(",", "").strip().rstrip(".")
    mult = 1
    for suf, mu in (("mm", 10 ** 6), ("mn", 10 ** 6), ("m", 10 ** 6), ("k", 10 ** 3)):
        if t.endswith(suf):
            mult, t = mu, t[: -len(suf)].strip()
            break
    try:
        return int(round(float(t) * mult))
    except ValueError:
        return None


QTY = r"(\d[\d,]*(?:\.\d+)?\s*(?:mm|mn|k|m)?)\b"


def parse_qty(body):
    b = _body_lines(body)
    pats = [r"(?:figure|number|balance|position|holding)s?\s+(?:is|of|shows?|=|:)\s+" + QTY,
            r"\b(?:we|records|books|ledger|system)\s+(?:show|shows|have|has|hold|holds|reflect|reflects|record)\s+" + QTY,
            QTY + r"\s*(?:shares|units)\b"]
    for p in pats:
        m = re.search(p, b, re.I)
        if m:
            v = _num(m.group(1))
            if v is not None:
                return v
    return None


def _clean(text):
    t = (text or "").strip().strip(".,;:()[]\"'")
    t2 = re.sub(FREE_PREFIXES, "", t, flags=re.I).strip()
    return [x for x in dict.fromkeys([t, t2]) if x]


def resolve_account(tools, mention, body):
    for t in _clean(mention):
        hits = tools.search_accounts(t)
        if hits:
            return hits
    if mention:
        m = re.search(r"\b(ACC-\d+|SA-\d+)\b", mention, re.I)
        if m:
            return tools.search_accounts(m.group(1).upper())
        return []
    ids = sorted(set(x.upper() for x in re.findall(r"\b(ACC-\d+|SA-\d+)\b", _body_lines(body), re.I)))
    hits = {}
    for i in ids:
        for h in tools.search_accounts(i):
            hits[h["id"]] = h
    return [hits[k] for k in sorted(hits)]


def resolve_instrument(tools, mention, body):
    for t in _clean(mention):
        hits = tools.search_instruments(t)
        if hits:
            return hits
    if mention:
        return []
    isins = sorted(set(re.findall(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", _body_lines(body))))
    hits = {}
    for i in isins:
        for h in tools.search_instruments(i):
            hits[h["id"]] = h
    return [hits[k] for k in sorted(hits)]


def respond(request, tools):
    mentions = request.get("mentions") or {}
    body = request.get("body") or ""
    sent = request["sent"]
    sender = (request.get("from") or "").strip().lower()

    # 1-2. identify account and instrument
    accs = resolve_account(tools, mentions.get("account_text"), body)
    if len(accs) != 1:
        return _out("REQUEST_INFO")
    acc = accs[0]["id"]
    inss = resolve_instrument(tools, mentions.get("instrument_text"), body)
    if len(inss) != 1:
        return _out("REQUEST_INFO")
    ins = inss[0]["id"]

    # 3. date
    d, found = parse_date(body, sent)
    assumed = False
    if d is None:
        d, assumed = dt.date.fromisoformat(sent), True
    if d > dt.date.fromisoformat(sent):
        return _out("REQUEST_INFO")
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]

    # 4. authorization
    profile = tools.get_client_profile(acc) or {"domains": [], "legal_hold": False, "no_email_confirm": False}
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    contact = tools.get_contact(sender) if sender else None
    ok = bool(contact) and domain in [x.lower() for x in profile.get("domains", [])]
    if ok:
        ok = any(e["account_id"] == acc and int(e["level"]) >= 2 and (not e.get("expires") or e["expires"] >= sent)
                 for e in tools.get_entitlements(contact["contact_id"]))
    if not ok:
        return _out("REQUEST_AUTHORIZATION")
    # 5. client asked for no email confirmations
    if profile.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")
    # 6. legal hold
    if profile.get("legal_hold"):
        return _out("ESCALATE", acc, ins)

    # 7. settled position (all sub-accounts, inclusive, split-adjusted)
    splits = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    settled = raw = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] <= as_of:
            q = t["qty"]
            raw += q
            for c in splits:
                if t["date"] < c["date"] <= as_of:
                    q *= c["ratio"]
            settled += q

    # 8. material pending settlements
    pend = [x for x in tools.get_instructions(acc, ins)
            if x.get("status") == "matched" and x["settle_date"] > as_of and abs(x["qty"]) >= PENDING_MIN]
    pending = sum(x["qty"] for x in pend) if pend else None
    pdate = max(x["settle_date"] for x in pend) if pend else None

    # 9. nothing held
    if settled <= 0:
        return _out("NOT_HELD", acc, ins, as_of, assumed, None, pending, pdate)

    # 10. client's figure must agree with ours (settled + pending)
    claim = parse_qty(body)
    if claim is not None:
        p = pending or 0
        ours = [settled + p, raw + p]
        if not any(abs(claim - o) <= TOLERANCE * max(abs(o), 1) for o in ours):
            return _out("ESCALATE", acc, ins)

    return _out("CONFIRMED", acc, ins, as_of, assumed, settled, pending, pdate)
