"""Induced procedure for the holdings-confirmation desk."""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

REQUIRED_LEVEL = 3
PENDING_WINDOW_DAYS = 30
FIGURE_TOLERANCE = 0.05


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _clean_body(body):
    keep = []
    for line in body.split("\n"):
        s = line.strip()
        if re.match(r"^(from|date|sent|to|subject)\s*:", s, re.I):
            continue
        if s.startswith("----------"):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        keep.append(line)
    return "\n".join(keep)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _end_of_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(text, sent):
    """Returns (status, date): status in 'none', 'ok', 'bad'."""
    t = text.lower()
    found = []
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        found.append(_mk(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t):
        found.append(_mk(int(m.group(3)), int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[-\s]" + MON_RE + r"[a-z]*\.?[-\s,]+(\d{4})\b", t):
        found.append(_mk(int(m.group(3)), MON3[m.group(2)[:3]], int(m.group(1))))
    for m in re.finditer(r"\b" + MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t):
        found.append(_mk(int(m.group(3)), MON3[m.group(1)[:3]], int(m.group(2))))
    if found:
        if any(f is None for f in found):
            return "bad", None
        if len(set(found)) > 1:
            return "bad", None
        return "ok", found[0]
    if re.search(r"\b(end of last month|last day of last month|last month[- ]end|month[- ]end|end of (?:the )?previous month|end of month)\b", t):
        return "ok", _end_of_prev_month(sent)
    if re.search(r"\byesterday\b", t):
        return "ok", sent - dt.timedelta(days=1)
    if re.search(r"\b(today|this morning|current(?:ly)?|as of now|latest)\b", t):
        return "ok", sent
    return "none", None


def parse_qty(s):
    s = s.strip().lower().replace(",", "")
    mult = 1
    if s.endswith("mm"):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def stated_figure(text):
    t = text.lower()
    m = re.search(r"(?:figure is|we have|we show|records show|our books show|we hold|holding of|our position is|shows?)\s+"
                  r"(-?\d[\d,]*(?:\.\d+)?\s*(?:mm|m|k)?)\b", t)
    if not m:
        return None
    return parse_qty(m.group(1).replace(" ", ""))


def _prev_bd(tools, d):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def respond(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    ment = request.get("mentions") or {}
    acc_text = (ment.get("account_text") or "").strip()
    ins_text = (ment.get("instrument_text") or "").strip()
    body = _clean_body(request.get("body") or "")
    sender = (request.get("from") or "").strip().lower()

    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    valid_ents = [e for e in ents if e["expires"] >= sent.isoformat()]

    # 1. resolve account
    if acc_text:
        hits = tools.search_accounts(acc_text)
        if len(hits) != 1:
            return _out("REQUEST_INFO")
        account_id = hits[0]["id"]
    else:
        cands = sorted({e["account_id"] for e in valid_ents})
        if len(cands) != 1:
            return _out("REQUEST_INFO")
        account_id = cands[0]

    # 2. authorization
    if not contact:
        return _out("REQUEST_AUTHORIZATION")
    if not any(e["account_id"] == account_id and e["level"] >= REQUIRED_LEVEL for e in valid_ents):
        return _out("REQUEST_AUTHORIZATION")

    # 3. instrument
    if not ins_text:
        return _out("REQUEST_INFO")
    ins = tools.search_instruments(ins_text)
    if len(ins) != 1:
        return _out("REQUEST_INFO")
    instrument_id = ins[0]["id"]

    profile = tools.get_client_profile(account_id) or {}
    if profile.get("legal_hold"):
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    if profile.get("no_email_confirm"):
        return _out("REQUEST_AUTHORIZATION")

    # 4. date
    status, req_date = parse_date(body, sent)
    if status == "bad":
        return _out("REQUEST_INFO")
    assumed = status == "none"
    if assumed:
        req_date = sent
    if req_date > sent:
        return _out("REQUEST_INFO")
    as_of = _prev_bd(tools, req_date)
    as_iso = as_of.isoformat()

    # 5. settled position: all sub-accounts, split-adjusted
    splits = [c for c in tools.get_corporate_actions(instrument_id) if c.get("type") == "split"]
    settled = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_iso:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_iso:
                q *= s["ratio"]
        settled += q

    # 6. pending: matched instructions settling after as_of and soon after the email
    instrs = tools.get_instructions(account_id, instrument_id)
    pend, pend_date = 0, None
    limit = (sent + dt.timedelta(days=PENDING_WINDOW_DAYS)).isoformat()
    all_pending = 0
    for x in instrs:
        if x["status"] == "matched" and x["settle_date"] > as_iso:
            all_pending += x["qty"]
            if x["settle_date"] <= limit:
                pend += x["qty"]
                pend_date = max(pend_date or "", x["settle_date"])

    # 7. client's own figure must agree (within tolerance) with settled, or settled incl. pending
    fig = stated_figure(body)
    if fig is not None:
        def close(ours):
            if ours == fig:
                return True
            return ours > 0 and fig > 0 and abs(fig - ours) <= FIGURE_TOLERANCE * ours
        if not (close(settled) or close(settled + all_pending)):
            return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)

    if settled < 0:
        return _out("ESCALATE", account_id=account_id, instrument_id=instrument_id)
    if settled == 0:
        return _out("NOT_HELD", account_id=account_id, instrument_id=instrument_id,
                    as_of=as_iso, as_of_assumed=assumed)
    return _out("CONFIRMED", account_id=account_id, instrument_id=instrument_id, as_of=as_iso,
                as_of_assumed=assumed, settled=settled,
                pending=pend if pend_date else None, pending_date=pend_date)
