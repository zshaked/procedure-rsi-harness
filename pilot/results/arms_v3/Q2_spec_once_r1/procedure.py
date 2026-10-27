"""Holding-confirmation desk procedure (implements spec.md). Deterministic, stdlib only."""
import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
TOLERANCE = 0.01


def _empty(outcome, acc=None, ins=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


# ---------------------------------------------------------------- text helpers
def _strip_forward(body):
    body = re.sub(r'-+ ?Forwarded message ?-+[^\n]*\n(?:(?:From|Date|Sent|To|Subject|Cc):[^\n]*\n)*', '\n', body)
    body = re.sub(r'This email and any attachments are confidential[^\n]*', '', body)
    return body


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _parse_date(text, sent):
    """Return (date|None, found: bool)."""
    s = dt.date.fromisoformat(sent)
    m = re.search(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', text)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), True
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b', text)
    if m:
        return _mk(_year(m[3]), int(m[1]), int(m[2])), True
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\.?[- ,]+(\d{4})\b', text)
    if m and m[2][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), True
    m = re.search(r'\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b', text)
    if m and m[1][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), True
    low = text.lower()
    if 'day before yesterday' in low:
        return s - dt.timedelta(days=2), True
    if re.search(r'\byesterday\b', low):
        return s - dt.timedelta(days=1), True
    if re.search(r'\b(today|close of business today|cob today)\b', low):
        return s, True
    if re.search(r'end of last month|month[- ]end|last day of (the )?(last|previous|prior) month|'
                 r'end of (the )?(previous|prior) month|last month[- ]end', low):
        return s.replace(day=1) - dt.timedelta(days=1), True
    if re.search(r'end of (last|the previous|the prior) year|year[- ]end|last year[- ]end', low):
        return dt.date(s.year - 1, 12, 31), True
    if re.search(r'end of (last|the previous|the prior) quarter|quarter[- ]end', low):
        q0 = dt.date(s.year, 3 * ((s.month - 1) // 3) + 1, 1)
        return q0 - dt.timedelta(days=1), True
    return None, False


def _parse_qty(raw):
    s = raw.strip().lower().replace(',', '').replace(' ', '')
    mult, unit = 1, 1
    for suf, mu in (('mm', 1_000_000), ('mn', 1_000_000), ('m', 1_000_000), ('k', 1_000)):
        if s.endswith(suf):
            mult, s = mu, s[:-len(suf)]
            break
    try:
        v = float(s)
    except ValueError:
        return None, 0
    if mult > 1:
        dec = len(s.split('.')[1]) if '.' in s else 0
        unit = mult / (10 ** dec)          # precision of the abbreviated figure
    return int(round(v * mult)), (unit / 2 if mult > 1 else 0)


def _client_figure(text):
    m = re.search(r'(?:we show|figure is|records show|we have|books show|we hold|we record|our position is|'
                  r'our holding is|reconciles to|we see)\s+(?:a (?:position|holding) of\s+)?'
                  r'(\d[\d,]*(?:\.\d+)?\s*(?:mm|mn|m|k)?)(?![\w/-])', text, re.I)
    if not m:
        return None, 0
    return _parse_qty(m[1])


# ---------------------------------------------------------------- resolution
_PREFIX = re.compile(r'^(?:(?:our|the|a/c|acct|account|fund|portfolio|no\.?|number|#|:)\s*)+', re.I)


def _resolve_account(text, body, tools):
    cands = []
    if text:
        t = text.strip().strip('.,;:()"\'')
        cands += [t, _PREFIX.sub('', t).strip()]
    else:
        ids = re.findall(r'\b(ACC-\d+|SA-\d+)\b', body)
        cands += ids[:1]
    for c in cands:
        if not c:
            continue
        hits = tools.search_accounts(c)
        if hits:
            return [h["id"] for h in hits]
    return []


def _resolve_instrument(text, tools):
    if not text:
        return []
    t = text.strip().strip('.,;:()"\'')
    for c in (t, re.sub(r'^(?:the|our|shares of|units of)\s+', '', t, flags=re.I).strip()):
        if c:
            hits = tools.search_instruments(c)
            if hits:
                return list(dict.fromkeys(h["id"] for h in hits))
    return []


def _authorized(sender, account_id, sent, tools):
    sender = (sender or '').strip().lower()
    m = re.search(r'<([^>]+)>', sender)
    if m:
        sender = m[1]
    domain = sender.rsplit('@', 1)[-1] if '@' in sender else ''
    prof = tools.get_client_profile(account_id) or {}
    if domain not in [d.lower() for d in prof.get("domains", [])]:
        return False
    c = tools.get_contact(sender)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e.get("account_id") == account_id and (e.get("level") or 0) >= 2 \
                and (e.get("expires") is None or e["expires"] >= sent):
            return True
    return False


# ---------------------------------------------------------------- figures
def _business_as_of(d, tools):
    cal = tools.get_calendar(d.isoformat())
    return d.isoformat() if cal["business_day"] else cal["previous_business_day"]


def _settled(acc, ins, as_of, splits, tools):
    total = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            total += q
    return total


def _pending(acc, ins, as_of, splits, tools):
    qty, dates = 0, []
    for x in tools.get_instructions(acc, ins):
        if x.get("status") != "matched" or not x.get("settle_date") or x["settle_date"] <= as_of:
            continue
        if any(as_of < s["date"] <= x["settle_date"] for s in splits):
            continue
        qty += x["qty"]
        dates.append(x["settle_date"])
    return qty, (max(dates) if dates else None)


# ---------------------------------------------------------------- main
def respond(request, tools):
    sent = request.get("sent")
    body = _strip_forward(request.get("body") or "")
    mentions = request.get("mentions") or {}

    accs = _resolve_account(mentions.get("account_text"), body, tools)
    if len(accs) != 1:
        return _empty("REQUEST_INFO")
    acc = accs[0]
    inss = _resolve_instrument(mentions.get("instrument_text"), tools)
    if len(inss) != 1:
        return _empty("REQUEST_INFO")
    ins = inss[0]

    if not _authorized(request.get("from"), acc, sent, tools):
        return _empty("REQUEST_AUTHORIZATION")

    prof = tools.get_client_profile(acc) or {}
    if prof.get("legal_hold"):
        return _empty("ESCALATE", acc, ins)
    if prof.get("no_email_confirm"):
        return _empty("REQUEST_AUTHORIZATION")

    d, found = _parse_date(body, sent)
    if found and d is None:
        return _empty("REQUEST_INFO")
    assumed = not found
    if assumed:
        d = dt.date.fromisoformat(sent)
    if d.isoformat() > sent:
        return _empty("REQUEST_INFO")
    as_of = _business_as_of(d, tools)

    splits = [s for s in tools.get_corporate_actions(ins) if s.get("type") == "split"]
    settled = _settled(acc, ins, as_of, splits, tools)
    pend, pend_date = _pending(acc, ins, as_of, splits, tools)

    fig, prec = _client_figure(body)
    if fig is not None:
        ours = settled + pend
        tol = max(TOLERANCE * abs(ours), prec)
        if abs(fig - ours) > tol:
            return _empty("ESCALATE", acc, ins)

    out = _empty("NOT_HELD" if settled == 0 and pend == 0 else "CONFIRMED", acc, ins)
    out["as_of"] = as_of
    out["as_of_assumed"] = assumed
    if out["outcome"] == "CONFIRMED":
        out["settled"] = settled
        if pend:
            out["pending"] = pend
            out["pending_date"] = pend_date
    return out
