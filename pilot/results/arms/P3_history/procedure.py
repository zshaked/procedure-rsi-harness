"""Induced procedure for holding-confirmation requests (history-only arm)."""

LARGE_POSITION = 1_000_000   # settled at/above this -> escalate for review
PENDING_REPORT_MIN = 1_000   # pending settlements below this are not mentioned
REQUIRED_AUTH = 3


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pending_date}


def respond(request, tools):
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()

    # 1. Sender must be a known contact with full authorization.
    contact = tools.get_contact(sender) if sender else None
    if not contact or (contact.get("auth_level") or 0) < REQUIRED_AUTH:
        return _out("REQUEST_AUTHORIZATION")

    # 2. Account must resolve uniquely.
    accs = tools.lookup_account(f["account_ref"]) if f.get("account_ref") else []
    if len(accs) != 1:
        return _out("REQUEST_INFO")
    acc = accs[0]["id"]

    # 3. Contact may only ask about its own account.
    if contact.get("account_id") != acc:
        return _out("REQUEST_AUTHORIZATION")

    # 4. Instrument must resolve uniquely.
    ins_list = tools.resolve_instrument(f["instrument_ref"]) if f.get("instrument_ref") else []
    if len(ins_list) != 1:
        return _out("REQUEST_INFO")
    ins = ins_list[0]["id"]

    # 5. Date: given, or the request date (flagged as assumed).
    as_of = f.get("as_of")
    assumed = False
    if not as_of:
        as_of, assumed = request.get("date"), True

    pos = tools.get_position(acc, ins, as_of)
    if not pos or not pos.get("settled"):
        return _out("NOT_HELD", acc, ins, as_of, assumed)

    settled = pos["settled"]
    stated = f.get("stated_qty")
    if settled >= LARGE_POSITION or (stated is not None and stated != settled):
        return _out("ESCALATE", acc, ins)

    pending = pos.get("pending") or 0
    if pending >= PENDING_REPORT_MIN:
        return _out("CONFIRMED", acc, ins, as_of, assumed, settled, pending, pos.get("pending_date"))
    return _out("CONFIRMED", acc, ins, as_of, assumed, settled)
