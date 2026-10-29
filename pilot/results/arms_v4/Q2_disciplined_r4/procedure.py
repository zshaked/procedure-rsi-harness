"""Operations-desk procedure: confirm a client's holding of a security.

decide(request, tools) -> (response_dict, branch); respond() returns decide()[0].
Standard library + `tools` only. Deterministic.
"""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MIN_LEVEL = 2            # entitlement level needed to receive a confirmation (level 1 is not enough)
QTY_REL_TOL = 0.0        # exact match required for plain numbers


# ----------------------------------------------------------------------------- parsing
def _strip_fwd_header(body):
    return re.sub(r"-+\s*Forwarded message\s*-+\s*\nFrom:[^\n]*\nDate:[^\n]*\n", "", body)


def _mon(s):
    return MONTHS.get(s[:3].lower())


def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Returns (date|None, kind) kind in explicit | relative | none."""
    s = dt.date.fromisoformat(sent)
    b = _strip_fwd_header(body)
    mon = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[-\s]" + mon + r"[-,\s]+(\d{4})\b", b)
    if m:
        return dt.date(int(m[3]), _mon(m[2]), int(m[1])), "explicit"
    m = re.search(r"\b" + mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b)
    if m:
        return dt.date(int(m[3]), _mon(m[1]), int(m[2])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", b)
    if m:  # US month/day/year (evidence: 12/17/2025, 1/31/2026)
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return dt.date(y, int(m[1]), int(m[2])), "explicit"
    low = b.lower()
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"(end of last month|last day of last month|last day of the previous month|"
                 r"end of the previous month|end of previous month|month[- ]end|end of month)", low):
        return _last_day_prev_month(s), "relative"
    return None, "none"


def _num(tok):
    tok = tok.strip().lower().replace(",", "")
    mult, unit = 1, None
    for suf, mu in (("million", 1_000_000), ("mm", 1_000_000), ("m", 1_000_000),
                    ("thousand", 1_000), ("k", 1_000)):
        if tok.endswith(suf):
            mult, unit, tok = mu, suf, tok[: -len(suf)].strip()
            break
    if not re.fullmatch(r"\d+(\.\d+)?", tok):
        return None
    val = float(tok) * mult
    if unit is None:
        return int(round(val)), 0
    dec = len(tok.split(".")[1]) if "." in tok else 0
    half = 0.5 * mult / (10 ** dec)          # rounding half-width of an abbreviated figure
    return int(round(val)), half


def parse_stated_qty(body):
    """Return (qty, half_width) of the figure the client states, or None."""
    b = _strip_fwd_header(body)
    cues = r"(?:we show|our records show|records show|we have|our figure is|our figure|we hold|our books show|" \
           r"we are showing|showing|our records indicate)"
    tok = r"(\d[\d,]*(?:\.\d+)?\s?(?:million|thousand|mm|m|k)?)(?![\w])"
    m = re.search(cues + r"\s*(?:is|of|:)?\s*" + tok, b, re.I)
    if m:
        return _num(m.group(1).replace(" ", ""))
    return None


# ----------------------------------------------------------------------------- helpers
def _resolve_account(text, tools):
    if not text:
        return "missing", None
    hits = tools.search_accounts(text)
    if not hits:
        return "notfound", None
    if len(hits) > 1:
        return "ambiguous", None
    return "ok", hits[0]["id"]


def _resolve_instrument(text, tools):
    if not text:
        return "missing", None
    hits = tools.search_instruments(text)
    if not hits:
        return "notfound", None
    if len(hits) > 1:
        return "ambiguous", None
    return "ok", hits[0]["id"]


def _position(tools, acct, inst, as_of):
    """Settled quantity across all custody sub-accounts at close of as_of, split-adjusted."""
    splits = tools.get_corporate_actions(inst)
    total = 0
    for t in tools.get_ledger(acct, inst):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for sp in splits:
            if t["date"] < sp["date"] <= as_of:
                q *= sp["ratio"]
        total += q
    return total


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


# ----------------------------------------------------------------------------- decision
def decide(request, tools):
    men = request.get("mentions") or {}
    sent = request["sent"]
    body = request.get("body", "")

    a_stat, acct = _resolve_account(men.get("account_text"), tools)
    if a_stat == "missing":
        return _resp("REQUEST_INFO"), "info_no_account"
    if a_stat == "notfound":
        return _resp("REQUEST_INFO"), "info_account_not_found"
    if a_stat == "ambiguous":
        return _resp("REQUEST_INFO"), "info_ambiguous_account"
    # --- authorization of the sender for this account
    contact = tools.get_contact(request["from"])
    if not contact:
        return _resp("REQUEST_AUTHORIZATION"), "auth_unknown_sender"
    ents = [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == acct]
    if not ents:
        return _resp("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    live = [e for e in ents if e["expires"] is None or e["expires"] >= sent]
    if not live:
        return _resp("REQUEST_AUTHORIZATION"), "auth_expired"
    if max(e["level"] for e in live) < MIN_LEVEL:
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"
    prof = tools.get_client_profile(acct) or {}
    dom = request["from"].lower().rsplit("@", 1)[-1]
    if dom not in [d.lower() for d in prof.get("domains", [])]:
        return _resp("REQUEST_AUTHORIZATION"), "auth_domain"

    # --- instrument is resolved only after the sender is authorized (oracle Q3: auth precedes missing-instrument info)
    i_stat, inst = _resolve_instrument(men.get("instrument_text"), tools)
    if i_stat == "missing":
        return _resp("REQUEST_INFO"), "info_no_instrument"
    if i_stat == "notfound":
        return _resp("REQUEST_INFO"), "info_instrument_not_found"
    if i_stat == "ambiguous":
        return _resp("REQUEST_INFO"), "info_ambiguous_instrument"

    base = dict(account_id=acct, instrument_id=inst)
    if prof.get("legal_hold"):
        return _resp("ESCALATE", **base), "legal_hold"
    if prof.get("no_email_confirm"):
        return _resp("ESCALATE", **base), "no_email_confirm"

    # --- as-of date
    try:
        d, kind = parse_date(body, sent)
    except ValueError:         # e.g. 31-Feb-2026: unusable date, ask which date they want
        return _resp("REQUEST_INFO"), "info_bad_date"
    assumed = False
    if d is None:
        d, assumed = dt.date.fromisoformat(sent), True
    iso = d.isoformat()
    cal = tools.get_calendar(iso)
    if not cal["business_day"]:
        iso = cal["previous_business_day"]

    settled = _position(tools, acct, inst, iso)
    stated = parse_stated_qty(body)

    if settled == 0:
        return _resp("NOT_HELD", as_of=iso, as_of_assumed=assumed, **base), "not_held"

    # pending = matched instructions settling after as_of (a split between as_of and settlement multiplies the
    # recorded quantity: oracle Q8); unmatched / cancelled are not pending (oracle Q9)
    pend, pdate = None, None
    ins = [x for x in tools.get_instructions(acct, inst)
           if x["status"] == "matched" and x["settle_date"] > iso]
    if ins:
        splits = tools.get_corporate_actions(inst)

        def _adj(x):
            q = x["qty"]
            for sp in splits:
                if iso < sp["date"] <= x["settle_date"]:
                    q *= sp["ratio"]
            return q
        pend = sum(_adj(x) for x in ins)
        pdate = min(x["settle_date"] for x in ins)

    # the client's figure is compared with OUR figure = settled + pending (oracle Q10, Q51; history Q2-0006)
    if stated is not None:
        q, half = stated
        ours = settled + (pend or 0)
        if abs(q - ours) > max(half, QTY_REL_TOL * ours):
            return _resp("ESCALATE", **base), "qty_mismatch"

    return _resp("CONFIRMED", as_of=iso, as_of_assumed=assumed, settled=settled,
                 pending=pend, pending_date=pdate, **base), ("confirm_pending" if ins else "confirm")


def respond(request, tools):
    try:
        return decide(request, tools)[0]
    except Exception:          # malformed input: ask the client rather than guess
        return _resp("REQUEST_INFO")
