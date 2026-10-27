"""Reference-free verifier for desk replies to holding-confirmation requests.

verify(request, response, tools) -> (ok, failures)

Each check below is a separate, commented condition a correct response must satisfy, with the
evidence it was derived from (H = histories.jsonl case, O = oracle answer, T = tools docstring).
The checks recompute the facts they need from `tools` only; no reply text is consulted.
"""
import datetime as dt
import re

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


# ---------------------------------------------------------------- parsing helpers
def _d(s):
    return dt.date.fromisoformat(s)


def _last_day_prev_month(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def parse_date(body, sent):
    """Return (date|None, kind) where kind in {'explicit','relative','none'}."""
    sent_d = _d(sent)
    text = re.sub(r"-+ ?Forwarded message ?-+.*?Date: *\S+", " ", body, flags=re.S)
    text = re.sub(r"This email and any attachments.*", " ", text, flags=re.S)
    low = text.lower()
    if re.search(r"\byesterday\b", low):
        return sent_d - dt.timedelta(days=1), "relative"
    if re.search(r"end of last month|last day of last month|month-end|month end", low):
        return _last_day_prev_month(sent_d), "relative"
    if re.search(r"\btoday\b", low):
        return sent_d, "relative"
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:  # US style M/D/YYYY (H: 12/17/2025)
        return dt.date(int(m[3]), int(m[1]), int(m[2])), "explicit"
    m = re.search(r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]+(\d{4})\b", text)
    if m and m[2][:3].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), "explicit"
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", text)
    if m and m[1][:3].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), "explicit"
    return None, "none"


def parse_figure(body):
    """Client's own figure, if stated (H: 'We show', 'our figure is', 'Our records show', 'We have')."""
    text = re.sub(r"This email and any attachments.*", " ", body, flags=re.S)
    m = re.search(r"(?:we show|our figure is|our records show|we have)\s+(\d[\d,]*(?:\.\d+)?(?:k|mm|m)?)\b",
                  text, flags=re.I)
    if not m:
        return None
    return parse_qty(m[1])


def parse_qty(s):
    s = s.strip().lower().replace(",", "")
    mult = 1
    if s.endswith("mm"):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(round(float(s.strip()) * mult))
    except ValueError:
        return None


def business_roll(tools, d):
    cal = tools.get_calendar(d.isoformat())
    return d if cal["business_day"] else _d(cal["previous_business_day"])


# ---------------------------------------------------------------- facts
def facts(request, tools):
    """Everything the checklist needs, recomputed from tools."""
    f = {}
    m = request.get("mentions") or {}
    at, it = m.get("account_text"), m.get("instrument_text")
    f["accounts"] = tools.search_accounts(at) if at else []
    f["instruments"] = tools.search_instruments(it) if it else []
    f["account"] = f["accounts"][0]["id"] if len(f["accounts"]) == 1 else None
    f["instrument"] = f["instruments"][0]["id"] if len(f["instruments"]) == 1 else None
    f["sub_account"] = at.strip().upper() if at and re.fullmatch(r"\s*SA-\d+\s*", at) else None
    sender = request["from"].lower()
    f["domain"] = sender.split("@")[-1]
    contact = tools.get_contact(sender)
    f["contact"] = contact
    f["ents"] = tools.get_entitlements(contact["contact_id"]) if contact else []
    f["profile"] = tools.get_client_profile(f["account"]) if f["account"] else None
    d, kind = parse_date(request["body"], request["sent"])
    f["date_raw"], f["date_kind"] = d, kind
    f["figure"] = parse_figure(request["body"])
    return f


def authorized(f, sent):
    ok_ent = any(e["account_id"] == f["account"] and e["level"] >= 2 and e["expires"] >= sent
                 for e in f["ents"])
    ok_dom = f["profile"] is not None and f["domain"] in [x.lower() for x in f["profile"]["domains"]]
    return ok_ent and ok_dom


def settled_at(tools, acct, inst, as_of, sub=None):
    """Sum of ledger across ALL sub-accounts (H-0004, H-0021, H-0022) with date <= as_of,
    split-adjusted for splits effective on/before as_of (T: split multiplies earlier holdings)."""
    led = tools.get_ledger(acct, inst)
    splits = [c for c in tools.get_corporate_actions(inst) if c["type"] == "split"]
    tot = 0
    for t in led:
        if t["date"] > as_of:
            continue
        if sub and t["sub_account"].upper() != sub:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        tot += q
    return tot


def pending_at(tools, acct, inst, as_of):
    """Matched instructions settling after as_of (H-0021: matched INS reported as pending;
    unmatched/cancelled never reported: H-0008, H-0018, H-0010; O-0025: settle date before the
    email date still counts). Amount = sum (O-0089 accepted the sum), date = LATEST settle date
    (O-0089 rejected the earliest). An instruction settling after a split that falls after as_of
    is split-adjusted (O-0076 rejected the unadjusted 601)."""
    splits = [c for c in tools.get_corporate_actions(inst) if c["type"] == "split"]
    ins = [x for x in tools.get_instructions(acct, inst)
           if x["status"] == "matched" and x["settle_date"] > as_of]
    if not ins:
        return None, None
    tot = 0
    for x in ins:
        q = x["qty"]
        for sp in splits:
            if as_of < sp["date"] <= x["settle_date"]:
                q *= sp["ratio"]
        tot += q
    return tot, max(x["settle_date"] for x in ins)


def figure_matches(fig, ours, tol=0.01):
    """Client figure compared with settled + pending (O-0006: settled-only match still escalated;
    O-0051: figure == settled+pending accepted). Small tolerance ('closely enough', O-0006);
    every observed discrepancy is >= 2% (H-0012), so tol < 2%."""
    return abs(fig - ours) <= tol * max(abs(ours), 1)


def expected(request, tools, f=None):
    """Derived expectation used by the checks (not a reply; reference-free)."""
    f = f or facts(request, tools)
    sent = request["sent"]
    e = {"facts": f}
    # account/instrument must be uniquely identified (H-0002, H-0003, H-0005, H-0023)
    if not f["account"] or not f["instrument"]:
        e["outcome"] = "REQUEST_INFO"
        return e
    # sender must be entitled (level>=2, unexpired) AND write from a client domain
    # (H-0009 lvl1 expired, H-0018 lvl1, H-0019/H-0024/H-0000 wrong acct, H-0014 proton.me)
    if not authorized(f, sent):
        e["outcome"] = "REQUEST_AUTHORIZATION"
        return e
    prof = f["profile"]
    if prof.get("legal_hold"):
        e["outcome"] = "ESCALATE"          # guess, calibrated by oracle
        return e
    if prof.get("no_email_confirm"):
        # untestable (no authorized no_email_confirm sender in the pool); O-0095 shows the
        # domain/authorization check runs first. Guess: refer it (ESCALATE).
        e["outcome"] = "ESCALATE"
        return e
    d, kind = f["date_raw"], f["date_kind"]
    assumed = kind == "none"
    if d is None:
        d = _d(sent)
    if d > _d(sent):
        e["outcome"] = "REQUEST_INFO"      # future position date: cannot confirm (guess)
        return e
    as_of = business_roll(tools, d)       # H-0017: Sat 31 Jan -> 2026-01-30
    e["as_of"], e["as_of_assumed"] = as_of.isoformat(), assumed
    s = settled_at(tools, f["account"], f["instrument"], as_of.isoformat())
    e["settled"] = s
    e["pending"], e["pending_date"] = pending_at(tools, f["account"], f["instrument"], as_of.isoformat())
    # client figure disagrees with ours -> escalate (H-0008, H-0011, H-0013, H-0015, H-0016, H-0020)
    total = s + (e["pending"] or 0)
    if f["figure"] is not None and not figure_matches(f["figure"], total):
        e["outcome"] = "ESCALATE"
        return e
    if s < 0:
        e["outcome"] = "ESCALATE"          # negative net position: data break (guess)
        return e
    e["outcome"] = "NOT_HELD" if s == 0 else "CONFIRMED"   # O-0123, O-0153
    return e


# ---------------------------------------------------------------- the checklist
def verify(request, response, tools):
    fails = []
    f = facts(request, tools)
    e = expected(request, tools, f)
    out = response.get("outcome")

    # CHECK 1 (README): outcome is one of the five enum values.
    if out not in OUTCOMES:
        return False, ["C1 invalid outcome %r" % out]

    # CHECK 2 (H-0002/0003/0005/0023): if account or instrument cannot be resolved to exactly one
    # record, the only acceptable outcome is REQUEST_INFO; conversely REQUEST_INFO is wrong when
    # both resolve uniquely.
    unresolved = not f["account"] or not f["instrument"]
    if unresolved and out != "REQUEST_INFO":
        fails.append("C2 unresolved account/instrument requires REQUEST_INFO")
    if not unresolved and out == "REQUEST_INFO" and e["outcome"] != "REQUEST_INFO":
        fails.append("C2b REQUEST_INFO although account and instrument resolve uniquely")

    # CHECK 3 (H-0000/0009/0014/0018/0019/0024): if resolved but sender is not authorized
    # (needs unexpired entitlement level>=2 on that account and a sender domain listed in the
    # client profile), outcome must be REQUEST_AUTHORIZATION; never disclose a figure.
    if not unresolved and not authorized(f, request["sent"]):
        if out != "REQUEST_AUTHORIZATION":
            fails.append("C3 unauthorized sender requires REQUEST_AUTHORIZATION")
    if out == "REQUEST_AUTHORIZATION" and e["outcome"] != "REQUEST_AUTHORIZATION":
        fails.append("C3b REQUEST_AUTHORIZATION although sender is authorized")

    # CHECK 4 (profile flags): legal hold -> ESCALATE (O-0096); flags are checked only after the
    # sender is authorized (O-0177 legal hold + gmail -> REQUEST_AUTHORIZATION; O-0095).
    if not unresolved and authorized(f, request["sent"]) and f["profile"]:
        if f["profile"].get("legal_hold") and out != "ESCALATE":
            fails.append("C4 legal hold requires ESCALATE")
        if f["profile"].get("no_email_confirm") and not f["profile"].get("legal_hold") \
                and out != e["outcome"]:
            fails.append("C4b no_email_confirm requires %s" % e["outcome"])

    # CHECK 5 (README): account/instrument filled for CONFIRMED/NOT_HELD/ESCALATE and equal to
    # the uniquely resolved ids (H-0010: short name SGEIII -> ACC-10225; H-0015: SA- -> parent).
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        if response.get("account_id") != f["account"]:
            fails.append("C5 account_id should be %s" % f["account"])
        if response.get("instrument_id") != f["instrument"]:
            fails.append("C5 instrument_id should be %s" % f["instrument"])

    # CHECK 6 (H-0017, H-0022, H-0010): as_of is the requested date rolled back to a business day
    # when it is a weekend/holiday; as_of_assumed true iff the email gave no date.
    if out in ("CONFIRMED", "NOT_HELD") and "as_of" in e:
        if response.get("as_of") != e["as_of"]:
            fails.append("C6 as_of should be %s" % e["as_of"])
        if bool(response.get("as_of_assumed")) != e["as_of_assumed"]:
            fails.append("C6 as_of_assumed should be %s" % e["as_of_assumed"])

    # CHECK 7 (H-0001/0004/0021/0022): settled = ledger summed over all sub-accounts up to as_of,
    # split-adjusted; NOT the cached get_position_summary (primary sub-account, prior day).
    if out == "CONFIRMED" and "settled" in e:
        if response.get("settled") != e["settled"]:
            fails.append("C7 settled should be %s" % e["settled"])
        if e["settled"] == 0:
            fails.append("C7b zero holding cannot be CONFIRMED")
    if out == "NOT_HELD" and e.get("settled", 0) != 0:
        fails.append("C7c NOT_HELD but holding is %s" % e.get("settled"))

    # CHECK 8 (H-0021, O-0025/0089/0076): pending/pending_date reported iff matched instructions
    # settle after as_of; summed, latest date, split-adjusted across a later split.
    if out in ("CONFIRMED", "NOT_HELD") and "settled" in e:
        if response.get("pending") != e["pending"] or response.get("pending_date") != e["pending_date"]:
            fails.append("C8 pending should be %s/%s" % (e["pending"], e["pending_date"]))

    # CHECK 9 (H-0008/0011/0013/0015/0016/0020): a stated client figure that differs from our
    # settled figure must be ESCALATEd, never CONFIRMED/NOT_HELD.
    if "settled" in e and f["figure"] is not None:
        tot = e["settled"] + (e["pending"] or 0)
        if not figure_matches(f["figure"], tot) and out in ("CONFIRMED", "NOT_HELD"):
            fails.append("C9 client figure %s vs settled+pending %s requires ESCALATE" % (f["figure"], tot))
        if figure_matches(f["figure"], tot) and out == "ESCALATE" and e["outcome"] != "ESCALATE":
            fails.append("C9b figures agree (O-0051); ESCALATE not warranted")

    # CHECK 10: when everything resolves, is authorized, and figures agree, outcome must be the
    # disclosure outcome (CONFIRMED / NOT_HELD), not a gratuitous ESCALATE.
    if e["outcome"] in ("CONFIRMED", "NOT_HELD") and out != e["outcome"]:
        fails.append("C10 expected %s" % e["outcome"])

    # CHECK 11: non-disclosure outcomes must not leak figures.
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION", "ESCALATE"):
        if response.get("settled") is not None:
            fails.append("C11 figure leaked on %s" % out)

    # CHECK 12 (residual): future position date -> REQUEST_INFO; negative net -> ESCALATE.
    if e["outcome"] != out and not fails:
        fails.append("C12 expected %s" % e["outcome"])

    return (not fails), fails
