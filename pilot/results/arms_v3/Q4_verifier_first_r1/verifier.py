"""Reference-free verifier for the holding-confirmation desk.

verify(request, response, tools) -> (ok: bool, failures: list[str])

Each check below is independent and commented with the evidence it rests on
(H = history case, U = unlabeled case, O = oracle answer, see NOTES.md).
The verifier never looks at a reply; it recomputes what the desk's rules imply
from the request and the system of record and checks the response against it.
"""
import re
import datetime as dt

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
             "proton.me", "protonmail.com", "live.com", "msn.com", "mail.com", "gmx.com"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# Calibrated settings (see NOTES.md for the oracle answers behind each).
CFG = {
    # O3/O4/O5: client figure is compared with settled+pending; 7-8% off is fine (O2, O3), 15% off escalates
    # (H Q4-0001/0003/0024), matching settled-only while pending exists escalates (O5).
    "tolerance": 0.10,
    "compare_incl_pending": True,
    "min_level": 2,               # H Q4-0011 level 1 -> AUTH; level 2 confirms (H Q4-0012/0013/0015/0021)
    "infer_account_from_entitlement": False,   # O9: "our account" without naming it -> REQUEST_INFO
    "future_date": "REQUEST_INFO",             # O13
    "legal_hold": "ESCALATE",                  # O11; O15: authorization is checked before legal hold
    "no_email_confirm": None,                  # O12: "fine to confirm" -> flag does not change the outcome
    "zero_with_claim": "NOT_HELD",             # O14
    "assumed_when_rolled": False,  # O1 (weekend roll), O7 (yesterday), O8 (month-end): as_of_assumed False
}


# ----------------------------------------------------------------- parsing helpers
def _date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def _clean_body(body):
    out = []
    for line in (body or "").split("\n"):
        s = line.strip()
        if re.match(r"^-+\s*(forwarded|original) message", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|cc|subject):", s, re.I):
            continue
        if s.lower().startswith("this email and any attachments"):
            continue
        out.append(line)
    return "\n".join(out)


def parse_date(body, sent):
    """(date|None, kind) where kind is 'explicit', 'relative' or None."""
    s = dt.date.fromisoformat(sent)
    b = _clean_body(body)
    low = b.lower()
    if re.search(r"\b(month[- ]?end|end of (the )?(last|previous|prior) month|end of month|"
                 r"last day of (the )?(last|previous|prior) month|last month[- ]end)\b", low):
        return s.replace(day=1) - dt.timedelta(days=1), "relative"
    if re.search(r"\byesterday\b", low):
        return s - dt.timedelta(days=1), "relative"
    if re.search(r"\b(today|close of business today|cob today)\b", low):
        return s, "relative"
    m = re.search(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b", b)
    if m:
        return _date(*m.groups()), "explicit"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d|\d\d)\b", b)
    if m:
        y = m.group(3)
        y = "20" + y if len(y) == 2 else y
        return _date(y, m.group(1), m.group(2)), "explicit"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\.?[- ,]+(20\d\d)\b", b)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _date(m.group(3), MONTHS[m.group(2)[:3].lower()], m.group(1)), "explicit"
    m = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (20\d\d)\b", b)
    if m and m.group(1)[:3].lower() in MONTHS:
        return _date(m.group(3), MONTHS[m.group(1)[:3].lower()], m.group(2)), "explicit"
    # day + month without a year: the desk has to assume the year (most recent such date not after sent)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,9})\b", b)
    mm = re.search(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?\b", b)
    for g in ((m.group(2), m.group(1)) if m else None, (mm.group(1), mm.group(2)) if mm else None):
        if g and g[0][:3].lower() in MONTHS and (len(g[0]) == 3 or g[0].lower().startswith(
                ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                 "october", "november", "december"][MONTHS[g[0][:3].lower()] - 1])):
            for y in (s.year, s.year - 1):
                c = _date(y, MONTHS[g[0][:3].lower()], g[1])
                if c and c < s:
                    return c, "assumed"
    return None, None


def parse_qty(x):
    x = x.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    for suf, mu in (("mm", 10 ** 6), ("mn", 10 ** 6), ("bn", 10 ** 9), ("m", 10 ** 6), ("k", 10 ** 3)):
        if x.endswith(suf):
            mult, x = mu, x[: -len(suf)]
            break
    try:
        return int(round(float(x) * mult))
    except Exception:
        return None


_Q = r"(\d[\d,]*(?:\.\d+)?\s?(?:mm|mn|bn|k|m)?)(?![\w-])"
_QPATS = [r"records show\s+" + _Q, r"figure is\s+" + _Q, r"we have\s+" + _Q, r"we show\s+" + _Q,
          r"books (?:show|have)\s+" + _Q, r"we hold\s+" + _Q, r"we (?:expect|see)\s+" + _Q,
          r"(?:balance|position|figure|holding) of\s+" + _Q]


def parse_client_qty(body):
    b = _clean_body(body)
    for p in _QPATS:
        m = re.search(p, b, re.I)
        if m:
            return parse_qty(m.group(1))
    return None


def _clean_mention(t):
    if not t:
        return None
    t = t.strip().strip(".,;:()\"'")
    t = re.sub(r"^(our |the )?(account|acct|a/c|fund|portfolio)\s+", "", t, flags=re.I)
    return t.strip() or None


# ----------------------------------------------------------------- derivation
def derive(request, tools, cfg=CFG):
    """Everything the checks need, computed from request + tools only."""
    d = {}
    sender = (request.get("from") or "").strip().lower()
    d["domain"] = sender.split("@")[-1] if "@" in sender else ""
    d["sent"] = request.get("sent")
    contact = tools.get_contact(sender) if sender else None
    d["ents"] = tools.get_entitlements(contact["contact_id"]) if contact else []
    m = request.get("mentions") or {}
    at, it = _clean_mention(m.get("account_text")), _clean_mention(m.get("instrument_text"))
    d["accs"] = tools.search_accounts(at) if at else []
    d["inss"] = tools.search_instruments(it) if it else []
    d["account_mentioned"] = bool(at)
    if not at and cfg["infer_account_from_entitlement"]:
        live = [e for e in d["ents"] if e["expires"] >= d["sent"]]
        if len(live) == 1:
            a = tools.get_account(live[0]["account_id"])
            d["accs"] = [{"id": a["id"], "name": a["name"], "short_name": a["short_name"]}]
    d["acc"] = d["accs"][0]["id"] if len(d["accs"]) == 1 else None
    d["ins"] = d["inss"][0]["id"] if len(d["inss"]) == 1 else None
    raw, kind = parse_date(request.get("body", ""), d["sent"])
    d["date_raw"], d["date_kind"] = raw, kind
    d["client_qty"] = parse_client_qty(request.get("body", ""))
    d["profile"] = tools.get_client_profile(d["acc"]) if d["acc"] else None
    ent = [e for e in d["ents"] if d["acc"] and e["account_id"] == d["acc"]]
    d["ent"] = max(ent, key=lambda e: (e["expires"] >= d["sent"], e["level"])) if ent else None
    d["as_of"] = None
    if raw:
        cal = tools.get_calendar(raw.isoformat())
        d["as_of"] = raw.isoformat() if cal["business_day"] else cal["previous_business_day"]
    d["settled"] = d["pending"] = d["pending_date"] = None
    if d["acc"] and d["ins"] and d["as_of"]:
        splits = tools.get_corporate_actions(d["ins"])
        q = 0
        for t in tools.get_ledger(d["acc"], d["ins"]):
            if t["date"] <= d["as_of"]:
                mult = 1
                for s in splits:
                    if t["date"] < s["date"] <= d["as_of"]:
                        mult *= s["ratio"]
                q += t["qty"] * mult
        d["settled"] = q
        xs = [x for x in tools.get_instructions(d["acc"], d["ins"])
              if x["status"] == "matched" and x["settle_date"] > d["as_of"]]
        if xs:
            d["pending"] = sum(x["qty"] for x in xs)
            d["pending_date"] = max(x["settle_date"] for x in xs)
    return d


def expected_outcome(d, cfg=CFG):
    """The gate order the checks encode. Returns (outcome, reason)."""
    # free-mail sender: never confirm (H Q4-0008 entitled L3 gmail -> AUTH; H Q4-0009)
    if d["domain"] in FREE_MAIL:
        return "REQUEST_AUTHORIZATION", "free-mail sender"
    # account must resolve to exactly one (H Q4-0002, Q4-0017, Q4-0022 ambiguous -> INFO)
    if len(d["accs"]) != 1:
        return "REQUEST_INFO", "account missing/ambiguous"
    prof = d["profile"] or {}
    ent = d["ent"]
    # sender domain must be one of the client's domains (H Q4-0004/0005/0018/0020)
    if d["domain"] not in prof.get("domains", []):
        return "REQUEST_AUTHORIZATION", "domain not on client profile"
    # live entitlement with sufficient level (H Q4-0011 level 1 -> AUTH; level 2 confirms H Q4-0012)
    if not ent or ent["expires"] < d["sent"] or ent["level"] < cfg["min_level"]:
        return "REQUEST_AUTHORIZATION", "no live entitlement of sufficient level"
    if prof.get("no_email_confirm") and cfg["no_email_confirm"]:
        return cfg["no_email_confirm"], "client does not allow email confirmation"
    # legal hold escalates once the sender is authorised (O11, O15)
    if prof.get("legal_hold"):
        return cfg["legal_hold"], "legal hold"
    # instrument / date needed (H Q4-0014, Q4-0016 no date -> INFO)
    if not d["ins"]:
        return "REQUEST_INFO", "instrument missing/ambiguous"
    if not d["date_raw"]:
        return "REQUEST_INFO", "date missing"
    if d["date_raw"].isoformat() >= d["sent"]:
        return cfg["future_date"], "date not in the past"
    s, c = d["settled"], d["client_qty"]
    if s == 0:
        if c:
            return cfg["zero_with_claim"], "nothing held but client claims a figure"
        return "NOT_HELD", "nothing held"
    if s is not None and s < 0:
        return "ESCALATE", "negative position"
    if c is not None:
        base = s + (d["pending"] or 0) if cfg["compare_incl_pending"] else s
        if abs(c - base) > cfg["tolerance"] * abs(base):
            return "ESCALATE", "client figure disagrees"
    return "CONFIRMED", "ok"


# ----------------------------------------------------------------- the checklist
def verify(request, response, tools, cfg=CFG):
    fails = []
    r = response or {}
    out = r.get("outcome")

    # C1 schema: outcome is one of the five; types are right.
    if out not in OUTCOMES:
        return False, ["C1 outcome not in enum"]
    for k in ("account_id", "instrument_id", "as_of", "pending_date"):
        if r.get(k) is not None and not isinstance(r.get(k), str):
            fails.append("C1 %s not str/None" % k)
    for k in ("settled", "pending"):
        if r.get(k) is not None and (isinstance(r.get(k), bool) or not isinstance(r.get(k), int)):
            fails.append("C1 %s not int/None" % k)

    d = derive(request, tools, cfg)
    exp, why = expected_outcome(d, cfg)

    # C2 free-mail sender -> REQUEST_AUTHORIZATION (H Q4-0008, Q4-0009).
    if d["domain"] in FREE_MAIL and out != "REQUEST_AUTHORIZATION":
        fails.append("C2 free-mail sender must get REQUEST_AUTHORIZATION")
    # C3 account must resolve uniquely before anything is disclosed (H Q4-0002/0017/0022).
    if exp == "REQUEST_INFO" and why.startswith("account") and out != "REQUEST_INFO":
        fails.append("C3 unresolved account must get REQUEST_INFO")
    # C4 authorization: sender domain on profile + live entitlement level>=2 (H Q4-0004/05/11/18/20).
    if exp == "REQUEST_AUTHORIZATION" and out != "REQUEST_AUTHORIZATION":
        fails.append("C4 sender not authorised (%s)" % why)
    if out == "REQUEST_AUTHORIZATION" and exp != "REQUEST_AUTHORIZATION":
        fails.append("C4b authorization requested although sender is authorised (expected %s)" % exp)
    # C5 missing instrument/date or future date -> REQUEST_INFO (H Q4-0014, Q4-0016).
    if exp == "REQUEST_INFO" and not why.startswith("account") and out != "REQUEST_INFO":
        fails.append("C5 %s must get REQUEST_INFO" % why)
    if out == "REQUEST_INFO" and exp != "REQUEST_INFO":
        fails.append("C5b asked for info although request is complete (expected %s)" % exp)
    # C6 legal hold / no-email-confirm / disagreement -> ESCALATE (H Q4-0001/0003/0019/0024).
    if exp == "ESCALATE" and out != "ESCALATE":
        fails.append("C6 must ESCALATE (%s)" % why)
    if out == "ESCALATE" and exp != "ESCALATE":
        fails.append("C6b escalated without cause (expected %s)" % exp)
    # C7 zero holding -> NOT_HELD; positive -> never NOT_HELD.
    if exp == "NOT_HELD" and out != "NOT_HELD":
        fails.append("C7 nothing held: must be NOT_HELD")
    if out == "NOT_HELD" and exp != "NOT_HELD":
        fails.append("C7b NOT_HELD but expected %s" % exp)
    if exp == "CONFIRMED" and out != "CONFIRMED":
        fails.append("C8 should be CONFIRMED (got %s)" % out)

    # C9 identifiers for CONFIRMED / NOT_HELD / ESCALATE (README; H replies name ACC id + ticker).
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        if r.get("account_id") != d["acc"]:
            fails.append("C9 account_id should be %s" % d["acc"])
        if r.get("instrument_id") != d["ins"]:
            fails.append("C9 instrument_id should be %s" % d["ins"])
    # C10 as_of = stated date rolled back to the previous business day
    #     (H Q4-0006 Sat->Fri, Q4-0013 Sun->Fri, Q4-0012 month-end Sat->Fri, Q4-0024).
    if out in ("CONFIRMED", "NOT_HELD"):
        if r.get("as_of") != d["as_of"]:
            fails.append("C10 as_of should be %s" % d["as_of"])
        exp_assumed = (d["date_kind"] == "assumed") or bool(
            cfg["assumed_when_rolled"] and d["date_raw"] and d["as_of"] != d["date_raw"].isoformat())
        if bool(r.get("as_of_assumed")) != exp_assumed:
            fails.append("C10b as_of_assumed should be %s" % exp_assumed)
    # C11 settled = ledger summed over ALL custody sub-accounts, split-adjusted to as_of
    #     (H Q4-0006/0007/0010 multi-sub-account sums; Q4-0019 split x3; get_position_summary is primary-only).
    if out == "CONFIRMED" and r.get("settled") != d["settled"]:
        fails.append("C11 settled should be %s" % d["settled"])
    # C12 pending = matched instructions settling after as_of, summed, dated by the last one; not split-adjusted
    #     (H Q4-0013 79+38071=38150 @04-05; Q4-0021 690 unadjusted; Q4-0010 unmatched ignored).
    if out == "CONFIRMED":
        if r.get("pending") != d["pending"]:
            fails.append("C12 pending should be %s" % d["pending"])
        if r.get("pending_date") != d["pending_date"]:
            fails.append("C12 pending_date should be %s" % d["pending_date"])
    return (not fails), fails
