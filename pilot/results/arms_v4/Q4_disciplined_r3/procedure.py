"""Desk procedure induced from histories (v1, before any oracle question).

decide(request, tools) -> (response_dict, branch)
respond(request, tools) -> response_dict
"""
import datetime as dt
import re

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
FULL = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
        "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}

# ---- tunable conventions ------------------------------------------------------------
MIN_LEVEL = 2            # entitlement level needed to receive a confirmation
TOLERANCE = 0.10         # relative tolerance between client's figure and the desk's figure


def _mnum(tok):
    t = tok.lower()
    if t in FULL:
        return FULL[t]
    return MONTHS.get(t[:3])


# ---- text parsing -------------------------------------------------------------------
def _clean_body(body):
    lines = []
    for ln in body.split("\n"):
        s = ln.strip()
        if re.match(r"^(from|date|sent|to|subject):", s, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _last_day_of_prev_month(sent):
    first = sent.replace(day=1)
    return first - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date|None, kind). kind in explicit|relative|none."""
    b = _clean_body(body)
    low = b.lower()
    # ISO
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", b)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "explicit"
        except ValueError:
            pass
    # 27-Jan-2026
    m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", b)
    if m and _mnum(m.group(2)):
        return dt.date(int(m.group(3)), _mnum(m.group(2)), int(m.group(1))), "explicit"
    # 3 Jan 2026 / 22 December 2025
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", b)
    if m and _mnum(m.group(2)):
        return dt.date(int(m.group(3)), _mnum(m.group(2)), int(m.group(1))), "explicit"
    # January 27, 2026
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", b)
    if m and _mnum(m.group(1)):
        return dt.date(int(m.group(3)), _mnum(m.group(1)), int(m.group(2))), "explicit"
    # 1/23/2026  (US month first)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", b)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))), "explicit"
        except ValueError:
            pass
    # 2026/01/23
    m = re.search(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b", b)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "explicit"
        except ValueError:
            pass
    # 23.01.2026 (day first)
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", b)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))), "explicit"
        except ValueError:
            pass
    # day + month without a year: latest such date not after the sent date
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
                  b, re.I)
    mo = None
    if m:
        mo, dy = _mnum(m.group(2)), int(m.group(1))
    else:
        m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
                      b, re.I)
        if m:
            mo, dy = _mnum(m.group(1)), int(m.group(2))
    if mo:
        for yr in (sent.year, sent.year - 1):
            try:
                cand = dt.date(yr, mo, dy)
            except ValueError:
                continue
            if cand <= sent:
                return cand, "explicit"
    # relative
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), "relative"
    if re.search(r"\b(today|close of business today|as of now)\b", low):
        return sent, "relative"
    if re.search(r"(last|previous|prior) (business|working) day", low):
        return sent - dt.timedelta(days=1), "relative"   # rolled back to a business day by the caller
    if re.search(r"(year[- ]end|end of (the )?(last|previous) year)", low):
        return dt.date(sent.year - 1, 12, 31), "relative"
    if re.search(r"(quarter[- ]end|end of (the )?(last|previous) quarter)", low):
        q_start = dt.date(sent.year, 3 * ((sent.month - 1) // 3) + 1, 1)
        return q_start - dt.timedelta(days=1), "relative"
    if re.search(r"(last day of (the )?(last|previous) month|end of (the )?(last|previous) month|"
                 r"last month[- ]end|month[- ]?end|end of (the )?month)", low):
        return _last_day_of_prev_month(sent), "relative"
    return None, "none"


_NUM = r"(-?\d[\d,]*(?:\.\d+)?)\s*(k|mm|m)?\b"


def _to_qty(num, suf):
    v = float(num.replace(",", ""))
    s = (suf or "").lower()
    if s == "k":
        v *= 1_000
    elif s in ("mm", "m"):
        v *= 1_000_000
    return int(round(v))


def parse_figure(body):
    b = _clean_body(body)
    m = re.search(r"(?:records show|figure is|we show|we have|our books show|shows?)\s+" + _NUM, b, re.I)
    if m:
        return _to_qty(m.group(1), m.group(2))
    return None


# ---- system lookups -----------------------------------------------------------------
def _resolve_account(text, tools):
    if not text:
        return []
    return tools.search_accounts(text)


def _resolve_instrument(text, tools):
    if not text:
        return []
    return tools.search_instruments(text)


def _business_roll(d, tools):
    cal = tools.get_calendar(d.isoformat())
    if cal["business_day"]:
        return d
    return dt.date.fromisoformat(cal["previous_business_day"])


def _position(account_id, instrument_id, as_of, tools):
    """Settled quantity across all sub-accounts up to as_of (inclusive), split adjusted."""
    acts = tools.get_corporate_actions(instrument_id)
    total = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for a in acts:
            if a["type"] == "split" and t["date"] < a["date"] and a["date"] <= as_of:
                q *= a["ratio"]
        total += q
    return total


def _pending(account_id, instrument_id, as_of, tools):
    """Matched instructions still to settle after as_of. Returns (qty, latest date, stale_flag);
    stale_flag marks a matched instruction whose settle date is on/before as_of (ignored)."""
    ins = [x for x in tools.get_instructions(account_id, instrument_id) if x["status"] == "matched"]
    live = [x for x in ins if x["settle_date"] > as_of]
    stale = any(x["settle_date"] <= as_of for x in ins)
    if not live:
        return None, None, stale
    return sum(x["qty"] for x in live), max(x["settle_date"] for x in live), stale


def _blank(outcome):
    return {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _auth_status(contact, account_id, profile, sender_domain, sent, tools):
    """Return None if authorised, else the name of the first failing authorisation rule."""
    ents = [e for e in tools.get_entitlements(contact["contact_id"]) if e["account_id"] == account_id]
    if not ents:
        return "auth_no_entitlement"
    live = [e for e in ents if e["expires"] >= sent.isoformat()]
    if not live:
        return "auth_expired"
    if max(e["level"] for e in live) < MIN_LEVEL:
        return "auth_level"
    if profile is None or sender_domain not in profile["domains"]:
        return "auth_domain"
    return None


def decide(request, tools):
    sender = request["from"].lower()
    domain = sender.split("@")[-1]
    sent = dt.date.fromisoformat(request["sent"])
    men = request.get("mentions") or {}
    acct_text, inst_text = men.get("account_text"), men.get("instrument_text")

    contact = tools.get_contact(sender)
    if contact is None:
        return _blank("REQUEST_AUTHORIZATION"), "auth_no_contact"
    # ---- account resolution
    if acct_text:
        accts = _resolve_account(acct_text, tools)
        if not accts:
            return _blank("REQUEST_INFO"), "account_unresolved"
        if len(accts) > 1:
            # oracle Q4-0043: a sender whose domain is registered for none of the candidates is refused
            cand_domains = set()
            for a in accts:
                p = tools.get_client_profile(a["id"])
                if p:
                    cand_domains.update(p["domains"])
            if domain not in cand_domains:
                return _blank("REQUEST_AUTHORIZATION"), "auth_domain"
            if contact is not None:
                for a in accts:
                    p = tools.get_client_profile(a["id"])
                    if _auth_status(contact, a["id"], p, domain, sent, tools) is None:
                        return _blank("REQUEST_INFO"), "account_ambiguous"
            return _blank("REQUEST_INFO"), "account_ambiguous_unauth"
        acct_id = accts[0]["id"]
    else:
        # no account named: ask (oracle Q4-0055) unless the sender is not recognised for any account
        cands = []
        if contact:
            for e in tools.get_entitlements(contact["contact_id"]):
                p = tools.get_client_profile(e["account_id"])
                if p and domain in p["domains"]:
                    cands.append(e["account_id"])
        if not cands:
            return _blank("REQUEST_AUTHORIZATION"), "auth_no_account"
        return _blank("REQUEST_INFO"), "account_missing"
    if contact is None:
        return _blank("REQUEST_AUTHORIZATION"), "auth_no_contact"

    profile = tools.get_client_profile(acct_id)
    bad = _auth_status(contact, acct_id, profile, domain, sent, tools)
    if bad:
        return _blank("REQUEST_AUTHORIZATION"), bad

    # ---- instrument resolution
    insts = _resolve_instrument(inst_text, tools)
    if not inst_text:
        # the system exposes no way to list an account's positions, so a security that is not
        # named cannot be recovered from the figure (oracle Q4-0093 disagreed; see NOTES)
        r = _blank("REQUEST_INFO"); r["account_id"] = acct_id
        return r, "instrument_missing"
    if len(insts) != 1:
        r = _blank("REQUEST_INFO"); r["account_id"] = acct_id
        return r, "instrument_unresolved" if not insts else "instrument_ambiguous"
    inst_id = insts[0]["id"]

    # ---- date
    d, kind = parse_date(request["body"], sent)
    if d is None:
        r = _blank("REQUEST_INFO"); r["account_id"] = acct_id; r["instrument_id"] = inst_id
        return r, "date_missing"
    if d > sent:
        r = _blank("REQUEST_INFO"); r["account_id"] = acct_id; r["instrument_id"] = inst_id
        return r, "date_future"
    as_of = _business_roll(d, tools).isoformat()

    out = _blank("CONFIRMED")
    out.update(account_id=acct_id, instrument_id=inst_id, as_of=as_of)

    if profile.get("legal_hold"):
        out["outcome"] = "ESCALATE"
        out["settled"] = _position(acct_id, inst_id, as_of, tools)
        return out, "legal_hold"
    # no_email_confirm: oracle Q4-0054 showed a normal CONFIRMED (with pending) is expected; flag ignored

    settled = _position(acct_id, inst_id, as_of, tools)
    pend, pend_date, stale = _pending(acct_id, inst_id, as_of, tools)
    fig = parse_figure(request["body"])
    if settled == 0 and not pend:
        if fig is not None and fig != 0:
            out["outcome"] = "NOT_HELD"
            return out, "not_held_figure"
        out["outcome"] = "NOT_HELD"
        return out, "not_held"
    if fig is not None:
        total = settled + (pend or 0)
        ref = [settled, total]
        close = any(abs(fig - r) <= TOLERANCE * abs(r) for r in ref if r != 0)
        if not close:
            out["outcome"] = "ESCALATE"
            out["settled"] = settled
            return out, "qty_mismatch"
    out["settled"] = settled
    if pend:
        out["pending"] = pend
        out["pending_date"] = pend_date
        return out, "confirm_pending"
    if stale:
        return out, "confirm_stale_matched"
    return out, "confirm"


def respond(request, tools):
    try:
        return decide(request, tools)[0]
    except Exception:
        return _blank("REQUEST_INFO")
