"""Operations-desk procedure: confirm a client's holding of a security.

decide(request, tools) -> (response_dict, branch); respond() returns decide()[0].
Deterministic, standard library only, state read only via `tools`.

Rule order (first rule that fires decides):
  missing_account / missing_instrument      -> REQUEST_INFO
  account_unresolved / account_ambiguous    -> REQUEST_INFO   (exact match beats prefix match)
  instrument_unresolved / instrument_ambiguous -> REQUEST_INFO
  no_entitlement / entitlement_expired /
  auth_level / domain_mismatch              -> REQUEST_AUTHORIZATION
  legal_hold / no_email_confirm             -> ESCALATE
  future_date                               -> REQUEST_INFO
  not_held                                  -> NOT_HELD       (nothing settled at as_of)
  figure_mismatch                           -> ESCALATE       (client figure != settled + pending)
  confirmed / confirmed_pending             -> CONFIRMED
Figures: settled = ledger rows dated <= as_of over all sub-accounts, rows before a split dated <= as_of
multiplied by its ratio; pending = sum of matched instructions settling after as_of, pending_date = latest.
as_of = stated/relative date (or sent date, as_of_assumed=True), rolled back to a business day.
"""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MN = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
      r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")

# ---- tunable conventions -------------------------------------------------
MIN_LEVEL = 2                  # entitlement level needed to receive a confirmation
FIGURE_TOLERANCE = 0.0         # relative tolerance when comparing the client's figure
COMPARE_INCLUDING_PENDING = True   # client figure is compared with settled + pending
ZERO_BEFORE_MISMATCH = True    # nothing settled -> NOT_HELD even if the client quotes a figure
FLAG_ESCALATES = True          # legal_hold / no_email_confirm -> ESCALATE (after authorization)
EXPIRY_VS = "sent"             # entitlement expiry compared with the email's sent date
# ---------------------------------------------------------------------------


def _mon(s):
    return MONTHS[s[:3].lower()]


def _clean_body(body):
    b = re.sub(r"-+\s*Forwarded message\s*-+\s*\n(?:From:[^\n]*\n)?(?:Date:[^\n]*\n)?", "", body or "")
    b = re.split(r"\n\s*This email and any attachments", b)[0]
    return b


def _parse_date(body, sent):
    """-> (kind, date|None) with kind in explicit | relative | none.
    The explicit date written first in the body wins."""
    b = _clean_body(body)
    s = dt.date.fromisoformat(sent)
    found = []

    def add(m, y, mo, d):
        try:
            found.append((m.start(), dt.date(int(y), mo, int(d))))
        except ValueError:
            found.append((m.start(), None))

    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", b):
        add(m, m[1], int(m[2]), m[3])
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b):
        add(m, m[3], int(m[1]), m[2])
    for m in re.finditer(r"\b(\d{1,2})-" + MN + r"-(\d{4})\b", b, re.I):
        add(m, m[3], _mon(m[2]), m[1])
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MN + r",?\s+(\d{4})\b", b, re.I):
        add(m, m[3], _mon(m[2]), m[1])
    for m in re.finditer(MN + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b, re.I):
        add(m, m[3], _mon(m[1]), m[2])
    if found:
        found.sort(key=lambda x: x[0])
        return "explicit", found[0][1]
    if re.search(r"\byesterday\b", b, re.I):
        return "relative", s - dt.timedelta(days=1)
    if re.search(r"(end of (?:the )?last month|last day of (?:the )?last month|"
                 r"end of (?:the )?previous month|month[- ]end)", b, re.I):
        return "relative", s.replace(day=1) - dt.timedelta(days=1)
    return "none", None


def _parse_qty(tok):
    """-> (value, tolerance) ; tolerance is half a unit of the last written digit for k / mm forms."""
    t = tok.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    if t.endswith("mm"):
        mult, t = 1_000_000, t[:-2]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    elif t.endswith("k"):
        mult, t = 1_000, t[:-1]
    try:
        val = float(t)
    except ValueError:
        return None, 0
    tol = 0.0
    if mult > 1:
        dec = len(t.split(".")[1]) if "." in t else 0
        tol = 0.5 * mult / (10 ** dec)
    return int(round(val * mult)), tol


def _stated_figure(body):
    b = _clean_body(body)
    m = re.search(r"(?:figure is|we show|records show|we have|we hold|shows?)\s+"
                  r"(\d[\d,]*(?:\.\d+)?\s*(?:mm|k|m)?)(?![\w])", b, re.I)
    if not m:
        return None, 0
    return _parse_qty(m[1])


def _norm(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s.strip(" .,;:")


_PREFIX_WORDS = re.compile(r"^(?:the\s+)?(?:a/c|acct|account|fund)\s+", re.I)


def _lookup(fn, text):
    t = _norm(text)
    hits = fn(t)
    if not hits:
        t2 = _PREFIX_WORDS.sub("", t)
        if t2 != t:
            hits = fn(t2)
    return hits


def _business_on_or_before(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def _figures(account_id, instrument_id, as_of, tools):
    """settled (split-adjusted, all sub-accounts) and pending (matched instructions settling after as_of)."""
    iso = as_of.isoformat()
    splits = [(a["date"], a["ratio"]) for a in tools.get_corporate_actions(instrument_id)
              if a.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > iso:
            continue
        q = t["qty"]
        for sd, ratio in splits:
            if sd <= iso and t["date"] < sd:
                q = q * ratio
        total += q
    pend = [x for x in tools.get_instructions(account_id, instrument_id)
            if x["status"] == "matched" and x["settle_date"] > iso]
    pend.sort(key=lambda x: x["settle_date"])
    pending = sum(x["qty"] for x in pend) if pend else None
    pending_date = pend[-1]["settle_date"] if pend else None   # oracle: with several, the last date
    return total, pending, pending_date


def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def decide(request, tools):
    men = request.get("mentions") or {}
    at, it = men.get("account_text"), men.get("instrument_text")
    sent = request["sent"]

    # 1. identification --------------------------------------------------
    if not _norm(at):
        return _blank("REQUEST_INFO"), "missing_account"
    if not _norm(it):
        return _blank("REQUEST_INFO"), "missing_instrument"
    accs = [a["id"] for a in _lookup(tools.search_accounts, at)]
    if len(accs) != 1:
        return _blank("REQUEST_INFO"), ("account_ambiguous" if accs else "account_unresolved")
    insts = [i["id"] for i in _lookup(tools.search_instruments, it)]
    if len(insts) != 1:
        return _blank("REQUEST_INFO"), ("instrument_ambiguous" if insts else "instrument_unresolved")
    acc, ins = accs[0], insts[0]

    # 2. authorization ---------------------------------------------------
    sender = (request.get("from") or "").strip().lower()
    domain = sender.split("@")[-1]
    contact = tools.get_contact(sender)
    prof = tools.get_client_profile(acc) or {}
    if not contact:
        return _blank("REQUEST_AUTHORIZATION"), "no_entitlement"
    mine = [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == acc]
    if not mine:
        return _blank("REQUEST_AUTHORIZATION"), "no_entitlement"
    kind, d = _parse_date(request.get("body"), sent)
    ref = sent if EXPIRY_VS == "sent" else (d.isoformat() if d else sent)
    live = [e for e in mine if e["expires"] >= ref]
    if not live:
        return _blank("REQUEST_AUTHORIZATION"), "entitlement_expired"
    if max(e["level"] for e in live) < MIN_LEVEL:
        return _blank("REQUEST_AUTHORIZATION"), "auth_level"
    if domain not in [x.lower() for x in prof.get("domains", [])]:
        return _blank("REQUEST_AUTHORIZATION"), "domain_mismatch"

    resp = _blank("ESCALATE")
    resp["account_id"], resp["instrument_id"] = acc, ins

    # 3. as-of date -------------------------------------------------------
    assumed = False
    if kind == "none":
        d = dt.date.fromisoformat(sent)
        assumed = True
    flagged = FLAG_ESCALATES and (prof.get("legal_hold") or prof.get("no_email_confirm"))
    if d is None:
        if flagged:
            return resp, ("legal_hold" if prof.get("legal_hold") else "no_email_confirm")
        return _blank("REQUEST_INFO"), "bad_date"
    as_of = _business_on_or_before(d, tools)
    settled, pending, pending_date = _figures(acc, ins, as_of, tools)
    resp.update(as_of=as_of.isoformat(), as_of_assumed=assumed, settled=settled)

    # 4. account restrictions -------------------------------------------
    if flagged:
        return resp, ("legal_hold" if prof.get("legal_hold") else "no_email_confirm")
    if d > dt.date.fromisoformat(sent):
        return _blank("REQUEST_INFO"), "future_date"

    stated, tol = _stated_figure(request.get("body"))

    # 5. outcome -----------------------------------------------------------
    if settled == 0 and ZERO_BEFORE_MISMATCH:
        resp.update(outcome="NOT_HELD", settled=None)
        return resp, "not_held"
    if stated is not None:
        ref_fig = settled + (pending or 0) if COMPARE_INCLUDING_PENDING else settled
        allow = max(FIGURE_TOLERANCE * max(abs(ref_fig), 1), tol)
        if abs(stated - ref_fig) > allow:
            return resp, "figure_mismatch"
    if settled == 0:
        resp.update(outcome="NOT_HELD", settled=None)
        return resp, "not_held"

    resp.update(outcome="CONFIRMED", pending=pending, pending_date=pending_date)
    return resp, "confirmed_pending" if pending else "confirmed"


def respond(request, tools):
    return decide(request, tools)[0]
