"""Reference-free verifier for responses to position-confirmation requests.

verify(request, response, tools) -> (ok: bool, failures: list[str])

Each check below is a separate, commented condition a correct response must satisfy, with the
evidence it was derived from (H = histories.jsonl case, U = unlabeled, O = oracle answer, T = tools.py).
Self-contained: standard library + `tools` only.
"""
import re
import datetime as dt

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}

# Conventions that the oracle calibration settled (see NOTES.md); kept as named constants.
CFG = {
    "tolerance": 0.10,          # match band: O-0094 (0.93) and O-0077 (1.08) accepted as CONFIRMED; 0.85 escalated (H-0001/0003/0024)
    "min_level": 2,             # entitlement level needed to release a figure (H-0011 level 1 -> RA; H-0012 level 2 -> C)
    "future_outcome": "REQUEST_INFO",   # O-0083: date after `sent` -> REQUEST_INFO accepted
    "noemail_outcome": None,           # O-0054: "fine to confirm" despite no_email_confirm
    "hold_outcome": "ESCALATE",         # O-0114 accepted; O-0118: authorization is checked before the hold
    "zero_with_claim": "NOT_HELD",      # O-0157: zero settled + client claim -> NOT_HELD accepted
    "assumed_when": "never",            # O-0077 (rolled) and O-0104 (month-end) both: flag must be False
    "subaccount_scope": "account",      # sub-account mention resolves to whole account
    "domain_must_match": True,          # O-0032: entitled sender from unregistered domain -> RA
    "old_ticker": "ok",                 # O-0049: former ticker ZDXJ resolved and confirmed
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "proton.me",
            "protonmail.com", "live.com", "msn.com", "mail.com", "gmx.com", "yahoo.co.uk", "googlemail.com"}


# ----------------------------------------------------------------------------- parsing helpers
def strip_forward(body):
    """Forwarded-message headers carry a 'Date:' that is NOT the position date (U-0029, U-0031)."""
    out = []
    for line in (body or "").split("\n"):
        s = line.strip()
        if re.match(r"^-+\s*(Forwarded|Original) message", s, re.I):
            continue
        if re.match(r"^(From|Date|Sent|To|Cc|Subject):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        out.append(line)
    return "\n".join(out)


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(body, sent):
    """(date|None, kind) with kind in explicit | relative | none | invalid."""
    s = dt.date.fromisoformat(sent)
    b = strip_forward(body)
    bl = b.lower()
    som = s.replace(day=1)
    if re.search(r"\b(end of (the )?(last|previous|prior) month|last day of (the )?(last|previous|prior) month|"
                 r"(last|previous|prior) month[- ]?end|month[- ]?end|end of (the )?month)\b", bl):
        return som - dt.timedelta(days=1), "relative"
    if re.search(r"\b(end of (the )?(last|previous|prior) year|year[- ]?end)\b", bl):
        return dt.date(s.year - 1, 12, 31), "relative"
    if re.search(r"\byesterday\b", bl):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"\b(last|previous|prior) business day\b", bl):
        return s - dt.timedelta(days=1), "relative"   # rolled to a business day later
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (d, "explicit") if d else (None, "invalid")
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", b)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        d = _mk(y, int(m.group(1)), int(m.group(2)))
        return (d, "explicit") if d else (None, "invalid")
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\.?[- ,]+(\d{4})\b", b)
    if m and m.group(2).lower()[:3] in MON3:
        d = _mk(int(m.group(3)), MON3[m.group(2).lower()[:3]], int(m.group(1)))
        return (d, "explicit") if d else (None, "invalid")
    m = re.search(r"\b(" + "|".join(MONTHS) + "|" + "|".join(MON3) + r")\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?\b", b, re.I)
    if m:
        mo = MON3[m.group(1).lower()[:3]]
        day = int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
        else:
            y = s.year
            cand = _mk(y, mo, day)
            if cand and cand > s:
                y -= 1
        d = _mk(y, mo, day)
        return (d, "explicit") if d else (None, "invalid")
    if re.search(r"\b(today|as of now|current(ly)?|latest)\b", bl):
        return s, "relative"
    return None, "none"


def parse_qty(body):
    """Client's own figure. '12,500', '12500', '12.5k', '1.2mm' (README)."""
    b = strip_forward(body)
    m = re.search(r"(?:records show|our figure is|we show|we have|we hold|our books show|books reflect|we see|"
                  r"our position is|we record)\s+(-?[\d,]*\.?\d+)\s*(k|mm|mn|m|million|thousand|bn)?\b", b, re.I)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    if suf in ("k", "thousand"):
        v *= 1000
    elif suf in ("mm", "mn", "m", "million"):
        v *= 1_000_000
    elif suf == "bn":
        v *= 1_000_000_000
    return int(round(v))


# ----------------------------------------------------------------------------- facts from tools
def gather(request, tools):
    r = request
    m = r.get("mentions") or {}
    sent = r["sent"]
    F = {"sent": sent}
    sender = (r.get("from") or "").strip().lower()
    F["domain"] = sender.split("@")[-1]
    F["freemail"] = F["domain"] in FREEMAIL
    F["contact"] = tools.get_contact(sender) if sender else None
    at = (m.get("account_text") or "").strip()
    it = (m.get("instrument_text") or "").strip()
    ah = tools.search_accounts(at) if at else []
    F["acc_hits"] = ah
    F["acc"] = ah[0]["id"] if len(ah) == 1 else None
    ih = tools.search_instruments(it) if it else []
    F["ins_hits"] = ih
    F["ins"] = ih[0]["id"] if len(ih) == 1 else None
    F["old_ticker"] = bool(F["ins"] and ih[0]["old_ticker"] and ih[0]["old_ticker"].lower() == it.lower())
    F["date"], F["dkind"] = parse_date(r.get("body", ""), sent)
    F["qty"] = parse_qty(r.get("body", ""))
    F["level"] = None
    if F["acc"]:
        F["profile"] = tools.get_client_profile(F["acc"]) or {}
        if F["contact"]:
            for e in tools.get_entitlements(F["contact"]["contact_id"]):
                if e["account_id"] == F["acc"] and e["expires"] >= sent:
                    F["level"] = max(F["level"] or 0, e["level"])
    if F["date"]:
        cal = tools.get_calendar(F["date"].isoformat())
        F["as_of"] = F["date"].isoformat() if cal["business_day"] else cal["previous_business_day"]
        F["rolled"] = not cal["business_day"]
    if F["acc"] and F["ins"] and F.get("as_of"):
        a = F["as_of"]
        splits = [s for s in tools.get_corporate_actions(F["ins"]) if s.get("type") == "split"]
        tot = 0
        for t in tools.get_ledger(F["acc"], F["ins"]):
            if t["date"] > a:
                continue
            q = t["qty"]
            for s in splits:
                if t["date"] < s["date"] <= a:
                    q *= s["ratio"]
            tot += q
        F["settled"] = tot
        pend = [x for x in tools.get_instructions(F["acc"], F["ins"])
                if x["status"] == "matched" and x["settle_date"] > a]
        F["pending"] = sum(x["qty"] for x in pend) if pend else None
        F["pending_date"] = max(x["settle_date"] for x in pend) if pend else None
    return F


def expected_outcome(F, cfg=CFG):
    """The decision chain implied by the checks; returns (outcome, reason)."""
    if F["freemail"] or not F["contact"]:
        return "REQUEST_AUTHORIZATION", "sender not a verifiable corporate contact"
    if not F["acc"]:
        return "REQUEST_INFO", "account missing or ambiguous"
    prof = F.get("profile") or {}
    if cfg["domain_must_match"] and F["domain"] not in prof.get("domains", []):
        return "REQUEST_AUTHORIZATION", "domain not registered"
    if (F["level"] or 0) < cfg["min_level"]:
        return "REQUEST_AUTHORIZATION", "no live entitlement >= level"
    if not F["ins"]:
        return "REQUEST_INFO", "instrument missing or ambiguous"
    if F["dkind"] in ("none", "invalid"):
        return "REQUEST_INFO", "no usable position date"
    if F["date"].isoformat() > F["sent"]:
        return cfg["future_outcome"], "position date in the future"
    if prof.get("legal_hold"):
        return cfg["hold_outcome"], "legal hold"
    if prof.get("no_email_confirm") and cfg["noemail_outcome"]:
        return cfg["noemail_outcome"], "client does not allow email confirmation"
    if F["old_ticker"] and cfg["old_ticker"] != "ok":
        return cfg["old_ticker"], "former ticker"
    S = F["settled"]
    if S < 0:
        return "ESCALATE", "negative position"
    q = F["qty"]
    if S == 0:
        if q not in (None, 0) and cfg["zero_with_claim"] == "ESCALATE":
            return "ESCALATE", "client claims holding we do not show"
        return "NOT_HELD", "nothing settled"
    if q is not None:
        tol = cfg["tolerance"]
        cands = [S] + ([S + F["pending"]] if F.get("pending") else [])
        if not any(abs(q - c) <= tol * abs(c) for c in cands):
            return "ESCALATE", "client figure disagrees"
    return "CONFIRMED", "ok"


def verify(request, response, tools, cfg=CFG):
    fails = []
    R = response or {}
    out = R.get("outcome")
    # CHECK 0: well-formed outcome (README contract).
    if out not in OUTCOMES:
        return False, ["outcome not in enum"]
    F = gather(request, tools)
    exp, why = expected_outcome(F, cfg)

    # CHECK 1: freemail / unknown senders get REQUEST_AUTHORIZATION before anything else
    #   (H-0008 gmail with a level-3 entitlement -> RA; H-0009 gmail, no account -> RA).
    # CHECK 2: account must resolve to exactly one account; else REQUEST_INFO
    #   (H-0002 'Granite Global Equity' prefix-matches 3; H-0022 3 hits; H-0017 short name 'SP' 2 hits).
    # CHECK 3: a live (unexpired at `sent`) entitlement of level >= 2 to that account
    #   (H-0004/0005/0018/0020 none -> RA; H-0011 level 1 -> RA; H-0012/0013/0015 level 2 -> CONFIRMED).
    # CHECK 4: instrument must resolve (H-0008 missing instrument, but auth failed first);
    #   position date must be present (H-0014, H-0016 -> REQUEST_INFO).
    # CHECK 5: profile flags legal_hold / no_email_confirm block confirmation (T: get_client_profile; O).
    # CHECK 6: client figure must agree with settled (or settled+pending) within tolerance, else ESCALATE
    #   (H-0001/0003/0024 at 0.85 -> ESCALATE; H-0019 pre-split figure -> ESCALATE;
    #    H-0000 at 1.04 -> CONFIRMED; H-0013 0.93 of settled+pending -> CONFIRMED).
    # CHECK 7: nothing settled -> NOT_HELD.
    if out != exp:
        fails.append(f"outcome {out} but expected {exp} ({why})")

    # CHECK 8: field population per outcome (README).
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        if R.get("account_id") != F["acc"]:
            fails.append(f"account_id {R.get('account_id')} != {F['acc']}")
        if R.get("instrument_id") != F["ins"]:
            fails.append(f"instrument_id {R.get('instrument_id')} != {F['ins']}")
    if out in ("CONFIRMED", "NOT_HELD") and exp == out:
        # CHECK 9: as_of is the requested date rolled back to the previous business day
        #   (H-0006 Sat 3 Jan -> 2026-01-02; H-0013 Sun 1 Feb -> 2026-01-30; H-0012 month-end -> 01-30).
        if R.get("as_of") != F["as_of"]:
            fails.append(f"as_of {R.get('as_of')} != {F['as_of']}")
        # CHECK 10: as_of_assumed is True iff the desk had to interpret the date (O calibration).
        if cfg["assumed_when"] == "relative_or_rolled":
            want = F["dkind"] == "relative" or F["rolled"]
        elif cfg["assumed_when"] == "relative":
            want = F["dkind"] == "relative"
        elif cfg["assumed_when"] == "rolled":
            want = F["rolled"]
        else:
            want = False
        if bool(R.get("as_of_assumed")) != want:
            fails.append(f"as_of_assumed {R.get('as_of_assumed')} != {want}")
    if out == "CONFIRMED" and exp == out:
        # CHECK 11: settled is the sum over ALL sub-accounts, split-adjusted to as_of
        #   (H-0007 445,667 = 3 subs; H-0006 42,113 = 2 subs; get_position_summary uses primary sub only
        #    and the day before, so it is NOT the desk figure; O-0156: a weekend ledger entry after the
        #    rolled as_of is excluded and a sub-account mention still reports the whole account).
        if R.get("settled") != F["settled"]:
            fails.append(f"settled {R.get('settled')} != {F['settled']}")
        # CHECK 12: pending = matched instructions settling after as_of, summed, dated at the latest one
        #   (H-0013 79+38,071 = 38,150 expected 2026-04-05; H-0021 unmatched excluded; H-0010 unmatched only -> none;
        #    O-0054: an instruction settling after as_of but before `sent` must still be reported).
        if R.get("pending") != F.get("pending") or R.get("pending_date") != F.get("pending_date"):
            fails.append(f"pending {R.get('pending')}/{R.get('pending_date')} != {F.get('pending')}/{F.get('pending_date')}")
    if out != "CONFIRMED":
        # CHECK 13: settled/pending only reported on confirmations.
        if R.get("settled") is not None or R.get("pending") is not None:
            fails.append("settled/pending reported on non-confirmation")
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION"):
        # CHECK 14: do not leak resolved identifiers when not releasing anything.
        if R.get("account_id") is not None or R.get("instrument_id") is not None or R.get("as_of") is not None:
            fails.append("identifiers/as_of filled on a request-back")
    if out == "ESCALATE" and R.get("as_of") is not None:
        fails.append("as_of filled on ESCALATE")
    return (not fails), fails
