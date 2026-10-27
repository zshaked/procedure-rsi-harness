"""Reference-free verifier for the position-confirmation desk.

verify(request, response, tools) -> (ok, failures)

Every check below is a condition a correct response must satisfy, derived from the
histories, the unlabeled requests and the tool docstrings (evidence noted per check).
Conventions that the histories leave open are module-level constants; they were
calibrated with the oracle (see NOTES.md).
"""
import re
import datetime as dt

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}

# ---- calibrated conventions (see NOTES.md, oracle log) ----
MIN_LEVEL = 3                 # 0002/0009 (L2) and 0003/0010 (L1) -> REQUEST_AUTHORIZATION; L3 confirms
REQUIRE_DOMAIN = False        # 0023: yahoo sender with valid L3 entitlement was answered
INFER_ACCOUNT_FROM_SENDER = False  # oracle Q11/Q13 (0137): no account named -> REQUEST_INFO (0024 judged an operator slip)
NON_BUSINESS_DAY = "REQUEST_INFO"  # oracle Q4 (0057): not a business day -> ask which date they want
FUTURE_DATE = "REQUEST_INFO"  # date after the email was sent
LEGAL_HOLD = "ESCALATE"
NO_EMAIL_CONFIRM = "REQUEST_AUTHORIZATION"   # 0024
FIGURE_TOLERANCE = 0.03       # oracle Q5 (0132): 2% off confirmed; 0012: 7% off -> ESCALATE
PENDING_MATCH_OK = True       # client figure == settled + matched pending is not a break
PENDING_WINDOW_DAYS = 90      # oracle Q1-Q3: +17d, +36d, +65d after as_of reported; +107d not
LARGE_POSITION = 1_000_000    # oracle Q6 (0175): "positions that size always go to escalation"
NOT_HELD_WITH_FIGURE = "NOT_HELD"  # oracle Q12 (0080): zero position is NOT_HELD even if the client quotes a figure


MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}


def strip_forward(body):
    # Forwarded-message headers ("Date: 2026-01-27") are not the position date (0002, 0009, 0012).
    return "\n".join(l for l in body.split("\n")
                     if not re.match(r'\s*(From|Date|To|Sent|Subject|Cc):', l, re.I)
                     and 'forwarded message' not in l.lower()
                     and 'original message' not in l.lower())


def _month_end_prev(d):
    return d.replace(day=1) - dt.timedelta(days=1)


def _mk(y, mo, d):
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def parse_date(body, sent):
    """-> (date|None, mentioned: bool). Relative expressions are relative to `sent`."""
    sent_d = dt.date.fromisoformat(sent)
    t = strip_forward(body).lower()
    m = re.search(r'(?:as at|as of|as on|position date|positions? at|holdings? at|dated)\s*:?\s*'
                  r'(?:the\s+)?(?:close of business|cob|eod|end of day)?\s*(?:on\s+)?(.*?)(?:\?|\.\s|\.$|\n|$)', t)
    cand = m.group(1) if m else t
    if re.search(r'\byesterday\b', cand):
        return sent_d - dt.timedelta(days=1), True
    if re.search(r'\btoday\b|\bcurrent(ly)?\b|\bnow\b', cand) and m:
        return sent_d, True
    if re.search(r'end of last month|last day of (the )?(last|previous|prior) month|month[- ]?end|'
                 r'end of (the )?(previous|prior) month|last month[- ]?end|eom', cand):
        return _month_end_prev(sent_d), True
    if re.search(r'end of last year|year[- ]end|last day of last year', cand):
        return dt.date(sent_d.year - 1, 12, 31), True
    x = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', cand)
    if x:
        return _mk(int(x[1]), int(x[2]), int(x[3])), True
    x = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', cand)
    if x:
        y = int(x[3]); y = y + 2000 if y < 100 else y
        return _mk(y, int(x[1]), int(x[2])), True
    x = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?[- ]([a-z]{3})[a-z]*\.?[- ,]+(\d{4})\b', cand)
    if x and x[2] in MONTHS:
        return _mk(int(x[3]), MONTHS[x[2]], int(x[1])), True
    x = re.search(r'\b([a-z]{3})[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b', cand)
    if x and x[1] in MONTHS:
        return _mk(int(x[3]), MONTHS[x[1]], int(x[2])), True
    return None, bool(m)


def parse_qty(s):
    s = s.strip().lower().replace(',', '').replace(' ', '')
    mult = 1
    if s.endswith('mm'):
        mult, s = 1_000_000, s[:-2]
    elif s.endswith('m'):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith('k'):
        mult, s = 1000, s[:-1]
    return int(round(float(s) * mult))


def parse_figure(body):
    t = strip_forward(body).lower()
    m = re.search(r'(?:our figure is|we have|we show|records show|books show|we hold|we see|our position is|'
                  r'our records indicate|reconciles? to)\s*:?\s*(-?\d[\d,]*(?:\.\d+)?\s?(?:mm|m|k)?)(?![\w])', t)
    if not m:
        return None
    try:
        return parse_qty(m.group(1))
    except ValueError:
        return None


def expected(request, tools):
    """The desk's decision chain, as facts the checks below compare against."""
    from_ = request["from"].strip().lower()
    sent = request["sent"]
    men = request.get("mentions") or {}
    at, it = men.get("account_text"), men.get("instrument_text")
    contact = tools.get_contact(from_)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    E = {"outcome": None}

    # account resolution
    acc = None
    if at and at.strip():
        hits = tools.search_accounts(at)
        if len(hits) != 1:
            E.update(outcome="REQUEST_INFO", why="account not uniquely identified")
            return E
        acc = hits[0]["id"]
    else:
        accs = sorted({e["account_id"] for e in ents})
        if INFER_ACCOUNT_FROM_SENDER and len(accs) == 1:
            acc = accs[0]
        else:
            E.update(outcome="REQUEST_INFO", why="no account")
            return E
    E["account_id"] = acc

    # authorization
    ok = any(e["account_id"] == acc and e["level"] >= MIN_LEVEL and e["expires"] >= sent for e in ents)
    prof = tools.get_client_profile(acc) or {}
    if ok and REQUIRE_DOMAIN:
        ok = from_.split("@")[-1] in [d.lower() for d in prof.get("domains", [])]
    if not ok:
        E.update(outcome="REQUEST_AUTHORIZATION", why="sender not entitled")
        return E

    # instrument
    ins = tools.search_instruments(it) if it and it.strip() else []
    if len(ins) != 1:
        E.update(outcome="REQUEST_INFO", why="instrument not uniquely identified")
        return E
    iid = ins[0]["id"]
    E["instrument_id"] = iid

    if prof.get("no_email_confirm"):
        E.update(outcome=NO_EMAIL_CONFIRM, why="client does not allow email confirmations")
        return E
    if prof.get("legal_hold"):
        E.update(outcome=LEGAL_HOLD, why="legal hold")
        return E

    # date
    d, mentioned = parse_date(request["body"], sent)
    if d is None and mentioned:
        E.update(outcome="REQUEST_INFO", why="unreadable date")
        return E
    assumed = d is None
    if assumed:
        d = dt.date.fromisoformat(sent)
    if d.isoformat() > sent:
        E.update(outcome=FUTURE_DATE, why="future date")
        return E
    asof = d.isoformat()
    if assumed and not tools.get_calendar(asof)["business_day"]:
        asof = tools.get_calendar(asof)["previous_business_day"]
    if not tools.get_calendar(asof)["business_day"]:
        E.update(outcome=NON_BUSINESS_DAY, why="non-business day")
        return E
    E.update(as_of=asof, as_of_assumed=assumed)

    # settled: all custody sub-accounts, recorded on/before as_of, split-adjusted
    cas = tools.get_corporate_actions(iid)
    tot = 0
    for t in tools.get_ledger(acc, iid):
        if t["date"] <= asof:
            q = t["qty"]
            for c in cas:
                if c.get("type", "split") == "split" and t["date"] < c["date"] <= asof:
                    q *= c["ratio"]
            tot += q
    E["settled"] = tot
    pend = [x for x in tools.get_instructions(acc, iid)
            if x["status"] == "matched" and x["settle_date"] > asof]
    if PENDING_WINDOW_DAYS is not None:
        lim = (dt.date.fromisoformat(asof) + dt.timedelta(days=PENDING_WINDOW_DAYS)).isoformat()
        pend = [x for x in pend if x["settle_date"] <= lim]
    E["pending"] = sum(x["qty"] for x in pend) if pend else None
    E["pending_date"] = max(x["settle_date"] for x in pend) if pend else None

    fig = parse_figure(request["body"])
    E["figure"] = fig
    if tot == 0:
        E["pending"] = E["pending_date"] = None
        if fig not in (None, 0):
            E.update(outcome=NOT_HELD_WITH_FIGURE, why="client claims a holding we do not show")
        else:
            E.update(outcome="NOT_HELD", why="no settled position")
        return E
    if tot < 0:
        E.update(outcome="ESCALATE", why="non-positive position")
        return E
    if fig is not None:
        ok_fig = abs(fig - tot) <= FIGURE_TOLERANCE * max(abs(tot), 1)
        if not ok_fig and PENDING_MATCH_OK and E["pending"]:
            ok_fig = fig == tot + E["pending"]
        if not ok_fig:
            E.update(outcome="ESCALATE", why="client figure differs from ours")
            return E
    if abs(tot) >= LARGE_POSITION:
        E.update(outcome="ESCALATE", why="large position")
        return E
    E.update(outcome="CONFIRMED", why="ok")
    return E


def verify(request, response, tools):
    fails = []
    r = response or {}
    E = expected(request, tools)
    out = r.get("outcome")

    # C0 shape: outcome is one of the five; keys present
    if out not in OUTCOMES:
        fails.append("C0 outcome not in allowed set")
        return False, fails
    for k in ("account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date"):
        if k not in r:
            fails.append(f"C0 missing key {k}")

    # C1 account must resolve to exactly one account (0000,0006,0017,0021: ambiguous name -> REQUEST_INFO,
    #    even when the sender is entitled to one of the candidates)
    if E.get("why") in ("account not uniquely identified", "no account") and out != "REQUEST_INFO":
        fails.append("C1 account ambiguous/unknown -> REQUEST_INFO")

    # C2 authorization before anything else is disclosed (0002,0003,0009,0010,0014,0015,0016,0005):
    #    valid (unexpired) entitlement on that account at level >= 3
    if E.get("why") == "sender not entitled" and out != "REQUEST_AUTHORIZATION":
        fails.append("C2 sender not entitled -> REQUEST_AUTHORIZATION")
    if out in ("CONFIRMED", "NOT_HELD") and E.get("why") == "sender not entitled":
        fails.append("C2b position disclosed to unentitled sender")

    # C3 instrument must be identified (0004, 0019: authorised but no security -> REQUEST_INFO)
    if E.get("why") == "instrument not uniquely identified" and out != "REQUEST_INFO":
        fails.append("C3 instrument missing/ambiguous -> REQUEST_INFO")

    # C4 client-profile restrictions (0024: no_email_confirm -> REQUEST_AUTHORIZATION; legal hold -> calibrated)
    if E.get("why") == "client does not allow email confirmations" and out != NO_EMAIL_CONFIRM:
        fails.append("C4 no_email_confirm")
    if E.get("why") == "legal hold" and out != LEGAL_HOLD:
        fails.append("C4b legal hold")

    # C5 date handling: unreadable or future date
    if E.get("why") in ("unreadable date", "future date", "non-business day") and out != E["outcome"]:
        fails.append("C5 date not confirmable")

    # C6 figure break (0012): client figure differs from settled -> ESCALATE
    if E.get("why") in ("client figure differs from ours", "client claims a holding we do not show",
                        "non-positive position", "large position") and out != E["outcome"]:
        fails.append("C6 figure break -> " + E["outcome"])

    # C7 no position -> NOT_HELD (0023)
    if E.get("why") == "no settled position" and out != "NOT_HELD":
        fails.append("C7 zero position -> NOT_HELD")
    if E.get("why") == "ok" and out != "CONFIRMED":
        fails.append("C7b position agrees -> CONFIRMED")

    # C8 field population (README)
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        if r.get("account_id") != E.get("account_id"):
            fails.append("C8 account_id")
        if E.get("instrument_id") and r.get("instrument_id") != E.get("instrument_id"):
            fails.append("C8 instrument_id")
    if out in ("CONFIRMED", "NOT_HELD") and E["outcome"] == out:
        # C9 as_of: requested date, rolled to the previous business day; email date when none given
        if r.get("as_of") != E.get("as_of"):
            fails.append(f"C9 as_of {r.get('as_of')} != {E.get('as_of')}")
        if bool(r.get("as_of_assumed")) != E.get("as_of_assumed"):
            fails.append("C9b as_of_assumed")
    if out == "CONFIRMED" and E["outcome"] == out:
        # C10 settled = ledger over ALL sub-accounts (not get_position_summary), split-adjusted (0001, 0018)
        if r.get("settled") != E.get("settled"):
            fails.append(f"C10 settled {r.get('settled')} != {E.get('settled')}")
        # C11 pending: matched (not unmatched/cancelled) instructions settling after as_of (0008)
        if r.get("pending") != E.get("pending") or r.get("pending_date") != E.get("pending_date"):
            fails.append(f"C11 pending {r.get('pending')}/{r.get('pending_date')} != {E.get('pending')}/{E.get('pending_date')}")
    if out not in ("CONFIRMED",):
        if r.get("settled") is not None:
            fails.append("C12 settled only on CONFIRMED")
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION"):
        if r.get("as_of") is not None:
            fails.append("C12b no as_of on requests")
    return (not fails), fails
