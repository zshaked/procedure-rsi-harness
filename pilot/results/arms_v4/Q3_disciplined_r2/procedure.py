"""Desk procedure induced from the 25 histories (v3).  respond() returns decide()[0].

Decision order (first rule that fires decides):
  1. account named but not uniquely resolvable            -> REQUEST_INFO      (account_ambiguous / account_unresolved)
  2. no account named: use the sender's sole entitlement   -> else REQUEST_INFO (account_missing)
  3. sender has no entitlement for the account             -> REQUEST_AUTHORIZATION (auth_no_entitlement)
     entitlement expired on the email date                 -> REQUEST_AUTHORIZATION (auth_expired)
     entitlement level < 3                                 -> REQUEST_AUTHORIZATION (auth_level)
  4. no instrument named / unresolved, as-of a non-business
     day, or as-of in the future                           -> REQUEST_INFO      (instrument_missing / date_nonbusiness / future_date)
  5. account profile no_email_confirm                      -> REQUEST_AUTHORIZATION (no_email_confirm)
  6. account profile legal_hold                            -> ESCALATE          (legal_hold)
  7. client-stated quantity does not tie out               -> ESCALATE          (figure_mismatch / figure_vs_nothing)
  8. nothing held at as-of                                 -> NOT_HELD          (not_held)
  9. otherwise                                             -> CONFIRMED         (confirmed / confirmed_pending / ...)
Figures: settled = sum of ledger over ALL sub-accounts dated <= as_of, entries recorded before a split
dated <= as_of multiplied by its ratio.  No date -> email date (as_of_assumed).  Non-business-day position date ->
REQUEST_INFO (asked which date they want).  Pending = matched instructions settling after as_of, on/after the email date, within
PENDING_HORIZON_DAYS of the email date (summed; earliest date).
"""
import re
import datetime as dt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

# ---- parameters / conventions (see NOTES.md) --------------------------------
CFG = {
    "level_min": 3,
    "pending_horizon_days": 30,      # threshold: matched instruction must settle within this many days of the email date
    "pending_lower": "sent",         # lower bound of the pending window: 'sent' = settle on/after the email date; 'asof' = any settle after as_of
    "pending_statuses": ("matched",),
    "fig_tolerance": 0.05,           # relative tolerance on stated figure: oracle Q3-0132 (+2%) is "fine to confirm"; 0012 (-7%) and Q3-0102 (+8%) escalate
    "fig_basis": "settled_or_pending",  # stated figure ties out if == settled, or == settled + all matched pending after as-of
    "nonbusiness_date": "info",      # position date (given or assumed) not a business day: 'info' (oracle Q3-0085) | 'roll' (previous business day)
    "inclusive": True,               # ledger rows dated on the as-of date count
    "split_rule": "asof",            # 'asof': apply splits dated <= as_of ; 'sent': apply splits dated <= email date ; 'none'
    "infer_account": True,           # no account named -> sender's sole entitlement
    "future_asof": "info",           # as-of after the email date: 'normal' | 'info' | 'cap'
    "zero_with_figure": "escalate",  # stated figure but nothing held: 'escalate' | 'not_held'
    "expiry_anchor": "sent",         # 'sent' | 'asof'
    "monthend_phrases": True,
}


def _d(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_date(body, sent):
    t = re.sub(r"(?m)^\s*Date:.*$", "", body)          # forwarded-message header carries the email date, not the position date
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _d(*m.groups())
    m = re.search(r"\b(\d{1,2})-" + MON_RE + r"-(\d{4})\b", t, re.I)
    if m:
        return _d(m.group(3), MONTHS[m.group(2).lower()[:3]], m.group(1))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON_RE + r",?\s+(\d{4})\b", t, re.I)
    if m:
        return _d(m.group(3), MONTHS[m.group(2).lower()[:3]], m.group(1))
    m = re.search(r"\b" + MON_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t, re.I)
    if m:
        return _d(m.group(3), MONTHS[m.group(1).lower()[:3]], m.group(2))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if m:
        return _d(m.group(3), m.group(1), m.group(2))      # US month/day/year
    if re.search(r"\bday before yesterday\b", t, re.I):
        return sent - dt.timedelta(days=2)
    if re.search(r"\byesterday\b", t, re.I):
        return sent - dt.timedelta(days=1)
    if re.search(r"(end of last month|last day of last month|last day of the previous month|end of the previous month)", t, re.I):
        return sent.replace(day=1) - dt.timedelta(days=1)
    if CFG["monthend_phrases"] and re.search(r"\bmonth[- ]end\b", t, re.I):
        return sent.replace(day=1) - dt.timedelta(days=1)
    if re.search(r"\btoday\b", t, re.I):
        return sent
    return None


def parse_qty(s):
    s = s.strip().replace(",", "").rstrip(".")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(k|mm|m)?", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    u = (m.group(2) or "").lower()
    if u == "k":
        v *= 1e3
    elif u in ("mm", "m"):
        v *= 1e6
    return int(round(v))


_NUM = r"(-?\d[\d,]*(?:\.\d+)?\s*(?:mm|k|m)?)"


def stated_qty(body):
    pats = [r"We have\s+" + _NUM + r"\s+(?:shares|units)",
            r"records show\s+" + _NUM,
            r"our figure is\s+" + _NUM,
            r"We show\s+" + _NUM]
    for p in pats:
        m = re.search(p, body, re.I)
        if m:
            return parse_qty(m.group(1))
    return None


def _cal(tools, d):
    return tools.get_calendar(d.isoformat())


def _roll(tools, d):
    c = _cal(tools, d)
    return d if c["business_day"] else dt.date.fromisoformat(c["previous_business_day"])


def position(tools, acct, ins, as_of, sent):
    """Returns (settled, n_rows)."""
    ledger = tools.get_ledger(acct, ins)
    acts = [a for a in tools.get_corporate_actions(ins) if a["type"] == "split"]
    lim = {"asof": as_of, "sent": sent}.get(CFG["split_rule"])
    total, n = 0, 0
    for t in ledger:
        ok = (t["date"] <= as_of.isoformat()) if CFG["inclusive"] else (t["date"] < as_of.isoformat())
        if not ok:
            continue
        q = t["qty"]
        if lim is not None:
            for a in acts:
                if t["date"] < a["date"] <= lim.isoformat():
                    q *= a["ratio"]
        total += q
        n += 1
    return total, n


def _matched_after(tools, acct, ins, as_of):
    return [x for x in tools.get_instructions(acct, ins)
            if x["status"] in CFG["pending_statuses"] and dt.date.fromisoformat(x["settle_date"]) > as_of]


def pending_info(tools, acct, ins, as_of, sent):
    sel = []
    for x in _matched_after(tools, acct, ins, as_of):
        sd = dt.date.fromisoformat(x["settle_date"])
        if CFG["pending_lower"] == "sent" and sd < sent:
            continue
        if (sd - sent).days > CFG["pending_horizon_days"]:
            continue
        sel.append(x)
    if not sel:
        return None, None
    sel.sort(key=lambda x: x["settle_date"])
    return sum(x["qty"] for x in sel), sel[0]["settle_date"]


def _resp(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def _email(addr):
    m = re.search(r"[\w.+-]+@[\w.-]+", addr or "")
    return m.group(0) if m else (addr or "")


def _resolve_account(tools, text, body):
    hits = tools.search_accounts(text) if text else []
    if not hits and text:
        t = re.sub(r"^(?:our\s+)?(?:a/c|acct|account|fund)\s+", "", text.strip(), flags=re.I)
        hits = tools.search_accounts(t)
    if not hits:
        ids = re.findall(r"\b(?:ACC-\d{5}|SA-\d{6})\b", (text or "") + " " + body)
        for i in ids:
            hits = tools.search_accounts(i)
            if hits:
                break
    return hits


def _ties_out(sq, settled, pend_all):
    """Does the client-stated figure agree with ours?"""
    bases = [settled]
    if CFG["fig_basis"] == "settled_or_pending" and pend_all:
        bases.append(settled + pend_all)
    for b in bases:
        if abs(sq - b) <= CFG["fig_tolerance"] * (abs(b) if b else 1):
            return True, b is not settled
    return False, False


def decide(request, tools):
    sent = dt.date.fromisoformat(request["sent"])
    body = request.get("body", "")
    men = request.get("mentions") or {}
    contact = tools.get_contact(_email(request.get("from")))
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []

    # ---- 1/2 account
    at = men.get("account_text")
    if at:
        hits = _resolve_account(tools, at, body)
        if len(hits) == 0:
            return _resp("REQUEST_INFO"), "account_unresolved"
        if len(hits) > 1:
            return _resp("REQUEST_INFO"), "account_ambiguous"
        acct = hits[0]["id"]
    else:
        accts = sorted({e["account_id"] for e in ents})
        if CFG["infer_account"] and len(accts) == 1:
            acct = accts[0]
        else:
            return _resp("REQUEST_INFO"), "account_missing"

    # ---- date (no rolling: a non-business-day position date is sent back to the client, see below)
    d = parse_date(body, sent)
    assumed = False
    if d is None:
        d, assumed = sent, True

    # ---- 3 authorization
    if not contact:
        return _resp("REQUEST_AUTHORIZATION"), "auth_unknown_contact"
    mine = [e for e in ents if e["account_id"] == acct]
    if not mine:
        return _resp("REQUEST_AUTHORIZATION"), "auth_no_entitlement"
    ref = (sent if CFG["expiry_anchor"] == "sent" else d).isoformat()
    live = [e for e in mine if e["expires"] >= ref]
    if not live:
        return _resp("REQUEST_AUTHORIZATION"), "auth_expired"
    if not any(e["level"] >= CFG["level_min"] for e in live):
        return _resp("REQUEST_AUTHORIZATION"), "auth_level"

    # ---- 4 instrument / date sanity
    it = men.get("instrument_text")
    if not it:
        return _resp("REQUEST_INFO"), "instrument_missing"
    ihits = tools.search_instruments(it)
    if len(ihits) != 1:
        return _resp("REQUEST_INFO"), "instrument_unresolved"
    ins = ihits[0]["id"]
    if CFG["nonbusiness_date"] == "info" and not _cal(tools, d)["business_day"]:
        return _resp("REQUEST_INFO"), "date_nonbusiness"      # oracle (Q3-0085): "that date isn't a business day; we ask them which date they want"
    if CFG["nonbusiness_date"] == "roll" and not _cal(tools, d)["business_day"]:
        d = _roll(tools, d)
    if d > sent:
        if CFG["future_asof"] == "info":
            return _resp("REQUEST_INFO"), "future_date"
        if CFG["future_asof"] == "cap":
            d = _roll(tools, sent)

    # ---- 5/6 account flags
    prof = tools.get_client_profile(acct) or {}
    if prof.get("no_email_confirm"):
        return _resp("REQUEST_AUTHORIZATION"), "no_email_confirm"

    as_of = d.isoformat()
    settled, n = position(tools, acct, ins, d, sent)
    pend, pdate = pending_info(tools, acct, ins, d, sent)
    pend_all = sum(x["qty"] for x in _matched_after(tools, acct, ins, d))

    if prof.get("legal_hold"):
        return _resp("ESCALATE", account_id=acct, instrument_id=ins, as_of=as_of,
                     as_of_assumed=assumed, settled=settled), "legal_hold"

    held = n > 0 and settled != 0
    via_pending = False
    sq = stated_qty(body)
    if sq is not None:
        if held:
            ok, via_pending = _ties_out(sq, settled, pend_all)
            if not ok:
                return _resp("ESCALATE", account_id=acct, instrument_id=ins, as_of=as_of,
                             as_of_assumed=assumed, settled=settled), "figure_mismatch"
        elif CFG["zero_with_figure"] == "escalate" and sq != 0:
            return _resp("ESCALATE", account_id=acct, instrument_id=ins, as_of=as_of,
                         as_of_assumed=assumed, settled=settled), "figure_vs_nothing"

    if not held:
        return _resp("NOT_HELD", account_id=acct, instrument_id=ins, as_of=as_of,
                     as_of_assumed=assumed), "not_held"
    br = "confirmed_pending" if pend else "confirmed"
    if via_pending:
        br = "confirmed_figure_incl_pending"
    return _resp("CONFIRMED", account_id=acct, instrument_id=ins, as_of=as_of,
                 as_of_assumed=assumed, settled=settled, pending=pend,
                 pending_date=pdate), br


def respond(request, tools):
    return decide(request, tools)[0]
