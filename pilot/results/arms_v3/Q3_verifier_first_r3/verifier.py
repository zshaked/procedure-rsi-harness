"""Reference-free verifier for the position-confirmation desk.

verify(request, response, tools) -> (ok, failures)

Each check below is a condition a correct response must satisfy, with the evidence it was
derived from (H = histories case, U = unlabeled case, O = oracle answer, T = tool docstring).
The verifier recomputes what it needs through `tools` only; it never looks at a reference reply.
"""
import datetime as dt
import re

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}
MIN_LEVEL = 3          # H-0002, H-0009 level 2 -> AUTH; O-0028 confirmed "entitlement isn't high enough"
FIG_TOLERANCE = 0.05   # O-0132 (2% off) confirmed; H-0012 (7% off) escalated; 5% chosen in between
SIZE_LIMIT = 1_000_000 # O-0175: "positions that size always go to escalation"
PENDING_DAYS = 30      # O-0123 (+20d after email) reported; O-0074 (+34d) rejected

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "icloud.com", "aol.com"}


# ----------------------------------------------------------------------------- text helpers
def clean_body(body):
    """Drop forwarded-message headers (their 'Date:' line is not the position date) and
    the confidentiality footer."""
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if s.startswith("----------") or re.match(r"^(From|Date|Sent|To|Subject|Cc):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        lines.append(s)
    return " ".join(" ".join(lines).split())


def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month(tok):
    return _MONTHS.get(tok[:3].lower()) if tok and tok[:3].lower() in _MONTHS else None


def find_date(text, sent):
    """Returns (date|None, kind) where kind in {'abs','rel','none','bad'}."""
    t = text
    low = t.lower()
    # relative phrases
    if re.search(r"\byesterday\b", low):
        return sent - dt.timedelta(days=1), "rel"
    if re.search(r"\btoday\b|\bclose of business today\b", low):
        return sent, "rel"
    if re.search(r"(end of last month|last day of last month|month[- ]end|end of (the )?previous month|"
                 r"last month[- ]end|prior month[- ]end)", low):
        return sent.replace(day=1) - dt.timedelta(days=1), "rel"
    m = re.search(r"\bend of (january|february|march|april|may|june|july|august|september|october|november|december)"
                  r"(?:\s+(\d{4}))?", low)
    if m:
        mo = _month(m.group(1)); y = int(m.group(2)) if m.group(2) else sent.year
        if not m.group(2) and mo > sent.month:
            y -= 1
        nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
        return nxt - dt.timedelta(days=1), "rel"
    pats = [
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda g: _mk(int(g[0]), int(g[1]), int(g[2]))),
        (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", lambda g: _mk(int(g[2]), int(g[0]), int(g[1]))),
        (r"\b(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]+(\d{4})\b",
         lambda g: _mk(int(g[2]), _month(g[1]), int(g[0])) if _month(g[1]) else None),
        (r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b",
         lambda g: _mk(int(g[2]), _month(g[0]), int(g[1])) if _month(g[0]) else None),
        (r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?([A-Za-z]{3,9}),? (\d{4})\b",
         lambda g: _mk(int(g[2]), _month(g[1]), int(g[0])) if _month(g[1]) else None),
    ]
    found = []
    for p, f in pats:
        for mm in re.finditer(p, t):
            d = f(mm.groups())
            if d:
                found.append((mm.start(), d))
    if found:
        found.sort()
        return found[0][1], "abs"
    return None, "none"


def parse_qty(tok):
    s = tok.strip().rstrip(".").replace(",", "").lower()
    mult = 1
    for suf, mu in (("mm", 10 ** 6), ("mn", 10 ** 6), ("m", 10 ** 6), ("bn", 10 ** 9), ("k", 10 ** 3)):
        if s.endswith(suf):
            s = s[: -len(suf)]; mult = mu; break
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def client_figure(text):
    m = re.search(r"(?:we have|our records show|our figure is|we show|our books show|we hold|we hold|"
                  r"we record|our position is|we expect)\s+(-?[\d][\d,]*(?:\.\d+)?\s?(?:mm|mn|bn|m|k)?)\b",
                  text, re.I)
    if not m:
        return None
    return parse_qty(m.group(1).replace(" ", ""))


# ----------------------------------------------------------------------------- tool helpers
def resolve_account(text, tools):
    if not text or not text.strip():
        return None, "missing"
    hits = tools.search_accounts(text.strip())
    if len(hits) == 1:
        return hits[0]["id"], "ok"
    return None, ("ambiguous" if hits else "unknown")


def resolve_instrument(text, tools):
    if not text or not text.strip():
        return None, "missing"
    hits = tools.search_instruments(text.strip())
    ids = sorted({h["id"] for h in hits})
    if len(ids) == 1:
        return ids[0], "ok"
    return None, ("ambiguous" if ids else "unknown")


def authorized(sender, account_id, sent, tools):
    c = tools.get_contact(sender or "")
    if not c:
        return False
    for e in tools.get_entitlements(c["contact_id"]):
        if e["account_id"] == account_id and e["level"] >= MIN_LEVEL and e["expires"] >= sent:
            return True
    return False


def settled_qty(account_id, instrument_id, as_of, tools):
    """Sum over ALL sub-accounts of ledger rows dated <= as_of, split-adjusted to as_of (T: get_ledger,
    get_corporate_actions; H-0001, H-0018 sum several sub-accounts; position_summary is primary-only)."""
    cas = tools.get_corporate_actions(instrument_id)
    q = 0
    for t in tools.get_ledger(account_id, instrument_id):
        if t["date"] <= as_of:
            x = t["qty"]
            for c in cas:
                if c.get("type") == "split" and t["date"] < c["date"] <= as_of:
                    x *= c["ratio"]
            q += x
    return q


# ----------------------------------------------------------------------------- expectation
def infer_account(sender, tools):
    """No account named ("our fund"): the desk uses the sender's own entitled account (O-0062 accepted
    ESCALATE on the inferred account; H-0024 inferred account is no_email_confirm -> AUTH)."""
    c = tools.get_contact(sender or "")
    if not c:
        return None, "nocontact"
    accs = sorted({e["account_id"] for e in tools.get_entitlements(c["contact_id"])})
    if len(accs) == 1:
        return accs[0], "ok"
    return None, ("none" if not accs else "ambiguous")


def expected(request, tools):
    """Derive what the checklist demands: allowed outcomes and field values."""
    sent = dt.date.fromisoformat(request["sent"][:10])
    sent_s = sent.isoformat()
    men = request.get("mentions") or {}
    text = clean_body(request.get("body", ""))
    E = {"outcomes": None, "why": ""}

    # CHECK A: account resolves to exactly one account; sub-account ids map to the parent (T search_accounts).
    # Ambiguous/unknown -> REQUEST_INFO even if sender is entitled to one candidate (H-0000/0006/0017/0021).
    # Missing -> sender's single entitled account (O-0062, H-0024).
    if men.get("account_text") and men["account_text"].strip():
        acc, ast = resolve_account(men.get("account_text"), tools)
    else:
        acc, ast = infer_account(request.get("from"), tools)
        if ast == "nocontact":
            E["outcomes"] = {"REQUEST_AUTHORIZATION"}; E["why"] = "unknown sender, no account"; return E
    if ast != "ok":
        E["outcomes"] = {"REQUEST_INFO"}; E["why"] = "account " + ast; return E
    # CHECK B: live entitlement with level >= 3 on that account (O-0028: level 2 refused; H-0002/0009/0003/0010).
    # Sender domain is NOT checked (O-0025 gmail sender confirmed; H-0023 yahoo NOT_HELD).
    # Precedes instrument and date checks (H-0015; O-0045 unauthorized + weekend date -> AUTH).
    if not authorized(request.get("from"), acc, sent_s, tools):
        E["outcomes"] = {"REQUEST_AUTHORIZATION"}; E["why"] = "not authorized"; return E
    # CHECK C: instrument resolves (H-0004/0007/0019 -> REQUEST_INFO); former tickers allowed (T).
    ins, ist = resolve_instrument(men.get("instrument_text"), tools)
    if ist != "ok":
        E["outcomes"] = {"REQUEST_INFO"}; E["why"] = "instrument " + ist; return E
    E["account_id"] = acc
    E["instrument_id"] = ins
    # CHECK D: as-of date; none given -> date of the email, as_of_assumed True (H-0023).
    d, kind = find_date(text, sent)
    assumed = False
    if d is None:
        d, assumed = sent, True
    as_of = d.isoformat()
    # CHECK D2: not a business day (incl. relative dates landing on a weekend) -> REQUEST_INFO
    # (O-0057, O-0059, O-0085: date check precedes legal hold). Future date -> REQUEST_INFO (O-0051).
    if d > sent:
        E["outcomes"] = {"REQUEST_INFO"}; E["why"] = "future date"; return E
    if not tools.get_calendar(as_of)["business_day"]:
        E["outcomes"] = {"REQUEST_INFO"}; E["why"] = "non-business date"; return E
    # CHECK E: client profile flags. no_email_confirm -> REQUEST_AUTHORIZATION (O-0084).
    # legal_hold -> ESCALATE (assumed; never isolated by the oracle).
    prof = tools.get_client_profile(acc) or {}
    if prof.get("no_email_confirm"):
        E["outcomes"] = {"REQUEST_AUTHORIZATION"}; E["why"] = "no email confirm"; return E
    if prof.get("legal_hold"):
        E["outcomes"] = {"ESCALATE"}; E["why"] = "legal hold"; return E
    q = settled_qty(acc, ins, as_of, tools)
    E["as_of"] = as_of
    E["as_of_assumed"] = assumed
    E["settled"] = q
    # CHECK F: nothing settled -> NOT_HELD, even if the client quotes a figure (O-0080, H-0023).
    if q == 0:
        E["outcomes"] = {"NOT_HELD"}; return E
    if q < 0:
        E["outcomes"] = {"ESCALATE"}; E["why"] = "negative position"; return E
    # CHECK G: positions of 1,000,000 or more always escalate (O-0175 1,056,400; O-0145 split-adjusted 2.79M;
    # largest confirmed 855,399 in H-0011).
    if q >= SIZE_LIMIT:
        E["outcomes"] = {"ESCALATE"}; E["why"] = "large position"; return E
    # CHECK H: client figure must be within tolerance (O-0132 2% off confirmed; H-0012 7% off escalated).
    fig = client_figure(text)
    if fig is not None and abs(fig - q) > FIG_TOLERANCE * abs(q):
        E["outcomes"] = {"ESCALATE"}; E["why"] = "figure mismatch %s vs %s" % (fig, q); return E
    E["outcomes"] = {"CONFIRMED"}
    # CHECK I: pending = matched instructions settling after as_of and within PENDING_DAYS of the email
    # (H-0008 +7d reported; O-0123 +20d reported; O-0074 +34d wrong; H-0018 +81d, H-0020 +122d omitted).
    lim = (sent + dt.timedelta(days=PENDING_DAYS)).isoformat()
    pend = [x for x in tools.get_instructions(acc, ins)
            if x["status"] == "matched" and as_of < x["settle_date"] <= lim]
    E["pending"] = sum(x["qty"] for x in pend) if pend else None
    E["pending_date"] = min(x["settle_date"] for x in pend) if pend else None
    E["pending_strict"] = all(x["settle_date"] > sent_s for x in pend)
    return E


def verify(request, response, tools):
    fails = []
    r = response or {}
    out = r.get("outcome")
    # CHECK 0: schema
    if out not in OUTCOMES:
        return False, ["bad outcome %r" % out]
    for k in ("account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date"):
        if k not in r:
            fails.append("missing key " + k)
    E = expected(request, tools)
    if out not in E["outcomes"]:
        fails.append("outcome %s not in %s (%s)" % (out, sorted(E["outcomes"]), E["why"]))
        return False, fails
    # CHECK 1: identifiers for CONFIRMED / NOT_HELD / ESCALATE
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        if E.get("account_id") and r.get("account_id") != E["account_id"]:
            fails.append("account_id %s != %s" % (r.get("account_id"), E["account_id"]))
        if E.get("instrument_id") and r.get("instrument_id") != E["instrument_id"]:
            fails.append("instrument_id %s != %s" % (r.get("instrument_id"), E["instrument_id"]))
    # CHECK 2: date fields for CONFIRMED / NOT_HELD
    if out in ("CONFIRMED", "NOT_HELD"):
        if r.get("as_of") != E.get("as_of"):
            fails.append("as_of %s != %s" % (r.get("as_of"), E.get("as_of")))
        if bool(r.get("as_of_assumed")) != E.get("as_of_assumed"):
            fails.append("as_of_assumed %s != %s" % (r.get("as_of_assumed"), E.get("as_of_assumed")))
    # CHECK 3: settled figure for CONFIRMED (all sub-accounts, split-adjusted)
    if out == "CONFIRMED" and r.get("settled") != E.get("settled"):
        fails.append("settled %s != %s" % (r.get("settled"), E.get("settled")))
    if out != "CONFIRMED" and r.get("settled") not in (None,):
        if out != "NOT_HELD" or r.get("settled") not in (0,):
            fails.append("settled should be None for " + out)
    # CHECK 4: pending reported iff a matched instruction settles after as_of and within PENDING_DAYS
    # of the email; amount = total, date = earliest. Instructions already past their settle date at
    # the time of the email are tolerated either way (never isolated by the oracle).
    if out == "CONFIRMED":
        got = (r.get("pending"), r.get("pending_date"))
        want = (E.get("pending"), E.get("pending_date"))
        if got != want and not (not E.get("pending_strict") and got == (None, None)):
            fails.append("pending %s/%s != %s/%s" % (got + want))
    elif r.get("pending") is not None or r.get("pending_date") is not None:
        fails.append("pending reported on " + out)
    # CHECK 5: other outcomes carry no figures
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION"):
        for k in ("as_of", "settled", "pending", "pending_date"):
            if r.get(k) is not None:
                fails.append("%s should be None for %s" % (k, out))
    return (not fails), fails
