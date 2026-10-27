"""Position-confirmation desk procedure (implements spec.md final rules)."""
import re
import datetime as dt

LARGE = 1_000_000
TOL = 0.05

MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
MON_RE = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
DATE_HINT = re.compile(r'\b(as of|as at|position date|close of business|cob|dated?|on)\b', re.I)


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


def _clean_body(body):
    b = re.sub(r'-+\s*Forwarded message\s*-+\s*\n(?:\s*(?:From|Date|To|Subject|Sent):.*\n)*', '\n', body or '')
    b = re.split(r'\n\s*This email and any attachments', b)[0]
    return b


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return False  # invalid explicit date


def _year_for(m, d, sent):
    y = sent.year
    c = _mk(y, m, d)
    if c and c > sent:
        y -= 1
    return y


def parse_date(body, sent):
    """Return (date | None | False, kind). False = date text present but invalid/unparseable."""
    b = _clean_body(body)
    lb = b.lower()
    m = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', b)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), 'explicit'
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', b)
    if m:
        y = int(m[3]); y = y + 2000 if y < 100 else y
        return _mk(y, int(m[1]), int(m[2])), 'explicit'
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?' + MON_RE + r'\.?[\s\-,]+(\d{4})\b', lb)
    if m:
        return _mk(int(m[3]), MONTHS[m[2][:3]], int(m[1])), 'explicit'
    m = re.search(r'\b' + MON_RE + r'\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', lb)
    if m:
        return _mk(int(m[3]), MONTHS[m[1][:3]], int(m[2])), 'explicit'
    # year-less forms
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?' + MON_RE + r'\b', lb)
    if m:
        mo, d = MONTHS[m[2][:3]], int(m[1])
        return _mk(_year_for(mo, d, sent), mo, d), 'explicit'
    m = re.search(r'\b' + MON_RE + r'\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b', lb)
    if m:
        mo, d = MONTHS[m[1][:3]], int(m[2])
        return _mk(_year_for(mo, d, sent), mo, d), 'explicit'
    if re.search(r'\bday before yesterday\b', lb):
        return sent - dt.timedelta(days=2), 'relative'
    if re.search(r'\byesterday\b', lb):
        return sent - dt.timedelta(days=1), 'relative'
    if re.search(r'\b(today|this morning|close of business today|cob today)\b', lb):
        return sent, 'relative'
    first = sent.replace(day=1)
    if re.search(r'(end of last month|last day of (?:the )?(?:last|previous|prior) month|'
                 r'(?:last|previous|prior) month[- ]end|month[- ]end|end of (?:the )?(?:previous|prior) month)', lb):
        return first - dt.timedelta(days=1), 'relative'
    if re.search(r'(end of last year|year[- ]end|last day of last year)', lb):
        return dt.date(sent.year - 1, 12, 31), 'relative'
    if re.search(r'\b(as of|as at|position date)\b', lb):
        return False, 'unparsed'
    return None, 'none'


def parse_qty(t):
    t = t.strip().lower().replace(',', '').replace(' ', '')
    m = re.fullmatch(r'(-?\d+(?:\.\d+)?)(k|thousand|m|mm|mn|mio|million|bn|b|billion)?', t)
    if not m:
        return None
    mult = {None: 1, 'k': 1e3, 'thousand': 1e3, 'm': 1e6, 'mm': 1e6, 'mn': 1e6, 'mio': 1e6,
            'million': 1e6, 'b': 1e9, 'bn': 1e9, 'billion': 1e9}[m[2]]
    return int(round(float(m[1]) * mult))


QTY = r'(-?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|thousand|mm|mn|mio|million|m|bn|billion)\b)?)'


def client_figure(body):
    b = _clean_body(body)
    pats = [r'our figure is\s*' + QTY,
            r'(?:we|our records|our books|our records)\s+(?:have|show|shows|hold|holds|reflect|reflects)\s*' + QTY,
            r'records show\s*' + QTY,
            r'books show\s*' + QTY,
            r'we (?:hold|have|show)\s*' + QTY]
    for p in pats:
        m = re.search(p, b, re.I)
        if m:
            q = parse_qty(m.group(1))
            if q is not None:
                return q
    return None


def _resolve_account(req, tools, ents):
    text = (req.get('mentions') or {}).get('account_text')
    if text and text.strip():
        hits = tools.search_accounts(text)
        if len(hits) == 1:
            return hits[0]['id'], None
        return None, 'REQUEST_INFO'
    b = _clean_body(req.get('body', ''))
    ids = set()
    for tok in re.findall(r'\b(ACC-\d+|SA-\d+)\b', b, re.I):
        for h in tools.search_accounts(tok):
            ids.add(h['id'])
    if len(ids) == 1:
        return ids.pop(), None
    if len(ids) > 1:
        return None, 'REQUEST_INFO'
    # no account named: infer from sender's entitlements
    accs = sorted(set(e['account_id'] for e in ents))
    if len(accs) == 1:
        return accs[0], None
    return None, 'REQUEST_INFO'


def _resolve_instrument(req, tools):
    text = (req.get('mentions') or {}).get('instrument_text')
    if text and text.strip():
        hits = tools.search_instruments(text)
        if len(hits) == 1:
            return hits[0]['id']
        return None
    b = _clean_body(req.get('body', ''))
    ids = set()
    for tok in re.findall(r'\b([A-Z]{2}[A-Z0-9]{9}\d)\b', b):
        for h in tools.search_instruments(tok):
            ids.add(h['id'])
    return ids.pop() if len(ids) == 1 else None


def _settled(tools, acc, ins, as_of):
    cas = [c for c in tools.get_corporate_actions(ins) if c.get('type') == 'split']
    tot = 0
    for t in tools.get_ledger(acc, ins):
        if t['date'] <= as_of:
            q = t['qty']
            for c in cas:
                if t['date'] < c['date'] <= as_of:
                    q *= c['ratio']
            tot += q
    return tot


def respond(request, tools):
    sent_s = request.get('sent')
    sent = dt.date.fromisoformat(sent_s)
    contact = tools.get_contact(request.get('from', '') or '')
    ents = tools.get_entitlements(contact['contact_id']) if contact else []

    # 1. account
    acc, err = _resolve_account(request, tools, ents)
    if err:
        return _out(err)

    # 2. authorization
    ok = any(e['account_id'] == acc and e['level'] >= 3 and e['expires'] >= sent_s for e in ents)
    if not ok:
        return _out('REQUEST_AUTHORIZATION')

    # 3. instrument
    ins = _resolve_instrument(request, tools)
    if not ins:
        return _out('REQUEST_INFO')

    # 4. client does not accept email confirmations
    prof = tools.get_client_profile(acc) or {}
    if prof.get('no_email_confirm'):
        return _out('REQUEST_AUTHORIZATION')

    # 5. date
    d, kind = parse_date(request.get('body', ''), sent)
    if d is False:
        return _out('REQUEST_INFO')
    assumed = False
    if d is None:
        assumed = True
        cal = tools.get_calendar(sent_s)
        as_of = sent_s if cal['business_day'] else cal['previous_business_day']
    else:
        if d > sent:
            return _out('REQUEST_INFO')
        as_of = d.isoformat()
        if not tools.get_calendar(as_of)['business_day']:
            return _out('REQUEST_INFO')

    # 6. legal hold
    if prof.get('legal_hold'):
        return _out('ESCALATE', acc, ins)

    # 7-8. figure
    settled = _settled(tools, acc, ins, as_of)
    if settled == 0:
        return _out('NOT_HELD', acc, ins, as_of, assumed)
    if settled < 0 or settled >= LARGE:
        return _out('ESCALATE', acc, ins)

    pend = [x for x in tools.get_instructions(acc, ins)
            if x.get('status') == 'matched' and x['settle_date'] > as_of]
    pq = sum(x['qty'] for x in pend) if pend else None
    pdate = max(x['settle_date'] for x in pend) if pend else None

    fig = client_figure(request.get('body', ''))
    if fig is not None:
        close = abs(fig - settled) <= TOL * abs(settled)
        if not close and pq:
            close = abs(fig - (settled + pq)) <= TOL * abs(settled + pq)
        if not close:
            return _out('ESCALATE', acc, ins)

    return _out('CONFIRMED', acc, ins, as_of, assumed, settled, pq, pdate)
