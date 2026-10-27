"""Reference-free verifier for holding-confirmation responses.

verify(request, response, tools) -> (ok, failures)

Each check below is an independent condition a correct response must satisfy, derived from the
history (evidence case_ids cited) and calibrated with the oracle (every question/answer in oracle_log.jsonl).
It never needs a reference reply: everything is recomputed from the request and the system of record.
"""

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}
MIN_AUTH = 3                 # contacts below this level cannot get a confirmation
LARGE_SETTLED = 1_000_000    # settled positions at/above this are escalated
QTY_TOL = 0.05               # relative tolerance between client's stated qty and our settled qty
                             # oracle: 2% ok (P3-0144), 4% ok (P3-0126, P3-0115), 8% escalate (P3-0112)
PENDING_MIN = 1000           # pending settlements at/above this size are reported (below: omitted)


def _facts(request, tools):
    """Derive the facts the desk looks at. Returns dict; never raises."""
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()
    contact = tools.get_contact(sender) if sender else None
    aref, iref = f.get("account_ref"), f.get("instrument_ref")
    accs = tools.lookup_account(aref) if aref else []
    ins = tools.resolve_instrument(iref) if iref else []
    as_of = f.get("as_of")
    eff = as_of or request.get("date")
    pos = None
    if len(accs) == 1 and len(ins) == 1 and eff:
        pos = tools.get_position(accs[0]["id"], ins[0]["id"], eff)
    return dict(contact=contact, accs=accs, ins=ins, as_of=as_of, eff=eff,
                assumed=as_of is None, pos=pos, sq=f.get("stated_qty"))


def expected_outcome(request, tools):
    """The decision the checklist implies (used by the checks below; exposed for tooling)."""
    x = _facts(request, tools)
    c, accs, ins = x["contact"], x["accs"], x["ins"]
    # CHECK-A  authorization gate first: unknown sender or auth level < 3 -> REQUEST_AUTHORIZATION,
    #          even when the request is also incomplete/ambiguous.
    #          evidence: P3-0021, P3-0033, P3-0008, P3-0011, P3-0018, P3-0058, P3-0098
    #          (contra, treated as operator mistakes: P3-0032, P3-0056, P3-0067, P3-0199)
    #          oracle: P3-0199 CONFIRMED rejected; P3-0032, P3-0056 REQUEST_AUTHORIZATION accepted
    if c is None or c.get("auth_level", 0) < MIN_AUTH:
        return "REQUEST_AUTHORIZATION"
    # CHECK-B  sender's contact must belong to the (uniquely) referenced account, else
    #          REQUEST_AUTHORIZATION. evidence: P3-0000, P3-0002, P3-0003, P3-0048, P3-0159, P3-0113
    #          (contra: P3-0012, P3-0042, P3-0147, P3-0163)
    #          oracle: P3-0147, P3-0012 REQUEST_AUTHORIZATION accepted
    if len(accs) == 1 and c["account_id"] != accs[0]["id"]:
        return "REQUEST_AUTHORIZATION"
    # CHECK-C  account must resolve to exactly one account, instrument present and unique,
    #          else REQUEST_INFO. evidence: P3-0009, P3-0046, P3-0133 (ambiguous account),
    #          P3-0031, P3-0063, P3-0091 (no instrument)  (contra: P3-0120, P3-0166)
    #          oracle: P3-0166 INFO accepted; P3-0133, P3-0120 AUTH rejected ("can't tell which account")
    #          (P3-0120 INFO was also rejected once with a vague reason -- treated as oracle noise)
    if len(accs) != 1 or len(ins) != 1:
        return "REQUEST_INFO"
    p = x["pos"]
    # CHECK-D  never held, or zero settled -> NOT_HELD (takes precedence over qty mismatch).
    #          evidence: P3-0007, P3-0051, P3-0087, P3-0143, P3-0154, P3-0070  (contra: P3-0004)
    #          oracle: P3-0004 NOT_HELD accepted
    if not p or not p["settled"]:
        return "NOT_HELD"
    # CHECK-E  large settled position -> ESCALATE, even when stated qty matches.
    #          evidence: P3-0013, P3-0026, P3-0061, P3-0150, P3-0155, P3-0167
    #          (contra: P3-0010, P3-0069)
    #          oracle: P3-0010 CONFIRMED rejected ("that size always goes to escalation"); P3-0069 ESCALATE accepted
    if p["settled"] >= LARGE_SETTLED:
        return "ESCALATE"
    # CHECK-F  client's stated quantity disagrees with our settled quantity -> ESCALATE.
    #          evidence: P3-0076, P3-0092, P3-0107, P3-0115, P3-0164, P3-0112, P3-0037
    #          (contra: P3-0027; P3-0126/P3-0144 are within tolerance)
    #          oracle: P3-0099 (no date, small pending) CONFIRMED accepted -> its ESCALATE was a mistake
    sq = x["sq"]
    if sq is not None and abs(sq - p["settled"]) > QTY_TOL * p["settled"]:
        return "ESCALATE"
    return "CONFIRMED"


def verify(request: dict, response: dict, tools):
    fails = []
    if not isinstance(response, dict):
        return False, ["response is not a dict"]
    out = response.get("outcome")
    # CHECK-0  outcome is one of the five allowed values.
    if out not in OUTCOMES:
        return False, [f"invalid outcome {out!r}"]

    x = _facts(request, tools)
    exp = expected_outcome(request, tools)
    # CHECK-1  decision matches the checklist A..F.
    if out != exp:
        fails.append(f"outcome {out} but checklist implies {exp}")

    acc_id = x["accs"][0]["id"] if len(x["accs"]) == 1 else None
    ins_id = x["ins"][0]["id"] if len(x["ins"]) == 1 else None
    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        # CHECK-2  account/instrument identified with the system-of-record ids (README contract;
        #          replies quote ACC ids / tickers, e.g. P3-0010, P3-0007). oracle: P3-0076 ESCALATE w/o ids rejected
        if response.get("account_id") != acc_id:
            fails.append(f"account_id {response.get('account_id')} != {acc_id}")
        if response.get("instrument_id") != ins_id:
            fails.append(f"instrument_id {response.get('instrument_id')} != {ins_id}")
    if out in ("CONFIRMED", "NOT_HELD"):
        # CHECK-3  as_of is the requested date, or the request date when none was given, and
        #          as_of_assumed says which. evidence: P3-0070, P3-0177 ("As no date was given...")
        #          oracle: P3-0070 with as_of_assumed=false rejected ("If you assumed the date, say so")
        if response.get("as_of") != x["eff"]:
            fails.append(f"as_of {response.get('as_of')} != {x['eff']}")
        if bool(response.get("as_of_assumed")) != x["assumed"]:
            fails.append(f"as_of_assumed should be {x['assumed']}")
    if out == "CONFIRMED":
        p = tools.get_position(acc_id, ins_id, x["eff"]) if acc_id and ins_id else None
        # CHECK-4  settled equals the system of record as of the effective date (every CONFIRMED reply).
        if not p or response.get("settled") != p["settled"]:
            fails.append(f"settled {response.get('settled')} != {p and p['settled']}")
        # CHECK-5  pending is reported (with its date) iff it is material (>= PENDING_MIN);
        #          small pending amounts are left out.
        #          evidence reported: P3-0034, P3-0060, P3-0072, P3-0088, P3-0160
        #          evidence omitted: P3-0038 (884), P3-0110 (54), P3-0137 (541), P3-0069 (11)
        #          oracle: P3-0038 reporting 884 rejected; P3-0160 omitting 6187 rejected
        if p:
            want = p["pending"] if p["pending"] >= PENDING_MIN else 0
            got = response.get("pending") or 0
            if got != want:
                fails.append(f"pending {got} should be {want}")
            elif want and response.get("pending_date") != p["pending_date"]:
                fails.append(f"pending_date {response.get('pending_date')} != {p['pending_date']}")
            elif not want and response.get("pending_date"):
                fails.append("pending_date given without a reported pending amount")
    else:
        # CHECK-6  settled/pending only appear on a confirmation (non-confirmations disclose nothing).
        if response.get("settled") is not None or response.get("pending"):
            fails.append("quantities disclosed on a non-CONFIRMED response")
    return (not fails), fails
