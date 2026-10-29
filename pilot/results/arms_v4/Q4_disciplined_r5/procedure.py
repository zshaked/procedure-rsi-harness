import re, datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MISMATCH_TOL = 0.10   # relative difference between client's figure and ours above which we escalate
MIN_LEVEL = 2


def _iso(d):
    return d.isoformat()


def parse_date(body, sent):
    """Returns (date|None). Free-text dates relative to sent."""
    s = dt.date.fromisoformat(sent)
    b = body
    low = b.lower()
    m = re.search(r'(?:as of|as at|position date,?)\s+(?:close of business\s+)?(.*)', b, re.I)
    seg = None
    # strip forwarded header lines "Date: 2026-02-02"
    text = re.sub(r'^Date:.*$', '', b, flags=re.M)
    low = text.lower()
    m = re.search(r'(?:as of|as at|position date,?)\s+([^\n]*)', text, re.I)
    if not m:
        return None
    seg = m.group(1)
    sl = seg.lower()
    if sl.startswith('yesterday'):
        return s - dt.timedelta(days=1)
    if sl.startswith('today'):
        return s
    if re.match(r'(the )?(last day of last month|end of last month|month-end|month end|end of month)', sl):
        first = s.replace(day=1)
        return first - dt.timedelta(days=1)
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', seg)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', seg)
    if m:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.search(r'(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]*(\d{4})', seg)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r'([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})', seg)
    if m and m.group(1).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def parse_qty(body):
    m = re.search(r'(?:records show|we show|figure is|we have)\s+(-?[\d][\d,\.]*)\s*(k|mm|m)?\b', body, re.I)
    if not m:
        return None
    num = float(m.group(1).replace(',', '').rstrip('.'))
    suf = (m.group(2) or '').lower()
    if suf == 'k':
        num *= 1000
    elif suf in ('mm', 'm'):
        num *= 1000000
    return int(round(num))


def resolve_account(text, tools):
    if not text:
        return []
    return [a['id'] for a in tools.search_accounts(text)]


def resolve_instrument(text, tools):
    if not text:
        return []
    return [i['id'] for i in tools.search_instruments(text)]


def position(tools, acct, inst, as_of):
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if t['date'] <= as_of:
            q = t['qty']
            for sp in splits:
                if t['date'] < sp['date'] <= as_of:
                    q *= sp['ratio']
            total += q
    return total


def pending(tools, acct, inst, as_of):
    ins = [x for x in tools.get_instructions(acct, inst)
           if x['status'] == 'matched' and x['settle_date'] > as_of]
    if not ins:
        return None, None
    return sum(x['qty'] for x in ins), max(x['settle_date'] for x in ins)


def _r(outcome, acct=None, inst=None, as_of=None, assumed=False, settled=None, pend=None, pdate=None):
    return {"outcome": outcome, "account_id": acct, "instrument_id": inst, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pend, "pending_date": pdate}


def decide(request, tools):
    sender = request['from'].lower()
    sent = request['sent']
    men = request.get('mentions') or {}
    body = request['body']
    domain = sender.split('@')[-1]
    contact = tools.get_contact(sender)
    if not contact:
        return _r("REQUEST_AUTHORIZATION"), "unknown_sender"
    allents = tools.get_entitlements(contact['contact_id'])

    def dom_ok(aid):
        p = tools.get_client_profile(aid)
        return bool(p) and domain in [d.lower() for d in p['domains']]

    atext = men.get('account_text')
    accts = resolve_account(atext, tools)
    if len(accts) != 1:
        if not any(dom_ok(e['account_id']) for e in allents):
            return _r("REQUEST_AUTHORIZATION"), "auth_domain_noacct"
        if not atext:
            return _r("REQUEST_INFO"), "account_missing"
        if not accts:
            return _r("REQUEST_INFO"), "account_notfound"
        return _r("REQUEST_INFO"), "account_ambiguous"
    acct = accts[0]
    mine = [e for e in allents if e['account_id'] == acct]
    if not mine:
        return _r("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    valid = [e for e in mine if e['expires'] >= sent]
    if not valid:
        return _r("REQUEST_AUTHORIZATION"), "auth_expired"
    if not any(e['level'] >= MIN_LEVEL for e in valid):
        return _r("REQUEST_AUTHORIZATION"), "auth_low_level"
    if not dom_ok(acct):
        return _r("REQUEST_AUTHORIZATION"), "auth_domain"
    itext = men.get('instrument_text')
    insts = resolve_instrument(itext, tools)
    if len(insts) != 1:
        b = "instrument_missing" if not itext else ("instrument_notfound" if not insts else "instrument_ambiguous")
        return _r("REQUEST_INFO", acct), b
    inst = insts[0]
    d = parse_date(body, sent)
    if d is None:
        return _r("REQUEST_INFO", acct, inst), "no_date"
    if _iso(d) > sent:
        return _r("REQUEST_INFO", acct, inst), "future_date"
    prof = tools.get_client_profile(acct)
    if prof.get('legal_hold'):
        # oracle (Q4-0114): ESCALATE rejected, reason pointed at REQUEST_INFO
        return _r("REQUEST_INFO", acct, inst), "legal_hold"
    # no_email_confirm: oracle (Q4-0054) says confirm normally (with pending) -> flag ignored
    cal = tools.get_calendar(_iso(d))
    as_of = _iso(d) if cal['business_day'] else cal['previous_business_day']
    settled = position(tools, acct, inst, as_of)
    pq, pd_ = pending(tools, acct, inst, as_of)
    claimed = parse_qty(body)
    if claimed is not None:
        b = settled + (pq or 0)   # oracle (Q4-0155): compare against settled + matched pending
        rel = abs(claimed - b) / abs(b) if b else (0 if claimed == 0 else 1)
        if rel > MISMATCH_TOL and not (settled == 0 and not pq):
            return _r("ESCALATE", acct, inst, as_of, False, settled), "qty_mismatch"
    if settled == 0 and not pq:
        # oracle (Q4-0130): a client's claimed figure does not matter when we hold nothing
        return _r("NOT_HELD", acct, inst, as_of, False), ("not_held_claimed" if claimed else "not_held")
    has_split = any(sp['date'] <= as_of for sp in tools.get_corporate_actions(inst))
    b = "confirm_pending" if pq else ("confirm_split" if has_split else "confirm_plain")
    return _r("CONFIRMED", acct, inst, as_of, False, settled, pq, pd_), b


def respond(request, tools):
    return decide(request, tools)[0]
