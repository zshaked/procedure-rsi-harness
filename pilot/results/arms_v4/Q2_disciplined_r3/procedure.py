"""Operations-desk procedure: confirm a client's holding of a security.

decide(request, tools) -> (response_dict, branch); respond() returns decide()[0].
Deterministic, standard library + the `tools` argument only.
"""
import re
import datetime as dt

# ----------------------------------------------------------------- conventions
MIN_LEVEL = 2                 # entitlement level needed (level 1 is not enough)
REQUIRE_DOMAIN = True         # sender domain must be one of the account's client domains
FUTURE_DATE_OUTCOME = "REQUEST_INFO"
LEGAL_HOLD_OUTCOME = "ESCALATE"
NO_EMAIL_OUTCOME = "REQUEST_AUTHORIZATION"
FIGURE_TOL = 0                # absolute tolerance when comparing the client's figure to settled
PENDING_AFTER_ASOF = True     # pending = matched instructions settling after as_of
FIGURE_INCLUDES_PENDING = False  # client figure is compared with settled only
PENDING_SIZE_RATIO = 1.0      # matched pending larger than this multiple of settled -> escalate ("positions that size")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"


def _mon(s):
    return _MONTHS[s[:3].lower()]


def _clean_body(body):
    b = body or ""
    b = re.sub(r"(?s)This email and any attachments.*", "", b)
    b = re.sub(r"(?m)^-+\s*Forwarded message\s*-+\s*$", "", b)
    b = re.sub(r"(?m)^(From|Date|To|Subject|Sent):.*$", "", b)
    return b


def _find_dates(text):
    """Return list of (start, end, date) for explicit dates in text."""
    out = []
    pats = [
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: dt.date(int(m[1]), int(m[2]), int(m[3]))),
        (r"\b(\d{1,2})-" + _MON + r"-(\d{4})\b", lambda m: dt.date(int(m[3]), _mon(m[2]), int(m[1]))),
        (r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r",?\s+(\d{4})\b", lambda m: dt.date(int(m[3]), _mon(m[2]), int(m[1]))),
        (r"\b" + _MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", lambda m: dt.date(int(m[3]), _mon(m[1]), int(m[2]))),
    ]
    for p, f in pats:
        for m in re.finditer(p, text, re.I):
            try:
                out.append((m.start(), m.end(), f(m)))
            except Exception:
                pass
    for m in re.finditer(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b", text):
        try:
            out.append((m.start(), m.end(), dt.date(int(m[1]), int(m[2]), int(m[3]))))
        except Exception:
            pass
    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        try:
            out.append((m.start(), m.end(), dt.date(int(m[3]), int(m[2]), int(m[1]))))
        except Exception:
            pass
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        try:
            if a <= 12:
                d = dt.date(y, a, b)
            else:
                d = dt.date(y, b, a)
            out.append((m.start(), m.end(), d))
        except Exception:
            pass
    return out


def _parse_asof(body, sent):
    """Return (date or None, kind). kind in explicit|relative|none."""
    text = _clean_body(body)
    found = _find_dates(text)
    if found:
        found.sort()
        return found[0][2], "explicit", text, found
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"\b(?!\s*,?\s*\d{4})", text)
    if m:
        try:
            d = dt.date(sent.year, _mon(m.group(2)), int(m.group(1)))
            if d > sent:
                d = dt.date(sent.year - 1, d.month, d.day)
            found = found + [(m.start(), m.end(), d)]
            return d, "explicit", text, found
        except Exception:
            pass
    low = re.sub(r"\s+", " ", text.lower())
    if "yesterday" in low:
        return sent - dt.timedelta(days=1), "relative", text, found
    if re.search(r"(last|previous|prior) (business|working) day", low):
        return _PREV_BD(sent), "relative", text, found
    m = re.search(r"\blast (monday|tuesday|wednesday|thursday|friday)\b", low)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday"].index(m.group(1))
        d = sent - dt.timedelta(days=1)
        while d.weekday() != wd:
            d -= dt.timedelta(days=1)
        return d, "relative", text, found
    if re.search(r"(end of (the )?(last|previous) month|last day of (the )?(last|previous) month|month[- ]?end|end of (the )?month)", low):
        return sent.replace(day=1) - dt.timedelta(days=1), "relative", text, found
    if re.search(r"\btoday\b", low):
        return sent, "relative", text, found
    return None, "none", text, found


def _PREV_BD(d):
    d = d - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _figure(text, found_dates):
    t = text
    # remove date spans (from the end so offsets stay valid)
    for s, e, _ in sorted(found_dates, reverse=True):
        t = t[:s] + " " + t[e:]
    t = re.sub(r"\S+@\S+", " ", t)
    t = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ", t)
    t = re.sub(r"\b(?:ACC|SA)-\d+\b", " ", t, flags=re.I)
    t = re.sub(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b", " ", t)
    vals = []
    for m in re.finditer(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(mm|m|k)?(?![\w])", t, re.I):
        raw = m.group(1).rstrip(",")
        suf = (m.group(2) or "").lower()
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        if suf == "k":
            v *= 1e3
        elif suf in ("m", "mm"):
            v *= 1e6
        vals.append(int(round(v)))
    return vals[0] if vals else None


def _norm(s):
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip().strip(".,;:()[]\"'")
    return s or None


def _calendar(tools, d):
    c = tools.get_calendar(d.isoformat())
    return c["business_day"], dt.date.fromisoformat(c["previous_business_day"])


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def decide(request, tools):
    m = request.get("mentions") or {}
    sent = dt.date.fromisoformat(request["sent"][:10])
    _mm = re.search(r"[\w.+'-]+@[\w.-]+", request.get("from") or "")
    sender = (_mm.group(0) if _mm else (request.get("from") or "")).strip().lower()
    at, it = _norm(m.get("account_text")), _norm(m.get("instrument_text"))

    # ---- identify the account (missing / unknown / ambiguous -> ask)
    if not at:
        return _resp("REQUEST_INFO"), "no_account"
    accs = tools.search_accounts(at)
    if not accs:
        return _resp("REQUEST_INFO"), "account_not_found"
    if len(accs) > 1:
        return _resp("REQUEST_INFO"), "account_ambiguous"
    acc_id = accs[0]["id"]

    # ---- authorization comes before anything about the security (oracle Q15)
    contact = tools.get_contact(sender)
    if not contact:
        return _resp("REQUEST_AUTHORIZATION"), "auth_unknown_sender"
    ents = [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == acc_id]
    if not ents:
        return _resp("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    live = [e for e in ents if e["expires"] >= sent.isoformat()]
    if not live:
        return _resp("REQUEST_AUTHORIZATION"), "auth_expired"
    if max(e["level"] for e in live) < MIN_LEVEL:
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"
    prof = tools.get_client_profile(acc_id) or {}
    if REQUIRE_DOMAIN:
        dom = sender.split("@")[-1]
        if dom not in [d.lower() for d in prof.get("domains", [])]:
            return _resp("REQUEST_AUTHORIZATION"), "auth_domain"

    # ---- identify the security
    if not it:
        return _resp("REQUEST_INFO"), "no_instrument"
    inss = tools.search_instruments(it)
    if not inss:
        return _resp("REQUEST_INFO"), "instrument_not_found"
    if len(inss) > 1:
        return _resp("REQUEST_INFO"), "instrument_ambiguous"
    ins_id = inss[0]["id"]

    # ---- account flags
    if prof.get("legal_hold"):
        return _resp(LEGAL_HOLD_OUTCOME, account_id=acc_id, instrument_id=ins_id), "legal_hold"
    if prof.get("no_email_confirm"):
        return _resp(NO_EMAIL_OUTCOME, account_id=acc_id, instrument_id=ins_id), "no_email_confirm"

    # ---- date
    d, kind, text, found = _parse_asof(request.get("body", ""), sent)
    assumed = False
    if d is None:
        d, assumed = sent, True
    if kind != "none" and d > sent:
        return _resp(FUTURE_DATE_OUTCOME), "future_date"
    biz, prev = _calendar(tools, d)
    as_of = d if biz else prev
    as_of_s = as_of.isoformat()

    # ---- settled position at as_of (all sub-accounts, split adjusted)
    ledger = tools.get_ledger(acc_id, ins_id)
    splits = [s for s in tools.get_corporate_actions(ins_id) if s["date"] <= as_of_s]
    settled = 0
    n_rows = 0
    for t in ledger:
        if t["date"] <= as_of_s:
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"]:
                    q *= s["ratio"]
            settled += q
            n_rows += 1

    figure = _figure(text, found)

    if settled == 0:
        # nothing held at as_of: NOT_HELD even when the client quotes a figure (oracle Q6)
        return _resp("NOT_HELD", account_id=acc_id, instrument_id=ins_id, as_of=as_of_s,
                     as_of_assumed=assumed), "not_held"

    # ---- pending (matched instructions not yet settled at as_of)
    pend = [x for x in tools.get_instructions(acc_id, ins_id)
            if x["status"] == "matched" and (x["settle_date"] > as_of_s if PENDING_AFTER_ASOF else True)]
    pending = sum(x["qty"] for x in pend) if pend else None
    pdate = max(x["settle_date"] for x in pend) if pend else None  # latest of several matched (oracle Q13)

    # ---- size rule: a large unsettled leg relative to the holding always goes to escalation
    if pending and pending > settled * PENDING_SIZE_RATIO:
        return _resp("ESCALATE", account_id=acc_id, instrument_id=ins_id, as_of=as_of_s,
                     as_of_assumed=assumed, settled=settled), "pending_size"

    # ---- the client's own figure must agree with the desk's position
    if figure is not None:
        expected = settled + (pending or 0) if FIGURE_INCLUDES_PENDING else settled
        if abs(figure - expected) > FIGURE_TOL:
            return _resp("ESCALATE", account_id=acc_id, instrument_id=ins_id, as_of=as_of_s,
                         as_of_assumed=assumed, settled=settled), "qty_mismatch"

    branch = "confirm_pending" if pend else "confirm_plain"
    return _resp("CONFIRMED", account_id=acc_id, instrument_id=ins_id, as_of=as_of_s,
                 as_of_assumed=assumed, settled=settled, pending=pending, pending_date=pdate), branch


def respond(request, tools):
    return decide(request, tools)[0]
