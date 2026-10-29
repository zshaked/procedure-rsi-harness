"""Procedure for the securities-holding confirmation desk.

Rules (induced from 25 histories + 15 oracle answers):
  1. Account: ambiguous / unknown name -> REQUEST_INFO.  No account named -> use the sender's single
     entitlement (if exactly one), else REQUEST_INFO.
  2. Authorization (checked before anything else is validated): sender must be a known contact with an
     unexpired entitlement of level >= 3 on THAT account, otherwise REQUEST_AUTHORIZATION.
  3. Instrument missing / unresolved -> REQUEST_INFO.
  4. Date: none -> date of the email (assumed).  Not a business day, or in the future -> REQUEST_INFO.
  5. Account flags: no_email_confirm -> REQUEST_AUTHORIZATION, legal_hold -> ESCALATE.
  6. Position = ledger across ALL sub-accounts up to and including as_of, restated for splits that took
     effect on/before as_of.  Zero -> NOT_HELD (even if the client claims shares).
  7. Position >= 1,000,000 -> ESCALATE.  Client figure more than 5% away from settled (and from
     settled + pending) -> ESCALATE.
  8. Otherwise CONFIRMED; pending = matched instructions settling after as_of, reported only when the
     total is material (>= 1,000), pending_date = earliest settle date.
"""
import re
import datetime as dt

# ----------------------------------------------------------------- config
MIN_LEVEL = 3
LARGE_POSITION = 1_000_000     # positions at or above this size are escalated
PENDING_MIN_QTY = 1000         # pending below this is immaterial and not reported
FIG_TOLERANCE = 0.05           # client figure may differ from ours by this fraction

_MON = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
_MONFULL = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6, 'july': 7,
            'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12, 'sept': 9}


def _d(s):
    return dt.date.fromisoformat(s)


def _month(name):
    n = name.lower().rstrip('.')
    if n in _MONFULL:
        return _MONFULL[n]
    if len(n) == 3 and n in _MON:
        return _MON[n]
    return None


# ----------------------------------------------------------------- parsing
def _strip_forward_header(body):
    return re.sub(r'(?im)^\s*(From|Date|Sent|To|Cc|Subject):.*$', '', body)


def parse_requested_date(body, sent):
    """Return the date asked for, or None when the email gives no date."""
    s = _d(sent)
    t = _strip_forward_header(body)
    m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', t)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?[-\s]([A-Za-z]{3,9})\.?[-\s,]*(\d{4})\b', t)
    if m and _month(m[2]):
        try:
            return dt.date(int(m[3]), _month(m[2]), int(m[1]))
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', t)
    if m:
        try:
            return dt.date(int(m[3]), int(m[1]), int(m[2]))  # US month/day/year
        except ValueError:
            pass
    m = re.search(r'\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', t)
    if m and _month(m[1]):
        try:
            return dt.date(int(m[3]), _month(m[1]), int(m[2]))
        except ValueError:
            pass
    tl = t.lower()
    if re.search(r'\bday before yesterday\b', tl):
        return s - dt.timedelta(days=2)
    if re.search(r'\byesterday\b', tl):
        return s - dt.timedelta(days=1)
    if re.search(r'\btoday\b', tl):
        return s
    if re.search(r'(end of (the )?(last|previous) month|last day of (the )?(last|previous) month|'
                 r'(last|previous) month[- ]end|month[- ]end|end of (the )?month)', tl):
        return s.replace(day=1) - dt.timedelta(days=1)
    return None


def parse_qty(s):
    s = s.replace(',', '').strip()
    m = re.fullmatch(r'(-?\d+(?:\.\d+)?)\s*(k|mm|m|million)?', s, re.I)
    if not m:
        return None
    v = float(m[1])
    u = (m[2] or '').lower()
    if u == 'k':
        v *= 1e3
    elif u in ('m', 'mm', 'million'):
        v *= 1e6
    return int(round(v))


def client_figure(body):
    t = _strip_forward_header(body)
    m = re.search(r'(?:we have|we show|we hold|our records show|our books show|our figure is|'
                  r'our records indicate)\s+(-?\d[\d,]*(?:\.\d+)?)(?:\s?(k|mm|million|m)\b)?',
                  t, re.I)
    if m:
        return parse_qty(m[1] + (m[2] or ''))
    return None


# ----------------------------------------------------------------- lookups
def _clean(text):
    t = text.strip()
    t = re.sub(r'^(?:our|the)\s+', '', t, flags=re.I)
    t = re.sub(r'^(?:a/c|acct|account|fund)\s+', '', t, flags=re.I)
    return t.strip(' .,;:')


def _find_accounts(tools, text):
    if not text or not text.strip():
        return []
    hits = tools.search_accounts(text)
    if hits:
        return hits
    c = _clean(text)
    if c and c != text:
        hits = tools.search_accounts(c)
        if hits:
            return hits
    m = re.search(r'\b(ACC-\d+|SA-\d+)\b', text, re.I)
    if m:
        return tools.search_accounts(m[1].upper())
    return []


def _find_instruments(tools, text):
    if not text or not text.strip():
        return []
    hits = tools.search_instruments(text)
    if hits:
        return hits
    c = _clean(text)
    if c and c != text:
        hits = tools.search_instruments(c)
        if hits:
            return hits
    m = re.search(r'\b([A-Z]{2}[A-Z0-9]{9}\d)\b', text)
    if m:
        return tools.search_instruments(m[1])
    return []


def _entitled(tools, contact, account_id, sent):
    if not contact:
        return False
    for e in tools.get_entitlements(contact['contact_id']):
        if e['account_id'] == account_id and e['level'] >= MIN_LEVEL and e['expires'] >= sent:
            return True
    return False


def _position(tools, account_id, instrument_id, as_of):
    splits = tools.get_corporate_actions(instrument_id)
    tot = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t['date'] > as_of:
            continue
        q = t['qty']
        for s in splits:
            if s['date'] <= as_of and t['date'] < s['date']:
                q *= s['ratio']
        tot += q
    return tot


def _pending(tools, account_id, instrument_id, as_of):
    """(total, earliest settle date) of matched instructions settling after as_of."""
    rows = [x for x in tools.get_instructions(account_id, instrument_id)
            if x['status'] == 'matched' and x['settle_date'] > as_of]
    if not rows:
        return 0, None
    return sum(x['qty'] for x in rows), min(x['settle_date'] for x in rows)


def _blank(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ----------------------------------------------------------------- main
def respond(request, tools):
    sent = request['sent']
    body = request.get('body', '') or ''
    m = request.get('mentions') or {}
    contact = tools.get_contact(request['from'])

    # 1. account
    atext = m.get('account_text')
    if not atext:
        # extractor found nothing: look for an explicit id in the text, then fall back to the sender
        mm = re.search(r'\b(ACC-\d{3,}|SA-\d{3,})\b', _strip_forward_header(body))
        atext = mm[1] if mm else None
    if atext:
        accts = _find_accounts(tools, atext)
        if len(accts) != 1:
            return _blank("REQUEST_INFO")
    else:
        ids = []
        if contact:
            ids = sorted({e['account_id'] for e in tools.get_entitlements(contact['contact_id'])})
        if len(ids) != 1:
            return _blank("REQUEST_INFO")
        acc = tools.get_account(ids[0])
        if not acc:
            return _blank("REQUEST_INFO")
        accts = [acc]
    acct = accts[0]['id']

    # 2. authorization
    if not _entitled(tools, contact, acct, sent):
        return _blank("REQUEST_AUTHORIZATION")

    # 3. instrument
    itext = m.get('instrument_text')
    if not itext:
        mm = re.search(r'\b([A-Z]{2}[A-Z0-9]{9}\d)\b', _strip_forward_header(body))
        itext = mm[1] if mm else None
    insts = _find_instruments(tools, itext)
    if len(insts) != 1:
        return _blank("REQUEST_INFO")
    inst = insts[0]['id']

    # 4. date
    req = parse_requested_date(body, sent)
    assumed = req is None
    asof = req if req is not None else _d(sent)
    asof_s = asof.isoformat()
    if asof > _d(sent) or not tools.get_calendar(asof_s)['business_day']:
        return _blank("REQUEST_INFO")

    # 5. account flags
    prof = tools.get_client_profile(acct) or {}
    settled = _position(tools, acct, inst, asof_s)
    if prof.get('no_email_confirm'):
        return _blank("REQUEST_AUTHORIZATION")
    if prof.get('legal_hold'):
        return _blank("ESCALATE", account_id=acct, instrument_id=inst, as_of=asof_s,
                      as_of_assumed=assumed, settled=settled)

    # 6. nothing held
    if settled == 0:
        return _blank("NOT_HELD", account_id=acct, instrument_id=inst, as_of=asof_s,
                      as_of_assumed=assumed)

    pend_total, pend_date = _pending(tools, acct, inst, asof_s)

    # 7. escalations
    escalate = abs(settled) >= LARGE_POSITION
    fig = client_figure(body)
    if fig is not None and not escalate:
        ok = abs(fig - settled) <= FIG_TOLERANCE * abs(settled)
        if not ok and pend_total:
            tot = settled + pend_total
            ok = abs(fig - tot) <= FIG_TOLERANCE * abs(tot)
        escalate = not ok
    if escalate:
        return _blank("ESCALATE", account_id=acct, instrument_id=inst, as_of=asof_s,
                      as_of_assumed=assumed, settled=settled)

    # 8. confirm
    pend = pend_total if pend_total >= PENDING_MIN_QTY else None
    return _blank("CONFIRMED", account_id=acct, instrument_id=inst, as_of=asof_s,
                  as_of_assumed=assumed, settled=settled,
                  pending=pend, pending_date=pend_date if pend else None)
