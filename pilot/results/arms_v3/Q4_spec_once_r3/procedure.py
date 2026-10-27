"""Position-confirmation desk procedure (see spec.md). Deterministic, stdlib only."""
import re
import datetime as dt

TOLERANCE = 0.10
MIN_LEVEL = 2

_MON = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
_WD = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}


def _out(outcome, acc=None, ins=None, as_of=None, settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins,
            "as_of": as_of, "as_of_assumed": False, "settled": settled,
            "pending": pending, "pending_date": pending_date}


def _clean_body(body):
    lines = []
    for line in (body or '').split('\n'):
        s = line.strip()
        if re.match(r'^(from|date|to|sent|subject|cc)\s*:', s, re.I):
            continue  # forwarded-message headers
        if s.startswith('-----'):
            continue
        lines.append(line)
    return '\n'.join(lines)


def _month_end(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _prev_month_end(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _parse_date(text, sent):
    found = []

    def add(pos, d):
        if d is not None:
            found.append((pos, d))

    for m in re.finditer(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', text):
        add(m.start(), _safe_date(int(m[1]), int(m[2]), int(m[3])))
    for m in re.finditer(r'\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b', text):
        y = int(m[3]); y = y + 2000 if y < 100 else y
        add(m.start(), _safe_date(y, int(m[1]), int(m[2])))
    # 27-Jan-2026, 3 Jan 2026, 22 December 2025
    for m in re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\.?[- ,]+(\d{4})\b', text):
        mo = _MON.get(m[2][:3].lower())
        if mo:
            add(m.start(), _safe_date(int(m[3]), mo, int(m[1])))
    # January 27, 2026 / Jan 27 2026
    for m in re.finditer(r'\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b', text):
        mo = _MON.get(m[1][:3].lower())
        if mo and m[1][:3].lower() not in _WD:
            add(m.start(), _safe_date(int(m[3]), mo, int(m[2])))
    tl = text.lower()
    # end of <Month> [year]
    for m in re.finditer(r'\bend of ([a-z]{3,9})(?:,? (\d{4}))?\b', tl):
        mo = _MON.get(m[1][:3])
        if mo and m[1] not in ('last', 'the', 'month', 'previous', 'prior'):
            y = int(m[2]) if m[2] else sent.year
            d = _month_end(y, mo)
            if not m[2] and d > sent:
                d = _month_end(y - 1, mo)
            add(m.start(), d)
    rel = [
        (r'\bday before yesterday\b', lambda m: sent - dt.timedelta(days=2)),
        (r'\byesterday\b', lambda m: sent - dt.timedelta(days=1)),
        (r'\btoday\b|\bclose of business today\b', lambda m: sent),
        (r'\b(\d+) days ago\b', lambda m: sent - dt.timedelta(days=int(m[1]))),
        (r'\blast (mon|tues|wednes|thurs|fri|satur|sun)day\b',
         lambda m: sent - dt.timedelta(days=((sent.weekday() - _WD[m[1][:3]] - 1) % 7) + 1)),
        (r'month[- ]end|end of (?:the )?(?:last|previous|prior) month|last day of (?:the )?(?:last|previous|prior) month'
         r'|last business day of (?:the )?(?:last|previous|prior) month|end of month|\bmonth end\b',
         lambda m: _prev_month_end(sent)),
        (r'year[- ]end|end of (?:last|the previous|previous) year',
         lambda m: dt.date(sent.year - 1, 12, 31)),
    ]
    for pat, fn in rel:
        for m in re.finditer(pat, tl):
            add(m.start(), fn(m))
            break
    if not found:
        return None
    found.sort(key=lambda x: x[0])
    return found[0][1]


def _parse_qty(text):
    m = re.search(r'(?:records show|figure is|we show|we have|our figure of|our books show|balance of|show)'
                  r'\s*:?\s*(-?\(?[\d,]*\.?\d+\)?)\s*(mm|mn|m|k|bn)?\b', text, re.I)
    if not m:
        return None
    raw = m[1]
    neg = raw.startswith('-') or raw.startswith('(')
    raw = raw.strip('-()').replace(',', '')
    try:
        num = float(raw)
    except ValueError:
        return None
    num *= {'k': 1e3, 'm': 1e6, 'mm': 1e6, 'mn': 1e6, 'bn': 1e9, '': 1}[(m[2] or '').lower()]
    num = int(round(num))
    return -num if neg else num


def _business_day(tools, d):
    c = tools.get_calendar(d.isoformat())
    return d if c['business_day'] else dt.date.fromisoformat(c['previous_business_day'])


def _authorized(tools, sender, account_id, sent):
    contact = tools.get_contact(sender)
    if not contact:
        return False
    domain = sender.split('@')[-1].strip().lower()
    prof = tools.get_client_profile(account_id) or {}
    if domain not in [x.lower() for x in prof.get('domains', [])]:
        return False
    for e in tools.get_entitlements(contact['contact_id']):
        if e['account_id'] == account_id and e['level'] >= MIN_LEVEL and e['expires'] >= sent:
            return True
    return False


def _sender_plausible(tools, sender):
    """For requests with no identifiable account: is the sender a known contact writing from a
    domain registered to at least one account they are entitled to?"""
    contact = tools.get_contact(sender)
    if not contact:
        return False
    domain = sender.split('@')[-1].strip().lower()
    for e in tools.get_entitlements(contact['contact_id']):
        prof = tools.get_client_profile(e['account_id']) or {}
        if domain in [x.lower() for x in prof.get('domains', [])]:
            return True
    return False


def _within(client, ours):
    if ours == 0:
        return client == 0
    return abs(client - ours) <= TOLERANCE * abs(ours)


def respond(request, tools):
    sender = (request.get('from') or '').strip()
    sent = dt.date.fromisoformat(request['sent'][:10])
    mentions = request.get('mentions') or {}
    acc_text = (mentions.get('account_text') or '').strip()
    ins_text = (mentions.get('instrument_text') or '').strip()
    body = _clean_body(request.get('body') or '')

    # 1. account resolution
    accounts = tools.search_accounts(acc_text) if acc_text else []
    if len(accounts) != 1:
        if len(accounts) > 1:
            return _out("REQUEST_INFO")
        if not _sender_plausible(tools, sender):
            return _out("REQUEST_AUTHORIZATION")
        return _out("REQUEST_INFO")
    acc = accounts[0]['id']

    # 2. authorization
    if not _authorized(tools, sender, acc, sent.isoformat()):
        return _out("REQUEST_AUTHORIZATION")

    # 3. completeness: instrument and date
    instruments = tools.search_instruments(ins_text) if ins_text else []
    if len(instruments) != 1:
        return _out("REQUEST_INFO")
    ins = instruments[0]['id']
    req_date = _parse_date(body, sent)
    if req_date is None or req_date >= sent:
        return _out("REQUEST_INFO")

    # 4. legal hold
    prof = tools.get_client_profile(acc) or {}
    if prof.get('legal_hold'):
        return _out("ESCALATE", acc, ins)

    # 5. figure: all sub-accounts, split-adjusted, as of previous business day if needed
    as_of = _business_day(tools, req_date).isoformat()
    splits = [c for c in tools.get_corporate_actions(ins) if c.get('type') == 'split']
    settled = 0
    for t in tools.get_ledger(acc, ins):
        if t['date'] <= as_of:
            q = t['qty']
            for s in splits:
                if t['date'] < s['date'] <= as_of:
                    q *= s['ratio']
            settled += q
    pend = [x for x in tools.get_instructions(acc, ins)
            if x['status'] == 'matched' and x['settle_date'] > as_of]
    pending = sum(x['qty'] for x in pend)
    pending_date = max((x['settle_date'] for x in pend), default=None)

    client = _parse_qty(body)

    if settled < 0:
        return _out("ESCALATE", acc, ins)
    if settled == 0:
        r = _out("NOT_HELD", acc, ins, as_of)
        return r

    if client is not None and not (_within(client, settled) or (pending and _within(client, settled + pending))):
        return _out("ESCALATE", acc, ins)

    if pending:
        return _out("CONFIRMED", acc, ins, as_of, settled, pending, pending_date)
    return _out("CONFIRMED", acc, ins, as_of, settled)
