"""Desk procedure for holding-confirmation requests, per policy.txt."""


def _out(outcome, **kw):
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
         "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
    r.update(kw)
    return r


def respond(request, tools):
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()

    # Rules 1 and 3: authorization checked before resolving the account (rule 4).
    contact = tools.get_contact(sender) if sender else None
    if not contact or (contact.get("auth_level") or 0) < 2:
        return _out("REQUEST_AUTHORIZATION")
    home = tools.lookup_account(contact.get("account_id") or "")
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    if len(home) != 1 or sender_domain != (home[0].get("domain") or "").lower():
        return _out("REQUEST_AUTHORIZATION")

    # Rule 4: account resolution.
    ref = f.get("account_ref")
    accts = tools.lookup_account(ref) if ref else []
    if len(accts) != 1:
        return _out("REQUEST_INFO")
    acct = accts[0]

    # Rule 2: contact must belong to the account asked about.
    if contact.get("account_id") != acct["id"]:
        return _out("REQUEST_AUTHORIZATION")
    # Rule 3 against the account asked about (same account by now; kept for clarity).
    if sender_domain != (acct.get("domain") or "").lower():
        return _out("REQUEST_AUTHORIZATION")

    # Rule 5: instrument.
    iref = f.get("instrument_ref")
    ins = tools.resolve_instrument(iref) if iref else []
    if len(ins) != 1:
        return _out("REQUEST_INFO")
    inst = ins[0]

    # Rule 6: as-of date.
    as_of = f.get("as_of")
    if not as_of:
        return _out("REQUEST_INFO")

    # Rule 7: settled position.
    pos = tools.get_position(acct["id"], inst["id"], as_of)
    if not pos or (pos.get("settled") or 0) <= 0:
        return _out("NOT_HELD", account_id=acct["id"], instrument_id=inst["id"], as_of=as_of)

    settled, pending = pos["settled"], pos.get("pending") or 0

    # Rule 8: stated quantity check against settled + pending.
    stated = f.get("stated_qty")
    if stated is not None:
        total = settled + pending
        if abs(stated - total) > 0.10 * total:
            return _out("ESCALATE", account_id=acct["id"], instrument_id=inst["id"])

    # Rule 10: confirm.
    r = _out("CONFIRMED", account_id=acct["id"], instrument_id=inst["id"], as_of=as_of, settled=settled)
    if pending > 0:
        r["pending"] = pending
        r["pending_date"] = pos.get("pending_date")
    return r
