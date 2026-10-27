"""Holding-confirmation desk procedure. Deterministic; uses only `tools`.

Order of checks (see verifier.py for evidence and oracle calibration):
 1. Sender must be a known contact with auth level >= 3 and, when the account reference resolves to
    exactly one account, linked to that account            -> else REQUEST_AUTHORIZATION
 2. Account must resolve to exactly one account and the instrument to exactly one instrument
                                                             -> else REQUEST_INFO
 3. as_of = requested date, or the request date (as_of_assumed=True) when none was given
 4. Never held / zero settled                                -> NOT_HELD
 5. Settled >= 1,000,000, or client's stated qty differs from settled by more than 5%
                                                             -> ESCALATE
 6. Otherwise CONFIRMED with settled; report pending (and its date) only when pending >= 1,000.
"""

MIN_AUTH = 3
LARGE_SETTLED = 1_000_000
QTY_TOL = 0.05
PENDING_MIN = 1000


def respond(request: dict, tools) -> dict:
    f = request.get("fields") or {}
    r = {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}

    sender = (request.get("from") or "").strip().lower()
    contact = tools.get_contact(sender) if sender else None
    aref, iref = f.get("account_ref"), f.get("instrument_ref")
    accs = tools.lookup_account(aref) if aref else []
    ins = tools.resolve_instrument(iref) if iref else []

    # 1. authorization gate
    if contact is None or (contact.get("auth_level") or 0) < MIN_AUTH:
        r["outcome"] = "REQUEST_AUTHORIZATION"
        return r
    if len(accs) == 1 and contact.get("account_id") != accs[0]["id"]:
        r["outcome"] = "REQUEST_AUTHORIZATION"
        return r

    # 2. completeness / unambiguity
    if len(accs) != 1 or len(ins) != 1:
        r["outcome"] = "REQUEST_INFO"
        return r

    acc_id, ins_id = accs[0]["id"], ins[0]["id"]
    as_of = f.get("as_of")
    assumed = not as_of
    if assumed:
        as_of = request.get("date")
    r.update(account_id=acc_id, instrument_id=ins_id)

    pos = tools.get_position(acc_id, ins_id, as_of or "")

    # 4. not held
    if not pos or not pos["settled"]:
        r.update(outcome="NOT_HELD", as_of=as_of, as_of_assumed=assumed)
        return r

    # 5. escalation
    settled = pos["settled"]
    sq = f.get("stated_qty")
    if settled >= LARGE_SETTLED or (sq is not None and abs(sq - settled) > QTY_TOL * settled):
        r["outcome"] = "ESCALATE"
        return r

    # 6. confirm
    r.update(outcome="CONFIRMED", as_of=as_of, as_of_assumed=assumed, settled=settled)
    if pos["pending"] and pos["pending"] >= PENDING_MIN:
        r.update(pending=pos["pending"], pending_date=pos["pending_date"])
    return r
