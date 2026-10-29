"""Operations-desk procedure: confirm a client's holding of a security.

Order of decisions (learned from histories + oracle):
  1. account must be identified uniquely            -> else REQUEST_INFO
  2. sender authorised for that account              -> else REQUEST_AUTHORIZATION
       (known contact, live entitlement level>=2 on the account, sender domain registered
        for the client, client accepts e-mail confirmations)
  3. client under legal hold                         -> ESCALATE
  4. instrument identified uniquely                  -> else REQUEST_INFO
  5. as-of date (relative to sent; roll back to business day); future date -> REQUEST_INFO
  6. settled position over ALL sub-accounts, split adjusted; zero -> NOT_HELD
  7. client's own figure must equal settled + matched pending (else ESCALATE)
  8. CONFIRMED with settled, and pending (sum of matched, settle_date > as_of) + latest date
"""
import re
import datetime as dt

_MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
           'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
_MONTH_RE = (r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|'
             r'aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)')
_WEEKDAYS = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4,
             'saturday': 5, 'sunday': 6}
_DISCLAIMER = 'This email and any attachments are confidential and intended solely for the addressee.'

OUT = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
       "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _res(outcome, **kw):
    r = dict(OUT)
    r["outcome"] = outcome
    r.update(kw)
    return r


# ----------------------------------------------------------------------------- text helpers
def _body(request):
    b = request.get("body") or ""
    b = b.replace(_DISCLAIMER, " ")
    # drop forwarded-message header block (its From/Date lines are not part of the request)
    b = re.sub(r'-{3,}\s*Forwarded message\s*-{3,}\s*(?:From:[^\n]*\n)?(?:Date:[^\n]*\n)?', ' ', b, flags=re.I)
    return re.sub(r'\s+', ' ', b).strip()


def _month(tok):
    return _MONTHS[tok.lower()[:3]]


def _mkdate(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def _last_day_prev_month(sent):
    return sent.replace(day=1) - dt.timedelta(days=1)


def _prev_weekday(sent, wd):
    d = sent - dt.timedelta(days=1)
    while d.weekday() != wd:
        d -= dt.timedelta(days=1)
    return d


def _cands(body, sent):
    """All date expressions found in the text as (start, end, date)."""
    out = []
    b = body

    def add(m, d):
        if d:
            out.append((m.start(), m.end(), d))

    for m in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b', b):
        add(m, _mkdate(*m.groups()))
    for m in re.finditer(r'\b(\d{4})/(\d{1,2})/(\d{1,2})\b', b):
        add(m, _mkdate(*m.groups()))
    for m in re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)?[-\s.]+(' + _MONTH_RE + r')\.?[-\s,.]+(\d{4})\b', b, re.I):
        add(m, _mkdate(m.group(3), _month(m.group(2)), m.group(1)))
    for m in re.finditer(r'\b(' + _MONTH_RE + r')\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', b, re.I):
        add(m, _mkdate(m.group(3), _month(m.group(1)), m.group(2)))
    for m in re.finditer(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', b):
        a, c, y = int(m.group(1)), int(m.group(2)), m.group(3)
        d = _mkdate(y, a, c) if a <= 12 else _mkdate(y, c, a)
        add(m, d)
    spans = [(s, e) for s, e, _ in out]

    def free(m):
        return not any(s <= m.start() < e for s, e in spans)

    # day + month without a year
    for m in re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)?[-\s]+(' + _MONTH_RE + r')\b(?![-\s,.]*\d{4})', b, re.I):
        if free(m):
            d = _mkdate(sent.year, _month(m.group(2)), m.group(1))
            if d and d > sent:
                d = _mkdate(sent.year - 1, _month(m.group(2)), m.group(1))
            add(m, d)
    for m in re.finditer(r'\b(' + _MONTH_RE + r')\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})', b, re.I):
        if free(m):
            d = _mkdate(sent.year, _month(m.group(1)), m.group(2))
            if d and d > sent:
                d = _mkdate(sent.year - 1, _month(m.group(1)), m.group(2))
            add(m, d)

    low = b.lower()
    for m in re.finditer(r'\byesterday\b', low):
        out.append((m.start(), m.end(), sent - dt.timedelta(days=1)))
    for m in re.finditer(r'\btoday\b', low):
        out.append((m.start(), m.end(), sent))
    for m in re.finditer(r'\b(\d{1,2}|one|two|three|four|five) days? ago\b', low):
        n = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}.get(m.group(1)) or int(m.group(1))
        out.append((m.start(), m.end(), sent - dt.timedelta(days=n)))
    for m in re.finditer(r'\b(?:end of (?:the )?(?:last|previous|prior) month|last day of (?:the )?(?:last|previous|prior) month|'
                         r'month[- ]end|end of (?:the )?month|end of month)\b', low):
        out.append((m.start(), m.end(), _last_day_prev_month(sent)))
    for m in re.finditer(r'\b(?:end of (?:the )?(?:last|previous|prior) quarter|quarter[- ]end|end of (?:the )?quarter)\b', low):
        q0 = dt.date(sent.year, 3 * ((sent.month - 1) // 3) + 1, 1)
        out.append((m.start(), m.end(), q0 - dt.timedelta(days=1)))
    for m in re.finditer(r'\b(?:year[- ]end|end of (?:the )?(?:last|previous|prior) year|end of (?:the )?year)\b', low):
        out.append((m.start(), m.end(), dt.date(sent.year - 1, 12, 31)))
    for m in re.finditer(r'\b(?:end of (?:the )?(?:last|previous|prior) week|close of (?:the )?(?:last|previous|prior) week)\b', low):
        out.append((m.start(), m.end(), _prev_weekday(sent, 4)))
    for m in re.finditer(r'\blast (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', low):
        out.append((m.start(), m.end(), _prev_weekday(sent, _WEEKDAYS[m.group(1)])))
    out.sort(key=lambda t: t[0])
    return out


_CUE_RE = re.compile(r'(?:as of|as at|position date|dated|date|on|for|at)\s*[:,]?\s*'
                     r'(?:close of business|cob|the close of|end of day|eod)?\s*(?:\w{3,9}\s)?$', re.I)


def _parse_date(body, sent):
    """Date the client asks about, or None if no date is given."""
    c = _cands(body, sent)
    if not c:
        return None
    # prefer an expression introduced by a date cue
    for s, e, d in c:
        if _CUE_RE.search(body[max(0, s - 40):s]):
            return d
    return c[0][2]


_NUM = r'(\d[\d,]*(?:\.\d+)?)\s*(k|mm|m|million|thousand)?\b'


def _to_val(numtxt, suffix):
    """Return (value, tolerance); tolerance is half a unit of the last written digit for
    abbreviated quantities such as 12.5k or 1.2mm (exact otherwise)."""
    t = numtxt.replace(',', '')
    try:
        v = float(t)
    except Exception:
        return None
    s = (suffix or '').lower()
    mult = 1
    if s in ('k', 'thousand'):
        mult = 1000
    elif s in ('mm', 'm', 'million'):
        mult = 1000000
    val = int(round(v * mult))
    tol = 0
    if mult > 1:
        dec = len(t.split('.')[1]) if '.' in t else 0
        tol = (mult / (10 ** dec)) / 2.0
    return val, tol


_CUES = (r'(?:our figure is|figure is|our figure|we show|we have|our records show|records show|we hold|'
         r'our books show|books show|our records reflect|we are showing|showing|reflects?|we record|we see|'
         r'our records indicate|we carry|holding of|balance of)')


def _stated_qty(body):
    """Quantity the client quotes, as (value, tolerance) or None."""
    m = re.search(_CUES + r'\s*:?\s*(?:a position of\s*)?(?:approximately\s*|approx\.?\s*|about\s*|c\.\s*)?' + _NUM,
                  body, re.I)
    if m:
        return _to_val(m.group(1), m.group(2))
    return None


# ----------------------------------------------------------------------------- resolution
def _variants(text, kind):
    t = (text or '').strip()
    out = [t]
    t2 = t.strip(' \t\r\n.,;:()[]"\'')
    out.append(t2)
    t3 = re.sub(r'\s+', ' ', t2)
    out.append(t3)
    if kind == 'account':
        t4 = re.sub(r'^(?:acct|a/c|account|fund|acc)\s*[:.]?\s+(?=\S)', '', t3, flags=re.I)
        out.append(t4)
        for m in re.finditer(r'\bACC[-\s]?(\d{4,6})\b', t3, re.I):
            out.append('ACC-' + m.group(1))
        for m in re.finditer(r'\bSA[-\s]?(\d{4,8})\b', t3, re.I):
            out.append('SA-' + m.group(1))
    else:
        for m in re.finditer(r'\b[A-Z]{2}[A-Z0-9]{9}\d\b', t3.upper()):
            out.append(m.group(0))
        t4 = re.sub(r'^(?:ticker|symbol|security|isin)\s*[:.]?\s+(?=\S)', '', t3, flags=re.I)
        out.append(t4)
    seen, res = set(), []
    for v in out:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            res.append(v)
    return res


def _resolve_account(tools, text):
    if not text or not str(text).strip():
        return None, 'missing'
    for v in _variants(text, 'account'):
        hits = tools.search_accounts(v)
        if len(hits) == 1:
            return hits[0]['id'], None
        if len(hits) > 1:
            return None, 'ambiguous'
    return None, 'none'


def _resolve_instrument(tools, text):
    if not text or not str(text).strip():
        return None, 'missing'
    for v in _variants(text, 'instrument'):
        hits = tools.search_instruments(v)
        if len(hits) == 1:
            return hits[0]['id'], None
        if len(hits) > 1:
            t = v.strip().lower()
            cur = [h for h in hits if t in (h['ticker'].lower(), h['name'].lower(), h['id'].lower())]
            if len(cur) == 1:
                return cur[0]['id'], None
            return None, 'ambiguous'
    return None, 'none'


def _authorized(tools, request, account_id, sent_iso):
    """Known contact with a live entitlement (level >= 2) on the account, writing from one of the
    client's registered domains."""
    sender = (request.get("from") or "").strip()
    contact = tools.get_contact(sender)
    if not contact:
        return False
    ok = False
    for e in tools.get_entitlements(contact['contact_id']):
        if e['account_id'] == account_id and e['level'] >= 2 and e['expires'] >= sent_iso:
            ok = True
    if not ok:
        return False
    prof = tools.get_client_profile(account_id)
    if prof is not None:
        dom = sender.split('@')[-1].strip().lower()
        if dom not in [d.lower() for d in prof.get('domains', [])]:
            return False
    return True


# ----------------------------------------------------------------------------- position
def _position(tools, account_id, instrument_id, as_of_iso):
    """Settled quantity over ALL custody sub-accounts up to as_of, adjusted for splits that
    happened on or before as_of (holdings recorded before the split date are multiplied)."""
    led = tools.get_ledger(account_id, instrument_id)
    acts = tools.get_corporate_actions(instrument_id)
    total = 0
    for t in led:
        if t['date'] > as_of_iso:
            continue
        q = t['qty']
        for a in acts:
            if a.get('type') == 'split' and t['date'] < a['date'] <= as_of_iso:
                q = q * a['ratio']
        total += q
    return total, bool(led)


def _pending(tools, account_id, instrument_id, as_of_iso):
    rows = [x for x in tools.get_instructions(account_id, instrument_id)
            if x['status'] == 'matched' and x['settle_date'] > as_of_iso]
    if not rows:
        return None, None
    return sum(x['qty'] for x in rows), max(x['settle_date'] for x in rows)


def _as_of(tools, body, sent):
    d = _parse_date(body, sent)
    assumed = d is None
    if d is None:
        d = sent
    cal = tools.get_calendar(d.isoformat())
    iso = d.isoformat() if cal['business_day'] else cal['previous_business_day']
    return d, iso, assumed


# ----------------------------------------------------------------------------- main
def _respond(request, tools):
    sent_iso = request.get("sent")
    sent = dt.date.fromisoformat(sent_iso)
    mentions = request.get("mentions") or {}
    body = _body(request)

    # 1. account
    acct, aerr = _resolve_account(tools, mentions.get("account_text"))
    if aerr:
        return _res("REQUEST_INFO")

    # 2. authorisation and client channel rules
    if not _authorized(tools, request, acct, sent_iso):
        return _res("REQUEST_AUTHORIZATION")
    prof = tools.get_client_profile(acct) or {}
    if prof.get('no_email_confirm'):
        return _res("REQUEST_AUTHORIZATION")

    inst, ierr = _resolve_instrument(tools, mentions.get("instrument_text"))

    # 3. legal hold
    if prof.get('legal_hold'):
        extra = {}
        if inst:
            try:
                _, as_of, assumed = _as_of(tools, body, sent)
                settled, _ = _position(tools, acct, inst, as_of)
                extra = dict(as_of=as_of, as_of_assumed=assumed, settled=settled)
            except Exception:
                extra = {}
        return _res("ESCALATE", account_id=acct, instrument_id=inst, **extra)

    # 4. instrument
    if ierr:
        return _res("REQUEST_INFO")

    # 5. date
    raw, as_of, assumed = _as_of(tools, body, sent)
    if raw > sent:
        return _res("REQUEST_INFO")

    # 6. position
    settled, has_ledger = _position(tools, acct, inst, as_of)
    if not has_ledger or settled == 0:
        return _res("NOT_HELD", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed)

    pend, pdate = _pending(tools, acct, inst, as_of)
    total = settled + (pend or 0)

    # 7. the client's own figure must agree with our total (settled + matched pending)
    stated = _stated_qty(body)
    if stated is not None:
        val, tol = stated
        if abs(val - total) > tol:
            return _res("ESCALATE", account_id=acct, instrument_id=inst, as_of=as_of,
                        as_of_assumed=assumed, settled=settled)

    # 8.
    return _res("CONFIRMED", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed,
                settled=settled, pending=pend, pending_date=pdate)


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:
        return _res("REQUEST_INFO")
