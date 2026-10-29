"""Procedure induced for the confirmation desk.  Standard library + the `tools` argument only.

Pipeline (first rule that fires wins):
  1. account: named account (id / sub-account / name / short name); none named -> the sender's own
     single entitled account; unresolved or ambiguous -> REQUEST_INFO
  2. sender must hold a non-expired entitlement of level >= 3 on that account -> else REQUEST_AUTHORIZATION
  3. instrument missing / unresolved -> REQUEST_INFO
  4. date: none -> date of the email (assumed); not a business day or in the future -> REQUEST_INFO
  5. client that does not take email confirmations -> REQUEST_AUTHORIZATION
  6. legal hold -> ESCALATE
  7. position = ledger (all sub-accounts) up to and including as_of, split-adjusted;
     nothing held -> NOT_HELD; client's own figure far from ours -> ESCALATE; else CONFIRMED
     (+ matched, material instructions settling after as_of reported as pending)
"""
import re
import datetime as dt

MIN_LEVEL = 3
CLAIM_TOLERANCE = 0.05          # client figure within 5% of ours is fine ("confirm with the settled position")
MIN_PENDING = 1000              # smaller matched instructions are dust and are not reported

_MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_FULL = ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"]
MONTHS = {m: i + 1 for i, m in enumerate(_MON)}
MONTHS.update({m: i + 1 for i, m in enumerate(_FULL)})
MONTHS["sept"] = 9
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
            "saturday": 5, "sunday": 6}


# ----------------------------------------------------------------------------- dates
def _d(s):
    return dt.date.fromisoformat(s)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _body_core(body):
    """Drop forwarded-message header lines so their Date: is not read as the as-of date."""
    out = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|To|Cc|Sent|Subject):", s):
            continue
        out.append(ln)
    return "\n".join(out)


MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _mdy_slash(m):
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if a > 12 and b <= 12:          # day/month/year
        return _mk(y, b, a)
    return _mk(y, a, b)             # month/day/year


ABS_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
     lambda m: _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[-/ ]+(?:of )?" + MON_RE + r"\.?[-/ ,]*(\d{4})\b", re.I),
     lambda m: _mk(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))),
    (re.compile(r"\b" + MON_RE + r"\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", re.I),
     lambda m: _mk(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), _mdy_slash),
]


def _last_day_prev_month(s):
    return s.replace(day=1) - dt.timedelta(days=1)


def _last_day_prev_quarter(s):
    q_start = dt.date(s.year, 3 * ((s.month - 1) // 3) + 1, 1)
    return q_start - dt.timedelta(days=1)


def parse_date(body, sent, tools=None):
    """Requested position date (datetime.date) or None when the email names none."""
    text = _body_core(body)
    low = text.lower()
    hits = []
    for rx, fn in ABS_PATTERNS:
        for m in rx.finditer(text):
            d = fn(m)
            if d:
                hits.append((m.start(), d))
    if hits:
        hits.sort()
        return hits[0][1]
    s = _d(sent)
    if re.search(r"\b(end|last day|close) of (the )?(last|previous|prior) month\b", low) or \
       re.search(r"\blast day of (the )?(last|previous|prior) month\b", low) or \
       re.search(r"\b(last|previous|prior) month[- ]?end\b", low) or \
       re.search(r"\bmonth[- ]?end\b", low) or re.search(r"\b(end|close) of (the )?month\b", low) or \
       re.search(r"\blast day of (the )?month\b", low):
        return _last_day_prev_month(s)
    if re.search(r"\b(end|last day) of (the )?(last|previous|prior) quarter\b", low) or \
       re.search(r"\bquarter[- ]?end\b", low):
        return _last_day_prev_quarter(s)
    if re.search(r"\b(previous|prior|last) business day\b", low):
        if tools is not None:
            return _d(tools.get_calendar(s.isoformat())["previous_business_day"])
        return s - dt.timedelta(days=1)
    if re.search(r"\bday before yesterday\b", low):
        return s - dt.timedelta(days=2)
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1)
    if re.search(r"\b(today|close of business today|this morning|this afternoon)\b", low):
        return s
    m = re.search(r"\b(?:as (?:of|at)|position date|on)\s+(?:the\s+)?last (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
    if m:
        back = (s.weekday() - WEEKDAYS[m.group(1)]) % 7 or 7
        return s - dt.timedelta(days=back)
    return None


# ----------------------------------------------------------------------------- quantities
_SUFFIX = r"(?:\s?(?:mm|million|m|thousand|k)\b)?"
NUMTOK = r"(-?\(?\d[\d,]*(?:\.\d+)?" + _SUFFIX + r"\)?)"


def _num(tok):
    tok = tok.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    for suf, mu in (("million", 1_000_000), ("thousand", 1_000), ("mm", 1_000_000), ("m", 1_000_000), ("k", 1_000)):
        if tok.endswith(suf):
            mult, tok = mu, tok[: -len(suf)]
            break
    try:
        return int(round(float(tok) * mult))
    except ValueError:
        return None


def parse_figure(body):
    """The holding the client says it has, or None."""
    text = _body_core(body)
    pats = [
        r"we have\s+" + NUMTOK + r"\s*(?:shares|units)",
        r"(?:our )?(?:records|books) (?:show|have|indicate)s?\s+" + NUMTOK,
        r"we (?:show|hold|see)\s+" + NUMTOK,
        r"our (?:figure|number|position) is\s+" + NUMTOK,
    ]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            tok = m.group(1)
            neg = tok.startswith("-") or tok.startswith("(")
            v = _num(tok.strip("-()"))
            if v is not None:
                return -v if neg else v
    return None


# ----------------------------------------------------------------------------- entities
def resolve_account(tools, text):
    if not text:
        return "missing", None
    t = " ".join(text.split()).strip(" .,;:")
    hits = tools.search_accounts(t)
    if len(hits) == 1:
        return "ok", hits[0]["id"]
    if len(hits) > 1:
        return "ambiguous", [h["id"] for h in hits]
    return "unresolved", None


def infer_account(tools, email):
    """No account named ('our fund'): the sender's own entitled account, if unique."""
    c = tools.get_contact(email)
    if not c:
        return "unresolved", None
    accts = sorted({e["account_id"] for e in tools.get_entitlements(c["contact_id"])})
    if len(accts) == 1:
        return "ok", accts[0]
    if len(accts) > 1:
        dom = email.split("@")[-1].lower()
        by_dom = [a for a in accts if dom in [x.lower() for x in (tools.get_client_profile(a) or {}).get("domains", [])]]
        if len(by_dom) == 1:
            return "ok", by_dom[0]
        return "ambiguous", accts
    return "unresolved", None


def resolve_instrument(tools, text):
    if not text:
        return "missing", None
    t = " ".join(text.split()).strip(" .,;:")
    ids = sorted({h["id"] for h in tools.search_instruments(t)})
    if len(ids) == 1:
        return "ok", ids[0]
    if len(ids) > 1:
        return "ambiguous", ids
    return "unresolved", None


def authorized(tools, email, account_id, sent_iso):
    c = tools.get_contact(email)
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent_iso:
            return True
    return False


# ----------------------------------------------------------------------------- figures
def settled_position(tools, account_id, instrument_id, as_of):
    """Ledger over all sub-accounts up to and including as_of, restated for splits effective by as_of."""
    iso = as_of.isoformat()
    splits = [s for s in tools.get_corporate_actions(instrument_id) if s.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > iso:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= iso and t["date"] < s["date"]:
                q *= s["ratio"]
        total += q
    return total


def matched_after(tools, account_id, instrument_id, as_of):
    return [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > as_of.isoformat()]


def pending_info(tools, account_id, instrument_id, as_of):
    ins = [x for x in matched_after(tools, account_id, instrument_id, as_of) if x["qty"] >= MIN_PENDING]
    if not ins:
        return None, None
    return sum(x["qty"] for x in ins), min(x["settle_date"] for x in ins)


# ----------------------------------------------------------------------------- main
def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _respond(request, tools):
    sent_iso = request["sent"]
    sent = _d(sent_iso)
    m = request.get("mentions") or {}

    a_state, a_val = resolve_account(tools, m.get("account_text"))
    if a_state == "missing":
        a_state, a_val = infer_account(tools, request["from"])
    if a_state != "ok":
        return _blank("REQUEST_INFO")
    account_id = a_val

    if not authorized(tools, request["from"], account_id, sent_iso):
        return _blank("REQUEST_AUTHORIZATION")

    i_state, instrument_id = resolve_instrument(tools, m.get("instrument_text"))
    if i_state != "ok":
        return _blank("REQUEST_INFO")

    d = parse_date(request["body"], sent_iso, tools)
    assumed = d is None
    if assumed:
        d = sent
    if d > sent or not tools.get_calendar(d.isoformat())["business_day"]:
        return _blank("REQUEST_INFO")          # the desk asks which date they want
    as_of = d

    prof = tools.get_client_profile(account_id) or {}
    if prof.get("no_email_confirm"):
        return _blank("REQUEST_AUTHORIZATION")  # client does not take confirmations by email

    out = _blank(None)
    out.update({"account_id": account_id, "instrument_id": instrument_id,
                "as_of": as_of.isoformat(), "as_of_assumed": assumed})
    settled = settled_position(tools, account_id, instrument_id, as_of)
    claimed = parse_figure(request["body"])

    if prof.get("legal_hold"):
        out.update({"outcome": "ESCALATE", "settled": settled})
        return out
    if settled == 0:
        out["outcome"] = "NOT_HELD"
        return out
    if claimed is not None and claimed != settled:
        near = abs(claimed - settled) <= CLAIM_TOLERANCE * abs(settled)
        allp = sum(x["qty"] for x in matched_after(tools, account_id, instrument_id, as_of))
        explained = allp > 0 and claimed == settled + allp      # client counts unsettled matched items
        if not (near or explained):
            out.update({"outcome": "ESCALATE", "settled": settled})
            return out
    out["outcome"] = "CONFIRMED"
    out["settled"] = settled
    out["pending"], out["pending_date"] = pending_info(tools, account_id, instrument_id, as_of)
    return out


def respond(request, tools):
    try:
        return _respond(request, tools)
    except Exception:                      # never crash: ask the client instead
        return _blank("REQUEST_INFO")
