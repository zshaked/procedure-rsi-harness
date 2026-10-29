"""Procedure induced for the position-confirmation desk.

Deterministic; standard library + the `tools` argument only.

Decision order (first rule that fires wins):
  1. account text must resolve to exactly one account          -> else REQUEST_INFO
  2. sender must be a known contact writing from a domain on the account's profile, with a live
     entitlement (not expired at the sent date) of level >= 2   -> else REQUEST_AUTHORIZATION
  3. account flagged no_email_confirm                           -> REQUEST_AUTHORIZATION
  4. account on legal hold                                      -> ESCALATE
  5. security must resolve to exactly one instrument            -> else REQUEST_INFO
  6. settled position (all sub-accounts, ledger <= as_of, split adjusted) == 0 -> NOT_HELD
  7. client's own figure present and equal to neither settled nor settled+pending -> ESCALATE
  8. otherwise CONFIRMED, with matched pending settlements (settle date after as_of) reported:
     pending = sum of quantities, pending_date = latest settle date.
"""
import re
import datetime as dt

_MON = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
_MONFULL = 'january|february|march|april|may|june|july|august|september|october|november|december'
_MONANY = _MONFULL + '|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec'
_WD = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
MIN_LEVEL = 2


# ---------------------------------------------------------------- text helpers
def _clean_body(body):
    body = re.sub(r'---------- Forwarded message ---------', '', body)
    body = re.sub(r'(?m)^\s*(?:From|Date|Sent|To|Cc|Subject):[^\n]*$', '', body)
    body = re.sub(r'This email and any attachments.*', '', body, flags=re.S)
    return body


def _month_end_prev(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _parse_date(body, sent):
    """The date the client asks about (literal or relative to the sent date), or None."""
    b = body
    m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', b)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d
    m = re.search(r'\b(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]*(\d{4})\b', b)
    if m and m.group(2).lower()[:3] in _MON and re.fullmatch(_MONANY, m.group(2).lower()):
        d = _mk(int(m.group(3)), _MON[m.group(2).lower()[:3]], int(m.group(1)))
        if d:
            return d
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', b)
    if m:  # US month/day/year
        d = _mk(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return d
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(' + _MONANY + r')\.?,?\s+(\d{4})\b', b, re.I)
    if m:
        d = _mk(int(m.group(3)), _MON[m.group(2)[:3].lower()], int(m.group(1)))
        if d:
            return d
    m = re.search(r'\b(' + _MONANY + r')\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', b, re.I)
    if m:
        d = _mk(int(m.group(3)), _MON[m.group(1)[:3].lower()], int(m.group(2)))
        if d:
            return d
    low = b.lower()
    if re.search(r'\byesterday\b', low):
        return sent - dt.timedelta(days=1)
    if re.search(r'\b(?:today|close of business today|cob today)\b', low):
        return sent
    if re.search(r'(end of last month|last day of last month|last month[- ]?end|month[- ]?end|end of the month|end of month|last day of the month)', low):
        return _month_end_prev(sent)
    if re.search(r'(end of last quarter|last quarter[- ]?end|quarter[- ]?end)', low):
        qs = dt.date(sent.year, 3 * ((sent.month - 1) // 3) + 1, 1)
        return qs - dt.timedelta(days=1)
    if re.search(r'(end of last year|year[- ]?end|last day of last year)', low):
        return dt.date(sent.year - 1, 12, 31)
    m = re.search(r'\b(?:last|previous|this past)\s+(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b', low)
    if m:
        target = _WD[m.group(1)]
        d = sent - dt.timedelta(days=1)
        while d.weekday() != target:
            d -= dt.timedelta(days=1)
        return d
    if re.search(r'end of last week|last week[- ]?end', low):
        d = sent - dt.timedelta(days=1)
        while d.weekday() != 4:
            d -= dt.timedelta(days=1)
        return d
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(' + _MONANY + r')\b', b, re.I)  # no year
    if m:
        mo = _MON[m.group(2)[:3].lower()]
        d = _mk(sent.year, mo, int(m.group(1)))
        if d and d > sent:
            d = _mk(sent.year - 1, mo, int(m.group(1)))
        if d:
            return d
    return None


_NUM = r'(\d[\d,]*(?:\.\d+)?)\s*(k|mm|m)?(?![A-Za-z0-9])'


def _figure_from(num, suf):
    v = float(num.replace(',', ''))
    s = (suf or '').lower()
    tol = 0.0
    if s in ('k', 'mm', 'm'):
        mult = 1000 if s == 'k' else 1000000
        dec = len(num.split('.')[1]) if '.' in num else 0
        tol = mult * 0.5 * (10 ** (-dec))
        v *= mult
    return int(round(v)), tol


def _client_figure(body):
    """(value, tolerance) of the quantity the client quotes, or None."""
    pats = [r'our figure is\s+' + _NUM, r'records show\s+' + _NUM, r'we show\s+' + _NUM,
            r'we have\s+' + _NUM + r'\s+(?:shares|units)', r'figure of\s+' + _NUM,
            r'(?:books|records|ledger)\s+(?:show|shows|indicate|indicates|reflect|reflects)\s+' + _NUM,
            r'we (?:hold|holding|record|see|carry)\s+' + _NUM,
            r'our (?:figure|number|balance|position)\s+(?:is|of)\s+' + _NUM,
            _NUM + r'\s+(?:shares|units)\s+on our books']
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            return _figure_from(m.group(1), m.group(2))
    return None


def _fig_ok(fig, candidates):
    val, tol = fig
    return any(abs(val - c) <= tol or val == c for c in candidates)


# ---------------------------------------------------------------- resolution
def _variants(text):
    t = ' '.join(text.split())
    out = [t]
    t2 = re.sub(r'^(?:our\s+)?(?:the\s+)?(?:account|acct|a/c|fund)\s+', '', t, flags=re.I)
    t2 = t2.strip(' .,;:()')
    if t2 and t2 not in out:
        out.append(t2)
    return out


def _resolve_account(text, tools):
    if not text or not text.strip():
        return None
    for v in _variants(text):
        hits = tools.search_accounts(v)
        if len(hits) == 1:
            return hits[0]['id']
        if len(hits) > 1:
            return None
    return None


def _resolve_instrument(text, tools):
    if not text or not text.strip():
        return None
    t = ' '.join(text.split()).strip(' .,;:()')
    hits = tools.search_instruments(t)
    ids = sorted({h['id'] for h in hits})
    if len(ids) == 1:
        return ids[0]
    return None


# ---------------------------------------------------------------- state
def _roll(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal['business_day']:
        return d
    return dt.date.fromisoformat(cal['previous_business_day'])


def _settled(account_id, instrument_id, as_of, tools):
    splits = tools.get_corporate_actions(instrument_id)
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t['date'] > as_of:
            continue
        q = t['qty']
        for s in splits:
            if s['date'] <= as_of and t['date'] < s['date']:
                q *= s['ratio']
        total += q
    return total


def _sender(addr):
    m = re.search(r'[\w.+\-]+@[\w.\-]+', addr or '')
    return (m.group(0) if m else (addr or '')).lower()


def _authorized(addr, account_id, sent, tools):
    c = tools.get_contact(addr)
    if not c:
        return False
    prof = tools.get_client_profile(account_id) or {}
    dom = addr.split('@')[-1].lower()
    if dom not in [d.lower() for d in prof.get('domains', [])]:
        return False
    for e in tools.get_entitlements(c['contact_id']):
        if e['account_id'] == account_id and e['level'] >= MIN_LEVEL and e['expires'] >= sent.isoformat():
            return True
    return False


def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _pending(account_id, instrument_id, as_of, tools):
    ms = [x for x in tools.get_instructions(account_id, instrument_id)
          if x['status'] == 'matched' and x['settle_date'] > as_of.isoformat()]
    if not ms:
        return None, None
    return sum(x['qty'] for x in ms), max(x['settle_date'] for x in ms)


# ---------------------------------------------------------------- entry point
def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _blank('REQUEST_INFO')


def _respond(request, tools):
    sent = dt.date.fromisoformat(request['sent'])
    men = request.get('mentions') or {}
    body = _clean_body(request.get('body', ''))
    sender = _sender(request.get('from'))

    acc = _resolve_account(men.get('account_text'), tools)
    if acc is None:
        return _blank('REQUEST_INFO')
    prof = tools.get_client_profile(acc) or {}

    if not _authorized(sender, acc, sent, tools):
        return _blank('REQUEST_AUTHORIZATION')
    if prof.get('no_email_confirm'):
        return _blank('REQUEST_AUTHORIZATION')

    ins = _resolve_instrument(men.get('instrument_text'), tools)
    asked = _parse_date(body, sent)
    assumed = asked is None
    if assumed:
        asked = sent
    as_of = _roll(asked, tools)
    out = _blank('CONFIRMED')
    out.update(account_id=acc, instrument_id=ins, as_of=as_of.isoformat(), as_of_assumed=assumed)

    if prof.get('legal_hold'):
        out['outcome'] = 'ESCALATE'
        if ins is not None:
            out['settled'] = _settled(acc, ins, as_of.isoformat(), tools)
        return out

    if ins is None:
        return _blank('REQUEST_INFO')

    settled = _settled(acc, ins, as_of.isoformat(), tools)
    if settled == 0:
        out['outcome'] = 'NOT_HELD'
        return out

    pend, pend_date = _pending(acc, ins, as_of, tools)
    fig = _client_figure(body)
    if fig is not None and not _fig_ok(fig, [settled, settled + (pend or 0)]):
        out['outcome'] = 'ESCALATE'
        out['settled'] = settled
        return out

    out['settled'] = settled
    out['pending'] = pend
    out['pending_date'] = pend_date
    return out
