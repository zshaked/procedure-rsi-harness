"""Holding-confirmation desk procedure (implements spec.md, revised rules)."""
import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
MON_RE = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'


def _out(outcome, account_id=None, instrument_id=None, as_of=None, as_of_assumed=False,
         settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": as_of_assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


# ---------------------------------------------------------------- text helpers
def _clean_body(body):
    lines = []
    for ln in (body or '').splitlines():
        if re.match(r'\s*(from|date|sent|to|cc|subject)\s*:', ln, re.I):
            continue
        if re.match(r'\s*-{3,}.*forwarded', ln, re.I):
            continue
        lines.append(ln)
    return ' '.join(' '.join(lines).split())


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _parse_date(text, sent):
    """Return (date|None, found_flag). found_flag True if the text names a date."""
    low = text.lower()
    s = sent
    if re.search(r'\bday before yesterday\b', low):
        return s - dt.timedelta(days=2), True
    if re.search(r'\byesterday\b', low):
        return s - dt.timedelta(days=1), True
    if re.search(r'\b(?:as (?:of|at)|position date)\s+(?:close of business\s+|cob\s+)?(?:today|this morning|now)\b', low):
        return s, True
    if re.search(r'(end of (?:the )?(?:last|previous|prior) month|last day of (?:the )?(?:last|previous|prior) month|'
                 r'(?:last |previous |prior )?month[- ]end|end[- ]of[- ]month|last month[- ]end)', low):
        return s.replace(day=1) - dt.timedelta(days=1), True
    m = re.search(r'(?:last|previous) (' + '|'.join(WEEKDAYS) + r')\b', low)
    if m:
        wd = WEEKDAYS.index(m.group(1))
        d = s - dt.timedelta(days=1)
        while d.weekday() != wd:
            d -= dt.timedelta(days=1)
        return d, True
    # ISO / YYYY/MM/DD
    m = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', text)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, True
    # M/D/YYYY (US) ; also M/D/YY
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', text)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        a, b = int(m.group(1)), int(m.group(2))
        d = _mk(y, a, b) if a <= 12 else _mk(y, b, a)
        if d:
            return d, True
    # D.M.YYYY or D-M-YYYY (numeric, European)
    m = re.search(r'\b(\d{1,2})[.-](\d{1,2})[.-](\d{4})\b', text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        d = _mk(int(m.group(3)), b, a) if b <= 12 else _mk(int(m.group(3)), a, b)
        if d:
            return d, True
    # D Mon YYYY / D-Mon-YYYY / Dth of Month, YYYY
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?(?: of)?[\s-]+' + MON_RE + r'\.?[\s,-]+(\d{4})\b', low)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))
        if d:
            return d, True
    # Mon D, YYYY
    m = re.search(r'\b' + MON_RE + r'\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', low)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2)))
        if d:
            return d, True
    # Without year: "Mon D" / "D Mon" -> most recent such date not after sent
    m = re.search(r'\b(?:as (?:of|at)|position date|close of business|cob)\s+(?:\w+day,?\s+)?(?:'
                  + MON_RE + r'\.?\s+(\d{1,2})(?:st|nd|rd|th)?|(\d{1,2})(?:st|nd|rd|th)?\s+' + MON_RE + r')\b', low)
    if m:
        if m.group(1):
            mo, da = MONTHS[m.group(1)[:3]], int(m.group(2))
        else:
            mo, da = MONTHS[m.group(4)[:3]], int(m.group(3))
        d = _mk(s.year, mo, da)
        if d and d > s:
            d = _mk(s.year - 1, mo, da)
        if d:
            return d, True
    return None, False


_QTY_NUM = r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k|mm|mn|m|bn|million|thousand)?\b'
_MULT = {'k': 1e3, 'thousand': 1e3, 'm': 1e6, 'mm': 1e6, 'mn': 1e6, 'million': 1e6, 'bn': 1e9}


def _parse_qty(text):
    """Return (value, precision) of the client's stated figure, or (None, None)."""
    pats = [
        r'(?:we show|we have|we hold|our figure is|our records show|our books show|records show|'
        r'books show|we see|we record|reconciles? to|figure of|balance of|holding of|position of)\s*:?\s*(?:a (?:holding|position|balance) of\s*)?'
        + _QTY_NUM,
        _QTY_NUM + r'\s*(?:shares|units|sh\b|shs\b)',
    ]
    for p in pats:
        for m in re.finditer(p, text, re.I):
            raw, unit = m.group(1), (m.group(2) or '').lower()
            # skip things that are clearly years/dates
            v = float(raw.replace(',', ''))
            mult = _MULT.get(unit, 1)
            if unit == '' and '.' in raw:
                # "12.5" without unit: treat literally
                pass
            val = v * mult
            if unit:
                dec = len(raw.split('.')[1]) if '.' in raw else 0
                prec = mult / (10 ** dec)
            else:
                prec = 1
            return int(round(val)), prec
    return None, None


# ---------------------------------------------------------------- resolution
_ACC_PREFIX = re.compile(r'^(?:our |the )?(?:account|acct\.?|a/c|fund|portfolio|sub-?account)\s*(?:no\.?|number|#|:)?\s*', re.I)


def _resolve_account(tools, text, body):
    cands = []
    if text and text.strip():
        t = text.strip().strip('.,;:()"\'')
        cands.append(t)
        t2 = _ACC_PREFIX.sub('', t).strip()
        if t2 and t2 != t:
            cands.append(t2)
    else:
        ids = re.findall(r'\b(ACC-\d+|SA-\d+)\b', body or '', re.I)
        if len(set(i.upper() for i in ids)) == 1:
            cands.append(ids[0])
    for c in cands:
        hits = tools.search_accounts(c)
        if hits:
            ids = sorted(set(h['id'] for h in hits))
            return ids
    return []


def _resolve_instrument(tools, text):
    if not text or not text.strip():
        return []
    t = text.strip().strip('.,;:()"\'')
    cands = [t]
    first = t.split()[0] if t.split() else t
    if first != t:
        cands.append(first)
    for c in cands:
        hits = tools.search_instruments(c)
        if hits:
            return sorted(set(h['id'] for h in hits))
    return []


# ---------------------------------------------------------------- authorization
def _authorized(tools, sender, account_id, sent_iso):
    sender = (sender or '').strip().lower()
    m = re.search(r'<([^>]+)>', sender)
    if m:
        sender = m.group(1)
    contact = tools.get_contact(sender)
    if not contact:
        return False
    ents = tools.get_entitlements(contact['contact_id'])
    valid = [e for e in ents if e.get('account_id') == account_id
             and (e.get('level') or 0) >= 2
             and (not e.get('expires') or e['expires'] >= sent_iso)]
    if not valid:
        return False
    domain = sender.rsplit('@', 1)[-1] if '@' in sender else ''
    prof = tools.get_client_profile(account_id) or {}
    doms = set(d.lower() for d in prof.get('domains', []))
    if domain in doms:
        return True
    # a known corporate user: sender's domain registered to another client the contact is entitled on
    for e in ents:
        p = tools.get_client_profile(e.get('account_id')) or {}
        if domain in set(d.lower() for d in p.get('domains', [])):
            return True
    return False


# ---------------------------------------------------------------- positions
def _settled(tools, acc, ins, as_of, adjust=True):
    cas = [c for c in tools.get_corporate_actions(ins) if c.get('type') == 'split']
    total = 0
    for t in tools.get_ledger(acc, ins):
        if t['date'] <= as_of:
            q = t['qty']
            if adjust:
                for c in cas:
                    if t['date'] < c['date'] <= as_of:
                        q = q * c['ratio']
            total += q
    return int(round(total))


def _pending(tools, acc, ins, as_of):
    xs = [x for x in tools.get_instructions(acc, ins)
          if x.get('status') == 'matched' and x.get('settle_date') and x['settle_date'] > as_of]
    if not xs:
        return None, None
    return sum(x['qty'] for x in xs), max(x['settle_date'] for x in xs)


def _matches(claim, prec, figure):
    if prec and prec > 1:
        return abs(figure - claim) <= prec / 2.0
    return claim == figure


# ---------------------------------------------------------------- main
def respond(request, tools):
    mentions = request.get('mentions') or {}
    sent_iso = (request.get('sent') or '')[:10]
    sent = dt.date.fromisoformat(sent_iso)
    body = request.get('body') or ''
    text = _clean_body(body)

    # 1. account
    accs = _resolve_account(tools, mentions.get('account_text'), text)
    if len(accs) != 1:
        return _out('REQUEST_INFO')
    acc = accs[0]

    # 2. sender authorization
    if not _authorized(tools, request.get('from'), acc, sent_iso):
        return _out('REQUEST_AUTHORIZATION')
    prof = tools.get_client_profile(acc) or {}
    # 3. client does not accept e-mail confirmations
    if prof.get('no_email_confirm'):
        return _out('REQUEST_AUTHORIZATION')

    # 4. instrument
    insts = _resolve_instrument(tools, mentions.get('instrument_text'))
    # 5. legal hold
    if prof.get('legal_hold'):
        return _out('ESCALATE', acc, insts[0] if len(insts) == 1 else None)
    if len(insts) != 1:
        return _out('REQUEST_INFO')
    ins = insts[0]

    # 6. date
    d, found = _parse_date(text, sent)
    if found and d is None:
        return _out('REQUEST_INFO')
    if d is None:
        as_of = tools.get_calendar(sent_iso)['previous_business_day']
        assumed = True
    else:
        if d > sent:
            return _out('REQUEST_INFO')
        if d == sent:
            as_of = tools.get_calendar(sent_iso)['previous_business_day']
        else:
            cal = tools.get_calendar(d.isoformat())
            as_of = d.isoformat() if cal['business_day'] else cal['previous_business_day']
        assumed = False

    # 7. figures
    settled = _settled(tools, acc, ins, as_of)
    if settled <= 0:
        return _out('NOT_HELD', acc, ins, as_of, assumed)
    pend, pend_date = _pending(tools, acc, ins, as_of)
    total = settled + (pend or 0)

    claim, prec = _parse_qty(text)
    if claim is not None:
        unadj = _settled(tools, acc, ins, as_of, adjust=False) + (pend or 0)
        if not (_matches(claim, prec, total) or _matches(claim, prec, unadj)):
            return _out('ESCALATE', acc, ins)

    return _out('CONFIRMED', acc, ins, as_of, assumed, settled, pend, pend_date)
