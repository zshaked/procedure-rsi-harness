"""Procedure for the custody operations desk: confirm a client's holding of a security.

Order of checks (induced from histories + oracle):
  1. identify the account (ambiguous name -> REQUEST_INFO; unnamed -> infer from sender's entitlement)
  2. authorization (known contact, live entitlement level >= 2, sender domain registered to the account)
  3. completeness (security, date; date must not be in the future)
  4. account under legal hold -> ESCALATE
  5. client's figure disputes ours -> ESCALATE
  6. nothing held -> NOT_HELD
  7. CONFIRMED with settled (all sub-accounts, split-adjusted) and matched pending
"""
import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

MISMATCH_TOL = 0.10          # relative difference above which the client's figure is "disputed"
AUTH_MIN_LEVEL = 2           # entitlement level needed to receive a confirmation
FLAG_ESCALATES = True        # legal_hold -> ESCALATE (no_email_confirm does not block a confirmation)


# ----------------------------------------------------------------------------- text helpers
def _strip_body(body):
    lines = (body or "").split("\n")
    if lines and lines[0].lstrip().startswith("---------- Forwarded"):
        i = 1
        while i < len(lines) and lines[i].strip() != "":
            i += 1
        lines = lines[i + 1:]
    out = []
    for l in lines:
        if l.startswith("This email and any attachments"):
            break
        out.append(l)
    return "\n".join(out)


def _parse_qty(s):
    s = s.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)(k|mm|m)?$", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    u = (m.group(2) or "").lower()
    if u == "k":
        v *= 1000
    elif u in ("m", "mm"):
        v *= 1000000
    return int(round(v))


NUM = r"(-?\d[\d,]*(?:\.\d+)?\s*(?:k|mm|m)?)(?![\w-])"


def _claimed(body):
    b = _strip_body(body)
    m = re.search(r"(?:\bshows?|figure is|figure of|\bhave|\bhold|records show|books show)\s+" + NUM, b, re.I)
    if m:
        return _parse_qty(m.group(1))
    m = re.search(NUM + r"\s+(?:units|shares)\b", b, re.I)
    if m:
        return _parse_qty(m.group(1))
    return None


def _last_day_of_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _parse_date(body, sent):
    """Return the position date requested (a datetime.date) or None, before business-day roll-back."""
    b = _strip_body(body)
    try:
        s = dt.date.fromisoformat(sent)
    except Exception:
        s = None
    m = re.search(r"(?<![\d/-])(\d{4})-(\d{2})-(\d{2})(?![\d])", b)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])", b)
    if m:
        for mo, dy in ((int(m.group(1)), int(m.group(2))), (int(m.group(2)), int(m.group(1)))):
            try:
                return dt.date(int(m.group(3)), mo, dy)      # M/D/YYYY first, D/M/YYYY if that is impossible
            except ValueError:
                pass
    m = re.search(r"(?<![\w])(\d{1,2})(?:st|nd|rd|th)?[\s-]+" + MON_RE + r"[\s,-]+(\d{4})(?![\d])", b, re.I)
    if m:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        except ValueError:
            pass
    m = re.search(r"(?<![\w])" + MON_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?![\d])", b, re.I)
    if m:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        except ValueError:
            pass
    low = b.lower()
    if s is not None:
        if re.search(r"(end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|"
                     r"(last|previous|prior) month[- ]end|month[- ]end|end of month)", low):
            return _last_day_of_prev_month(s)
        if "yesterday" in low:
            return s - dt.timedelta(days=1)
        if re.search(r"\b(today|this morning)\b", low):
            return s
    return None


# ----------------------------------------------------------------------------- state helpers
def _prev_bd(tools, d):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def _position(tools, acc, inst, as_of):
    """Settled position across all sub-accounts, in the units prevailing on as_of."""
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acc, inst):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            total += q
    return total


def _clean(text):
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t.strip(" .,;:()\"'")


def _search(fn, text):
    if not text:
        return []
    for cand in (text, _clean(text)):
        if cand:
            r = fn(cand)
            if r:
                return r
    return []


def _resolve_instrument(tools, text, body):
    cands = _search(tools.search_instruments, text)
    if not cands and not text:
        m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", body or "")
        if m:
            cands = tools.search_instruments(m.group(1))
    return cands


def _result(outcome, acc=None, inst=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": inst, "as_of": as_of,
            "as_of_assumed": bool(assumed), "settled": settled, "pending": pending, "pending_date": pdate}


# ----------------------------------------------------------------------------- the procedure
def _respond(request, tools):
    sent = request.get("sent")
    body = request.get("body") or ""
    men = request.get("mentions") or {}
    sender = (request.get("from") or "").strip().lower()
    dom = sender.split("@")[-1] if "@" in sender else ""

    contact = tools.get_contact(sender)
    acct_text = men.get("account_text")
    if not contact:
        return _result("REQUEST_AUTHORIZATION")

    ents = {}
    for e in tools.get_entitlements(contact["contact_id"]):
        if e["account_id"] not in ents or e["level"] > ents[e["account_id"]]["level"]:
            ents[e["account_id"]] = e

    def registered(a):
        p = tools.get_client_profile(a) or {}
        return dom in [d.lower() for d in p.get("domains", [])]

    def verified(a):
        return a in ents and registered(a)

    named = bool(acct_text and _clean(acct_text))
    cands = [x["id"] for x in _search(tools.search_accounts, acct_text)] if named else []

    # 1. sender screen: must be a verified contact (entitlement on file + registered domain) of the account(s) concerned
    pool = cands if cands else list(ents)
    if not any(verified(a) for a in pool):
        return _result("REQUEST_AUTHORIZATION")

    # 2. identify the account: unnamed, unknown or ambiguous -> ask
    if len(cands) != 1:
        return _result("REQUEST_INFO")
    acc = cands[0]
    profile = tools.get_client_profile(acc) or {}

    # 3. entitlement on the account: level and expiry
    e = ents[acc]
    if e["level"] < AUTH_MIN_LEVEL or e["expires"] < sent:
        return _result("REQUEST_AUTHORIZATION")

    # 4. completeness: security and date
    insts = _resolve_instrument(tools, men.get("instrument_text"), body)
    if len(insts) != 1:
        return _result("REQUEST_INFO", acc)
    inst = insts[0]["id"]
    d = _parse_date(body, sent)
    if d is None:
        return _result("REQUEST_INFO", acc, inst)
    try:
        if d > dt.date.fromisoformat(sent):
            return _result("REQUEST_INFO", acc, inst)
    except Exception:
        pass
    as_of = _prev_bd(tools, d).isoformat()

    # 5. account flags
    if FLAG_ESCALATES and profile.get("legal_hold"):
        return _result("ESCALATE", acc, inst, as_of)

    settled = _position(tools, acc, inst, as_of)

    # pending: matched instructions that have not settled as of the position date
    pend = [x for x in tools.get_instructions(acc, inst)
            if x["status"] == "matched" and x["settle_date"] > as_of]
    pending = sum(x["qty"] for x in pend) or None
    pdate = max(x["settle_date"] for x in pend) if pend else None

    # 6. client's figure disputes ours (compared with settled + pending)
    claimed = _claimed(body)
    if claimed is not None and settled != 0:
        base = settled + (pending or 0)          # the desk compares with settled + pending
        if base != 0 and abs(claimed - base) / abs(base) > MISMATCH_TOL:
            return _result("ESCALATE", acc, inst, as_of, settled=settled)

    # 7. nothing held / confirmation
    if settled == 0:
        return _result("NOT_HELD", acc, inst, as_of)
    return _result("CONFIRMED", acc, inst, as_of, False, settled, pending, pdate)


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _result("REQUEST_INFO")
