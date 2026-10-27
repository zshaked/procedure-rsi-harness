"""Holding-confirmation desk procedure (induced)."""

TOLERANCE = 0.10  # relative difference between client-stated qty and our (settled+pending) qty


def _out(outcome, account_id=None, instrument_id=None, as_of=None, as_of_assumed=False,
         settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": as_of_assumed, "settled": settled,
            "pending": pending, "pending_date": pending_date}


def respond(request, tools):
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()
    domain = sender.split("@")[-1] if "@" in sender else ""

    # 1. Sender must be a known contact with sufficient authority.
    contact = tools.get_contact(sender)
    if not contact or contact.get("auth_level", 0) < 2:
        return _out("REQUEST_AUTHORIZATION")
    # Sender must write from the domain of their own registered account (no personal mail).
    own = tools.lookup_account(contact.get("account_id") or "")
    if not own or own[0].get("domain", "").lower() != domain:
        return _out("REQUEST_AUTHORIZATION")

    # 2. Account must resolve uniquely.
    aref = f.get("account_ref")
    accs = tools.lookup_account(aref) if aref else []
    if len(accs) != 1:
        return _out("REQUEST_INFO")
    acc = accs[0]

    # 3. Sender must belong to that account, from the account's domain.
    if contact.get("account_id") != acc["id"] or acc.get("domain", "").lower() != domain:
        return _out("REQUEST_AUTHORIZATION")

    # 4. Instrument must resolve uniquely; date must be given.
    iref = f.get("instrument_ref")
    ins = tools.resolve_instrument(iref) if iref else []
    if len(ins) != 1:
        return _out("REQUEST_INFO")
    inst = ins[0]
    as_of = f.get("as_of")
    if not as_of:
        return _out("REQUEST_INFO")

    # 5. Position lookup.
    pos = tools.get_position(acc["id"], inst["id"], as_of)
    if not pos or not pos.get("settled"):
        return _out("NOT_HELD", acc["id"], inst["id"], as_of, False)

    settled = pos["settled"]
    pending = pos.get("pending") or 0
    stated = f.get("stated_qty")
    if stated is not None:
        ours = settled + pending
        if ours == 0 or abs(stated - ours) / ours > TOLERANCE:
            return _out("ESCALATE", acc["id"], inst["id"])

    if pending:
        return _out("CONFIRMED", acc["id"], inst["id"], as_of, False, settled, pending,
                    pos.get("pending_date"))
    return _out("CONFIRMED", acc["id"], inst["id"], as_of, False, settled)
