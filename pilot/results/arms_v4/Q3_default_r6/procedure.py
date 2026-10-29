import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

LARGE = 1000000
PENDING_MIN = 1000


def _mon(s):
    return MONTHS[s[:3].lower()]


def _iso(d):
    return d.isoformat()


def parse_date(body, sent):
    """Return (date or None, found_phrase_bool)."""
    b = body
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    # ignore the forwarded header date line
    cands = []
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", b):
        cands.append((m.start(), dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
    body_wo_hdr = b
    if b.startswith("---------- Forwarded"):
        parts = b.split("\n\n", 1)
        body_wo_hdr = parts[1] if len(parts) > 1 else b
        cands = []
        for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", body_wo_hdr):
            cands.append((m.start(), dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
    b = body_wo_hdr
    for m in re.finditer(r"\b(\d{1,2})[- ]" + MON_RE + r"[- ,]*(\d{4})\b", b, re.I):
        cands.append((m.start(), dt.date(int(m.group(3)), _mon(m.group(2)), int(m.group(1)))))
    for m in re.finditer(MON_RE + r"\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", b, re.I):
        cands.append((m.start(), dt.date(int(m.group(3)), _mon(m.group(1)), int(m.group(2)))))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b):
        cands.append((m.start(), dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))))
    if cands:
        cands.sort()
        return cands[0][1]
    lb = b.lower()
    if re.search(r"\byesterday\b", lb):
        return sent - dt.timedelta(days=1)
    if re.search(r"(end of last month|last day of (the )?last month|last day of (the )?previous month|end of (the )?previous month|month[- ]end)", lb):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1)
    if re.search(r"\b(today|close of business today)\b", lb):
        return sent
    return None


def parse_qty(s):
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)(k|mm|m)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"k": 1e3, "mm": 1e6, "m": 1e6, None: 1}[m.group(2)]
    return int(round(v * mult))


def stated_qty(body):
    m = re.search(r"(?:We have|We show|Our records show|our figure is|We hold)\s+(-?[\d,\.]+(?:k|mm|m)?)", body, re.I)
    if m:
        t = m.group(1).rstrip(".")
        neg = t.startswith("-")
        v = parse_qty(t.lstrip("-"))
        return -v if (neg and v is not None) else v
    return None


def resolve_account(tools, text):
    if not text:
        return []
    return tools.search_accounts(text)


def resolve_instrument(tools, text):
    if not text:
        return []
    return tools.search_instruments(text)


def prev_bd(tools, d):
    return dt.date.fromisoformat(tools.get_calendar(_iso(d))["previous_business_day"])


def settled_qty(tools, acct, inst, as_of):
    total = 0
    splits = tools.get_corporate_actions(inst)
    for t in tools.get_ledger(acct, inst):
        if t["date"] <= as_of:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= as_of:
                    q *= s["ratio"]
            total += q
    return total


def base(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    body = request["body"]
    sent = dt.date.fromisoformat(request["sent"])
    m = request.get("mentions") or {}
    contact = tools.get_contact(request["from"])
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # --- identify account
    acct_hits = resolve_account(tools, m.get("account_text"))
    if not m.get("account_text"):
        live = {e["account_id"] for e in ents}
        if len(live) == 1:
            acct_hits = [tools.get_account(next(iter(live)))]
    if len(acct_hits) != 1:
        return base("REQUEST_INFO")
    acct = acct_hits[0]["id"]
    ent_ok = any(e["account_id"] == acct and e["level"] >= 3 and e["expires"] >= request["sent"] for e in ents)
    if not contact or not ent_ok:
        return base("REQUEST_AUTHORIZATION")
    inst_hits = resolve_instrument(tools, m.get("instrument_text"))
    if len(inst_hits) != 1:
        return base("REQUEST_INFO")
    inst = inst_hits[0]["id"]

    prof = tools.get_client_profile(acct) or {}
    if prof.get("no_email_confirm") or prof.get("legal_hold"):
        return base("REQUEST_AUTHORIZATION")

    d = parse_date(body, sent)
    assumed = d is None
    if assumed:
        d = sent
    if d > sent or not tools.get_calendar(_iso(d))["business_day"]:
        return base("REQUEST_INFO")

    as_of = _iso(d)
    settled = settled_qty(tools, acct, inst, as_of)
    sq = stated_qty(body)

    pend_items = [x for x in tools.get_instructions(acct, inst)
                  if x["status"] == "matched" and x["settle_date"] > as_of]

    if settled == 0:
        return base("NOT_HELD", account_id=acct, instrument_id=inst, as_of=as_of, as_of_assumed=assumed)
    if abs(settled) >= LARGE:
        return base("ESCALATE", account_id=acct, instrument_id=inst)
    if sq is not None and sq != settled:
        ok = sq == settled + sum(x["qty"] for x in pend_items) or any(sq == settled + x["qty"] for x in pend_items)
        if not ok:
            return base("ESCALATE", account_id=acct, instrument_id=inst)

    mat = [x for x in pend_items if x["qty"] >= PENDING_MIN]
    pend = pdate = None
    if mat:
        pend = sum(x["qty"] for x in mat)
        pdate = min(x["settle_date"] for x in mat)
    return base("CONFIRMED", account_id=acct, instrument_id=inst, as_of=as_of,
                as_of_assumed=assumed, settled=settled, pending=pend, pending_date=pdate)
