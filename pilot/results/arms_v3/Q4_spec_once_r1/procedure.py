"""Holding-confirmation desk procedure (implements spec.md)."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
MON_RE = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?'
WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
TOL = 0.10


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_body(body):
    b = body or ''
    # drop forwarded-message headers and disclaimer noise
    b = re.sub(r'(?im)^\s*(from|date|sent|to|subject)\s*:.*$', ' ', b)
    b = re.sub(r'-{3,}\s*forwarded message\s*-{3,}', ' ', b, flags=re.I)
    return ' '.join(b.split())


def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _last_of_prev_month(s):
    return s.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return the requested calendar date (not yet rolled), or None."""
    b = _clean_body(body)
    lb = b.lower()
    s = dt.date.fromisoformat(sent)
    # explicit dates first
    m = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', b)
    if m:
        d = _mk(m[1], m[2], m[3])
        if d:
            return d
    m = re.search(r'\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b', b)
    if m:
        a, c, y = int(m[1]), int(m[2]), int(m[3])
        if y < 100:
            y += 2000
        d = _mk(y, c, a) if a > 12 else _mk(y, a, c)
        if d:
            return d
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[\s\-]+' + MON_RE + r'[\s\-,]+(\d{4})\b', lb)
    if m:
        d = _mk(m[3], MONTHS[m[2][:3]], m[1])
        if d:
            return d
    m = re.search(r'\b' + MON_RE + r'\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', lb)
    if m:
        d = _mk(m[3], MONTHS[m[1][:3]], m[2])
        if d:
            return d
    # relative phrases
    if re.search(r'\bday before yesterday\b', lb):
        return s - dt.timedelta(days=2)
    if re.search(r'\byesterday\b', lb):
        return s - dt.timedelta(days=1)
    if re.search(r'\b(as of|as at|position date)\s+today\b|\btoday\'s (position|holding)', lb):
        return s
    if re.search(r'month[\s-]?end|end of (the )?(last|previous|prior) month|last day of (the )?'
                 r'(last|previous|prior) month|end of month|previous month[\s-]?end|last month[\s-]?end', lb):
        return _last_of_prev_month(s)
    if re.search(r'quarter[\s-]?end|end of (the )?(last|previous|prior) quarter', lb):
        q_start_month = 3 * ((s.month - 1) // 3) + 1
        return dt.date(s.year, q_start_month, 1) - dt.timedelta(days=1)
    if re.search(r'year[\s-]?end|end of (the )?(last|previous|prior) year', lb):
        return dt.date(s.year - 1, 12, 31)
    if re.search(r'end of (the )?(last|previous|prior) week|last week[\s-]?end', lb):
        d = s - dt.timedelta(days=s.weekday() + 3)  # Friday of previous week
        return d
    m = re.search(r'\blast (' + '|'.join(WEEKDAYS) + r')\b', lb)
    if m:
        wd = WEEKDAYS.index(m[1])
        delta = (s.weekday() - wd) % 7 or 7
        return s - dt.timedelta(days=delta)
    return None


def _num(tok):
    t = tok.strip().lower().replace(',', '')
    mult = 1
    for suf, mu in (('mm', 1_000_000), ('mn', 1_000_000), ('m', 1_000_000), ('k', 1_000)):
        if t.endswith(suf):
            t, mult = t[:-len(suf)].strip(), mu
            break
    try:
        return int(round(float(t) * mult))
    except ValueError:
        return None


QTY = r'(-?\d[\d,]*(?:\.\d+)?\s*(?:mm|mn|m|k)?)\b'


def parse_figure(body):
    b = _clean_body(body)
    pats = [r'records show\s+' + QTY, r'we show\s+' + QTY, r'figure is\s+' + QTY,
            r'we have\s+' + QTY, r'our books show\s+' + QTY, r'we hold\s+' + QTY,
            r'we see\s+' + QTY, r'our position (?:is|of)\s+' + QTY, r'holding of\s+' + QTY]
    for p in pats:
        m = re.search(p, b, re.I)
        if m:
            v = _num(m[1])
            if v is not None:
                return v
    return None


def _find_account_text(r):
    t = (r.get('mentions') or {}).get('account_text')
    if t:
        return t
    m = re.search(r'\b(ACC-\d+|SA-\d+)\b', _clean_body(r.get('body', '')), re.I)
    return m[1] if m else None


def _find_instrument_text(r):
    t = (r.get('mentions') or {}).get('instrument_text')
    if t:
        return t
    m = re.search(r'\b([A-Z]{2}[A-Z0-9]{9}\d)\b', _clean_body(r.get('body', '')))
    return m[1] if m else None


def _roll(tools, d):
    c = tools.get_calendar(d.isoformat())
    return d if c['business_day'] else dt.date.fromisoformat(c['previous_business_day'])


def _search_accounts(tools, text):
    hits = tools.search_accounts(text)
    if not hits:
        alt = re.sub(r'^(our|the)\s+|\s*(account|acct|a/c|fund)\s*$', '', text.strip(), flags=re.I)
        if alt and alt != text:
            hits = tools.search_accounts(alt)
    return hits


def respond(request, tools):
    sender = (request.get('from') or '').strip().lower()
    dom = sender.split('@')[-1] if '@' in sender else ''
    sent = request.get('sent')
    body = request.get('body') or ''
    contact = tools.get_contact(sender) if sender else None
    ents = tools.get_entitlements(contact['contact_id']) if contact else []

    acc_text = _find_account_text(request)
    if not acc_text:
        known = False
        for e in ents:
            p = tools.get_client_profile(e['account_id'])
            if p and dom in [x.lower() for x in p['domains']]:
                known = True
                break
        return _out("REQUEST_INFO" if known else "REQUEST_AUTHORIZATION")

    accs = _search_accounts(tools, acc_text)
    if len(accs) != 1:
        return _out("REQUEST_INFO")
    acct = accs[0]['id']
    prof = tools.get_client_profile(acct) or {"domains": [], "legal_hold": False}

    # authorization: registered domain + live entitlement
    if dom not in [x.lower() for x in prof.get('domains', [])]:
        return _out("REQUEST_AUTHORIZATION")
    live = [e for e in ents if e['account_id'] == acct and e['expires'] >= sent]
    if not live:
        return _out("REQUEST_AUTHORIZATION")

    # instrument (resolved early so an escalation can carry it)
    ins_text = _find_instrument_text(request)
    ins = tools.search_instruments(ins_text) if ins_text else []
    instr = ins[0]['id'] if len(ins) == 1 else None

    if prof.get('legal_hold'):
        return _out("ESCALATE", account_id=acct, instrument_id=instr)
    if max(e['level'] for e in live) < 2:
        return _out("REQUEST_AUTHORIZATION")

    if not instr:
        return _out("REQUEST_INFO")
    req_date = parse_date(body, sent)
    if req_date is None:
        return _out("REQUEST_INFO")
    if req_date.isoformat() >= sent:
        return _out("REQUEST_INFO")
    as_of = _roll(tools, req_date).isoformat()

    splits = [c for c in tools.get_corporate_actions(instr) if c.get('type') == 'split']
    settled = 0
    for t in tools.get_ledger(acct, instr):
        if t['date'] <= as_of:
            q = t['qty']
            for sp in splits:
                if t['date'] < sp['date'] <= as_of:
                    q *= sp['ratio']
            settled += q
    settled = int(round(settled))

    if settled == 0:
        return _out("NOT_HELD", account_id=acct, instrument_id=instr, as_of=as_of)
    if settled < 0:
        return _out("ESCALATE", account_id=acct, instrument_id=instr)

    pend = [x for x in tools.get_instructions(acct, instr)
            if x['status'] == 'matched' and x['settle_date'] > as_of]
    pending = sum(x['qty'] for x in pend)
    pending_date = max(x['settle_date'] for x in pend) if pend else None

    fig = parse_figure(body)
    if fig is not None:
        def close(ref):
            return ref != 0 and abs(fig - ref) <= TOL * abs(ref)
        if not (close(settled) or (pending and close(settled + pending))):
            return _out("ESCALATE", account_id=acct, instrument_id=instr)

    res = _out("CONFIRMED", account_id=acct, instrument_id=instr, as_of=as_of, settled=settled)
    if pending:
        res['pending'] = pending
        res['pending_date'] = pending_date
    return res
