"""Desk procedure for holding-confirmation requests (implements policy.txt)."""


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()

    # Rule 1 (and 3): authorization checked before resolving the account.
    contact = tools.get_contact(sender) if sender else None
    if not contact or (contact.get("auth_level") or 0) < 3:
        return _out("REQUEST_AUTHORIZATION")

    # Rule 4: resolve account.
    acc_ref = f.get("account_ref")
    accs = tools.lookup_account(acc_ref) if acc_ref else []
    if len(accs) != 1:
        return _out("REQUEST_INFO")
    acc = accs[0]

    # Rule 2: contact must belong to that account.
    if contact.get("account_id") != acc["id"]:
        return _out("REQUEST_AUTHORIZATION")

    # Rule 5: instrument.
    ins_ref = f.get("instrument_ref")
    ins = tools.resolve_instrument(ins_ref) if ins_ref else []
    if len(ins) != 1:
        return _out("REQUEST_INFO")
    inst = ins[0]

    # Rule 6: as-of date.
    as_of = f.get("as_of")
    assumed = False
    if not as_of:
        as_of = request.get("date")
        assumed = True

    # Rule 7: settled position.
    pos = tools.get_position(acc["id"], inst["id"], as_of)
    if not pos or not pos.get("settled"):
        return _out("NOT_HELD", account_id=acc["id"], instrument_id=inst["id"],
                    as_of=as_of, as_of_assumed=assumed)
    settled = pos["settled"]

    # Rule 8: stated quantity mismatch > 5%.
    stated = f.get("stated_qty")
    if stated is not None and abs(stated - settled) > 0.05 * settled:
        return _out("ESCALATE", account_id=acc["id"], instrument_id=inst["id"])

    # Rule 9: large positions.
    if settled > 1_000_000:
        return _out("ESCALATE", account_id=acc["id"], instrument_id=inst["id"])

    # Rule 10: confirm; report pending only if > 1,000.
    r = _out("CONFIRMED", account_id=acc["id"], instrument_id=inst["id"], as_of=as_of,
             as_of_assumed=assumed, settled=settled)
    if (pos.get("pending") or 0) > 1000:
        r["pending"] = pos["pending"]
        r["pending_date"] = pos["pending_date"]
    return r
