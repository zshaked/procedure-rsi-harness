"""Induced procedure for the holding-confirmation desk (history-only arm)."""

TOLERANCE = 0.10  # stated qty may differ from our total by up to 10% before escalation


def _out(outcome, account_id=None, instrument_id=None, as_of=None, settled=None,
         pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id,
            "as_of": as_of, "as_of_assumed": False, "settled": settled,
            "pending": pending, "pending_date": pending_date}


def _domain(email):
    return email.rsplit("@", 1)[-1].lower().strip() if email and "@" in email else ""


def respond(request, tools):
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip()
    acc_ref = f.get("account_ref")
    ins_ref = f.get("instrument_ref")
    as_of = f.get("as_of")
    stated = f.get("stated_qty")

    # 1. Sender must be a known contact with sufficient authority, writing from
    #    the domain of the account it is registered to.
    contact = tools.get_contact(sender) if sender else None
    if not contact or (contact.get("auth_level") or 0) < 2:
        return _out("REQUEST_AUTHORIZATION")
    c_acc = tools.lookup_account(contact["account_id"])
    if not c_acc or c_acc[0].get("domain", "").lower() != _domain(sender):
        return _out("REQUEST_AUTHORIZATION")

    # 2. Account must resolve to exactly one account.
    accounts = tools.lookup_account(acc_ref) if acc_ref else []
    if len(accounts) != 1:
        return _out("REQUEST_INFO")
    account = accounts[0]

    # 3. The contact may only ask about its own account.
    if account["id"] != contact["account_id"]:
        return _out("REQUEST_AUTHORIZATION")

    # 4. Instrument and date must be unambiguous.
    instruments = tools.resolve_instrument(ins_ref) if ins_ref else []
    if len(instruments) != 1 or not as_of:
        return _out("REQUEST_INFO")
    instrument = instruments[0]
    if request.get("date") and as_of > request["date"]:
        return _out("REQUEST_INFO")

    pos = tools.get_position(account["id"], instrument["id"], as_of)
    if not pos or not pos.get("settled"):
        return _out("NOT_HELD", account["id"], instrument["id"], as_of)

    settled = pos["settled"]
    pending = pos.get("pending") or 0
    total = settled + pending
    if stated is not None:
        base = max(total, 1)
        if abs(stated - total) / base > TOLERANCE:
            return _out("ESCALATE", account["id"], instrument["id"])

    if pending:
        return _out("CONFIRMED", account["id"], instrument["id"], as_of, settled,
                    pending, pos.get("pending_date"))
    return _out("CONFIRMED", account["id"], instrument["id"], as_of, settled)
