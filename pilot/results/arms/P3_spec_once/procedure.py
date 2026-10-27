"""Holding-confirmation desk procedure, implementing spec.md (rules numbered as there)."""

LARGE_POSITION = 1_000_000      # rule 7
MISMATCH_TOLERANCE = 0.05       # rule 8 (relative to settled)
PENDING_REPORT_MIN = 1_000      # rule 10


def _out(outcome, account_id=None, instrument_id=None, as_of=None, as_of_assumed=False,
         settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": as_of_assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


def respond(request, tools):
    fields = request.get("fields") or {}
    sender = (request.get("from") or "").strip()

    # Rule 1: sender must be a known contact with auth level 3.
    contact = tools.get_contact(sender) if sender else None
    if not contact or (contact.get("auth_level") or 0) < 3:
        return _out("REQUEST_AUTHORIZATION")

    # Rule 2: account must resolve uniquely.
    acc_ref = fields.get("account_ref")
    accounts = tools.lookup_account(acc_ref) if acc_ref else []
    if len(accounts) != 1:
        return _out("REQUEST_INFO")
    account_id = accounts[0]["id"]

    # Rule 3: sender must belong to that account.
    if contact.get("account_id") != account_id:
        return _out("REQUEST_AUTHORIZATION")

    # Rule 4: instrument must resolve uniquely.
    ins_ref = fields.get("instrument_ref")
    instruments = tools.resolve_instrument(ins_ref) if ins_ref else []
    if len(instruments) != 1:
        return _out("REQUEST_INFO")
    instrument_id = instruments[0]["id"]

    # Rule 5: date (assume request date when none given).
    as_of = fields.get("as_of")
    assumed = not as_of
    if assumed:
        as_of = request.get("date")

    pos = tools.get_position(account_id, instrument_id, as_of)

    # Rule 6: not held.
    if not pos or not pos.get("settled"):
        return _out("NOT_HELD", account_id, instrument_id, as_of, assumed)

    settled = pos["settled"]

    # Rule 7: large positions go to escalation.
    if settled >= LARGE_POSITION:
        return _out("ESCALATE", account_id, instrument_id)

    # Rule 8: client's stated quantity outside tolerance -> escalation.
    stated = fields.get("stated_qty")
    if stated is not None and abs(stated - settled) > MISMATCH_TOLERANCE * settled:
        return _out("ESCALATE", account_id, instrument_id)

    # Rules 9-10: confirm; report pending only when material.
    pending = pos.get("pending") or 0
    if pending >= PENDING_REPORT_MIN:
        return _out("CONFIRMED", account_id, instrument_id, as_of, assumed, settled,
                    pending, pos.get("pending_date"))
    return _out("CONFIRMED", account_id, instrument_id, as_of, assumed, settled)
