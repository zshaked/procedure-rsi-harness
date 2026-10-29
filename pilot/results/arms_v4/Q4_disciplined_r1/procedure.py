"""Operations-desk procedure: confirm a client's holding of a security.

respond(request, tools) -> dict ; decide(request, tools) -> (dict, branch)
Deterministic, standard library only, state read only through `tools`.

Decision list (first rule that fires decides; branch name in quotes):
  "unknown_sender"       sender not a known contact                       -> REQUEST_AUTHORIZATION
  no unique account named (ambiguous / not found / none):
    "sender_domain"      sender's domain not registered on any of his own accounts -> REQUEST_AUTHORIZATION
    "ambiguous_account" / "account_not_found" / "no_account"                -> REQUEST_INFO
  "no_entitlement"       sender has no entitlement on the account         -> REQUEST_AUTHORIZATION
  "sender_domain"        sender's domain not registered on the ASKED account (oracle Q10, Q11) -> REQUEST_AUTHORIZATION
  "expired_entitlement"  all of the sender's entitlements expired before `sent` -> REQUEST_AUTHORIZATION
  "auth_level"           best valid entitlement level < MIN_LEVEL         -> REQUEST_AUTHORIZATION
  "legal_hold"           account under legal hold                         -> ESCALATE   (no_email_confirm is ignored)
  "no_instrument" / "instrument_not_found" / "ambiguous_instrument"       -> REQUEST_INFO
  "no_date"              no position date in the e-mail                   -> REQUEST_INFO
  "future_date"          position date after the e-mail was sent          -> REQUEST_INFO
  "not_held"             nothing settled, nothing pending (even if the client states a figure) -> NOT_HELD
  "qty_mismatch"         client's figure differs from settled+pending by > QTY_TOL -> ESCALATE
  "confirm" / "confirm_pending" / "confirm_split"                         -> CONFIRMED
Figures: settled = ledger over all sub-accounts dated <= as_of (non-business day rolled back), entries
recorded before a split dated <= as_of multiplied by its ratio; pending = matched instructions settling
after as_of (sum, latest date).
"""
import datetime as dt
import re

# ----------------------------------------------------------------------------------------------
# parameters (conventions)
# ----------------------------------------------------------------------------------------------
MIN_LEVEL = 2            # entitlement level needed to be told a position
QTY_TOL = 0.10           # relative tolerance between the client's stated figure and ours

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
            r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")


# ----------------------------------------------------------------------------------------------
# parsing helpers
# ----------------------------------------------------------------------------------------------
def _clean_body(body):
    """Drop forwarded-message header lines and the confidentiality footer."""
    out = []
    for ln in (body or "").replace("\r", "").split("\n"):
        s = ln.strip()
        if re.match(r"^-{3,}.*forwarded message.*-{3,}$", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|cc|subject):", s, re.I):
            continue
        out.append(ln)
    text = "\n".join(out)
    text = re.sub(r"This email and any attachments are confidential.*", "", text, flags=re.I | re.S)
    return text


def _mon(s):
    return MONTHS[s.lower()[:3]]


def _safe_date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _month_end(y, m):
    nm = dt.date(y + (m // 12), (m % 12) + 1, 1)
    return nm - dt.timedelta(days=1)


_WD = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_date(text, sent):
    """Return (date or None, kind). kind in explicit|relative|none."""
    t = text
    sent_d = dt.date.fromisoformat(sent)
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", t)
    if m:
        d = _safe_date(*m.groups())
        if d:
            return d, "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s]+" + MONTH_RE + r"\.?,?[-\s]+(\d{4})\b", t, re.I)
    if m:
        d = _safe_date(m.group(3), _mon(m.group(2)), m.group(1))
        if d:
            return d, "explicit"
    m = re.search(r"\b" + MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        d = _safe_date(m.group(3), _mon(m.group(1)), m.group(2))
        if d:
            return d, "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _safe_date(y, a, b) if a <= 12 else _safe_date(y, b, a)
        if d:
            return d, "explicit"
    low = t.lower()
    if re.search(r"\byesterday\b", low):
        return sent_d - dt.timedelta(days=1), "relative"
    if re.search(r"\btoday\b", low):
        return sent_d, "relative"
    m = re.search(r"\blast (mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", low)
    if m:
        back = (sent_d.weekday() - _WD[m.group(1)]) % 7 or 7
        return sent_d - dt.timedelta(days=back), "relative"
    if re.search(r"(end of (the )?(last|previous|prior) month|last (business |working |trading |calendar )?day of (the )?(last|previous|prior) month|"
                 r"(last|previous|prior) month[- ]end|month[- ]end|end of (the )?month)", low):
        return sent_d.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"(end of (the )?(last|previous|prior) quarter|quarter[- ]end|end of (the )?quarter)", low):
        q = (sent_d.month - 1) // 3
        if q == 0:
            return dt.date(sent_d.year - 1, 12, 31), "relative"
        return _month_end(sent_d.year, 3 * q), "relative"
    if re.search(r"(year[- ]end|end of (the )?(last|previous|prior) year|end of (the )?year)", low):
        return dt.date(sent_d.year - 1, 12, 31), "relative"
    return None, "none"


_SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "mln": 1e6, "million": 1e6, "bn": 1e9, "b": 1e9}


_DATE_SCRUB = [
    r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b",
    r"\b\d{1,2}(?:st|nd|rd|th)?[-\s]+" + MONTH_RE + r"\.?,?[-\s]+\d{4}\b",
    r"\b" + MONTH_RE + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\bUS\d{10}\b|\bACC-\d+\b|\bSA-\d+\b",
]


def parse_quantity(text):
    """Client's stated figure, or None. Looks for a number in a sentence that talks about the client's own
    figure ("our records show", "we have ... on our books", "our figure is", ...)."""
    cue = re.compile(r"\b(?:[Ss]how|[Ss]hows|[Hh]ave|[Hh]old|[Ff]igure|[Rr]ecords|[Bb]ooks|[Bb]alance|[Cc]arry)\b")
    num = re.compile(r"(?<![\w.-])(-?\s?\d[\d,]*(?:\.\d+)?)\s*(million|mln|mm|mn|bn|thousand|k|m|b)?(?![\w-]|\.\d)", re.I)
    for sent_txt in re.split(r"(?<=[.?!])\s+|\n", text):
        s = sent_txt
        for pat in _DATE_SCRUB:
            s = re.sub(pat, " ", s, flags=re.I)
        mc = cue.search(s)
        if not mc:
            continue
        m = num.search(s, mc.end()) or num.search(s)
        if not m:
            continue
        try:
            v = float(m.group(1).replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        suf = (m.group(2) or "").lower()
        if suf:
            v *= _SUFFIX[suf]
        return int(round(v))
    return None


# ----------------------------------------------------------------------------------------------
# resolution helpers
# ----------------------------------------------------------------------------------------------
def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).strip(" .,;:")


def resolve_account(text, tools):
    if not text:
        return []
    c = _norm(text)
    hits = tools.search_accounts(c)
    if hits:
        return hits
    c2 = re.sub(r"^(?:the\s+)?(?:fund|account|acct|a/c)\s+", "", c, flags=re.I)
    if c2 != c:
        return tools.search_accounts(c2)
    return []


def resolve_instrument(text, tools):
    if not text:
        return []
    return tools.search_instruments(_norm(text))


# ----------------------------------------------------------------------------------------------
# position
# ----------------------------------------------------------------------------------------------
def settled_position(account_id, instrument_id, as_of, tools):
    """Sum of ledger entries dated on/before as_of over all custody sub-accounts, expressed after any
    split that took effect on/before as_of (entries recorded before the split are multiplied)."""
    ledger = tools.get_ledger(account_id, instrument_id)
    splits = tools.get_corporate_actions(instrument_id)
    total, adjusted = 0, False
    for t in ledger:
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if s["date"] <= as_of and t["date"] < s["date"]:
                q = q * s["ratio"]
                adjusted = True
        total += q
    return total, adjusted


def pending_position(account_id, instrument_id, as_of, tools):
    ins = [x for x in tools.get_instructions(account_id, instrument_id)
           if x["status"] == "matched" and x["settle_date"] > as_of]
    if not ins:
        return None, None
    return sum(x["qty"] for x in ins), max(x["settle_date"] for x in ins)


# ----------------------------------------------------------------------------------------------
# decision
# ----------------------------------------------------------------------------------------------
def _resp(outcome, account_id=None, instrument_id=None, as_of=None, assumed=False,
          settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


def _within(stated, base):
    if base == 0:
        return stated == 0
    return abs(stated - base) / abs(base) <= QTY_TOL


def decide(request, tools):
    sent = request["sent"]
    sent_d = dt.date.fromisoformat(sent)
    body = _clean_body(request.get("body", ""))
    men = request.get("mentions") or {}
    sender = request["from"].strip().lower()
    domain = sender.split("@")[-1]

    # ---- who is asking --------------------------------------------------------------------
    contact = tools.get_contact(sender)
    if contact is None:
        return _resp("REQUEST_AUTHORIZATION"), "unknown_sender"
    ents = tools.get_entitlements(contact["contact_id"])
    registered = set()                      # domains registered on any account the sender is entitled to
    for e in ents:
        p0 = tools.get_client_profile(e["account_id"])
        if p0:
            registered |= {d.lower() for d in p0["domains"]}

    # ---- which account --------------------------------------------------------------------
    acc_hits = resolve_account(men.get("account_text"), tools)
    if len(acc_hits) != 1:
        # account not (uniquely) identified: all we can check is that the sender writes from a domain
        # registered for one of his own accounts
        if domain not in registered:
            return _resp("REQUEST_AUTHORIZATION"), "sender_domain"
        if len(acc_hits) > 1:
            return _resp("REQUEST_INFO"), "ambiguous_account"
        if men.get("account_text"):
            return _resp("REQUEST_INFO"), "account_not_found"
        return _resp("REQUEST_INFO"), "no_account"
    aid = acc_hits[0]["id"]

    # ---- authorization on that account ----------------------------------------------------
    mine = [e for e in ents if e["account_id"] == aid]
    if not mine:
        return _resp("REQUEST_AUTHORIZATION"), "no_entitlement"
    # Oracle Q10 + Q11: the sender's domain must be one of the ASKED account's registered domains
    # (a sender entitled to several accounts is not verified for an account whose client does not list his domain)
    prof0 = tools.get_client_profile(aid) or {"domains": []}
    if domain not in [d.lower() for d in prof0["domains"]]:
        return _resp("REQUEST_AUTHORIZATION"), "sender_domain"
    valid = [e for e in mine if e["expires"] >= sent]
    if not valid:
        return _resp("REQUEST_AUTHORIZATION"), "expired_entitlement"
    if max(e["level"] for e in valid) < MIN_LEVEL:
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"

    prof = tools.get_client_profile(aid) or {"legal_hold": False, "no_email_confirm": False}

    ihits = resolve_instrument(men.get("instrument_text"), tools)

    # ---- account-level handling flags -----------------------------------------------------
    # (no_email_confirm is NOT a gate: oracle Q8 said such an account is "fine to confirm", with pending shown.)
    for flag in ("legal_hold",):
        if prof[flag]:
            iid0 = ihits[0]["id"] if len(ihits) == 1 else None
            return _resp("ESCALATE", aid, iid0), flag

    # ---- which instrument -----------------------------------------------------------------
    if len(ihits) > 1:
        return _resp("REQUEST_INFO", aid), "ambiguous_instrument"
    if not ihits:
        if men.get("instrument_text"):
            return _resp("REQUEST_INFO", aid), "instrument_not_found"
        return _resp("REQUEST_INFO", aid), "no_instrument"
    iid = ihits[0]["id"]

    # ---- which date -----------------------------------------------------------------------
    d, _kind = parse_date(body, sent)
    if d is None:
        return _resp("REQUEST_INFO", aid, iid), "no_date"
    if d > sent_d:
        return _resp("REQUEST_INFO", aid, iid), "future_date"
    cal = tools.get_calendar(d.isoformat())
    as_of = d.isoformat() if cal["business_day"] else cal["previous_business_day"]
    assumed = False

    # ---- figures --------------------------------------------------------------------------
    settled, split_adj = settled_position(aid, iid, as_of, tools)
    pend, pend_date = pending_position(aid, iid, as_of, tools)
    stated = parse_quantity(body)

    if settled == 0 and not pend:
        # Oracle (Q7): "the account doesn't hold that security as of that date" -> NOT_HELD even when the
        # client states a (non-zero) figure.
        return _resp("NOT_HELD", aid, iid, as_of, assumed), "not_held"

    if stated is not None:
        # Oracle Q15: a figure that matches the settled position only (while matched instructions are
        # pending) "doesn't match closely enough" -> compare with settled + pending.
        if not _within(stated, settled + (pend or 0)):
            return _resp("ESCALATE", aid, iid, as_of, assumed, settled), "qty_mismatch"

    branch = "confirm_pending" if pend else ("confirm_split" if split_adj else "confirm")
    return _resp("CONFIRMED", aid, iid, as_of, assumed, settled, pend, pend_date), branch


def respond(request, tools):
    try:
        return decide(request, tools)[0]
    except Exception:
        return _resp("REQUEST_INFO")
