"""Induced procedure for the holdings-confirmation desk (P3)."""

LARGE_POSITION = 1_000_000      # settled at/above this -> escalate
PENDING_REPORT_MIN = 1_000      # report pending only when at least this large
QTY_TOLERANCE = 0.05            # stated vs settled relative difference tolerated


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": assumed, "settled": settled, "pending": pending, "pending_date": pdate}


def respond(request, tools):
    f = request.get("fields") or {}
    contact = tools.get_contact(request.get("from") or "")

    # 1. Requester must be a known contact with full authorization.
    if not contact or (contact.get("auth_level") or 0) < 3:
        return _out("REQUEST_AUTHORIZATION")

    # 2. Account and instrument must resolve uniquely.
    accs = tools.lookup_account(f["account_ref"]) if f.get("account_ref") else []
    if len(accs) != 1:
        return _out("REQUEST_INFO")
    acc = accs[0]["id"]

    # 3. Contact must belong to the account.
    if contact.get("account_id") != acc:
        return _out("REQUEST_AUTHORIZATION")

    insts = tools.resolve_instrument(f["instrument_ref"]) if f.get("instrument_ref") else []
    if len(insts) != 1:
        return _out("REQUEST_INFO")
    ins = insts[0]["id"]

    # 4. Date: default to the request date.
    as_of = f.get("as_of")
    assumed = False
    if not as_of:
        as_of, assumed = request.get("date"), True

    pos = tools.get_position(acc, ins, as_of)
    settled = pos["settled"] if pos else 0
    if settled <= 0:
        return _out("NOT_HELD", acc, ins, as_of, assumed)

    stated = f.get("stated_qty")
    if settled >= LARGE_POSITION or (stated is not None and abs(stated - settled) > QTY_TOLERANCE * settled):
        return _out("ESCALATE", acc, ins)

    pending, pdate = None, None
    if pos and pos["pending"] and pos["pending"] >= PENDING_REPORT_MIN:
        pending, pdate = pos["pending"], pos["pending_date"]
    return _out("CONFIRMED", acc, ins, as_of, assumed, settled, pending, pdate)
