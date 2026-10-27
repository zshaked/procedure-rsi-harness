"""Holding-confirmation desk procedure (implements spec.md)."""

TOLERANCE = 0.10


def _base():
    return {"outcome": None, "account_id": None, "instrument_id": None, "as_of": None,
            "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}


def _out(outcome, **kw):
    r = _base()
    r["outcome"] = outcome
    r.update(kw)
    return r


def respond(request, tools):
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()

    # Rule 1: known contact with auth_level >= 2
    contact = tools.get_contact(sender) if sender else None
    if not contact or (contact.get("auth_level") or 0) < 2:
        return _out("REQUEST_AUTHORIZATION")

    # Rule 2: sender must write from the client's own domain
    dom = sender.split("@", 1)[1] if "@" in sender else ""
    own = tools.lookup_account(contact["account_id"])
    own_dom = own[0]["domain"].lower() if len(own) == 1 else None
    if dom != own_dom:
        return _out("REQUEST_AUTHORIZATION")

    # Rule 3: account must resolve uniquely
    ref = f.get("account_ref")
    cands = tools.lookup_account(ref) if ref else []
    if len(cands) != 1:
        return _out("REQUEST_INFO")
    acc = cands[0]
    # Rule 4: contact must belong to that account
    if acc["id"] != contact["account_id"]:
        return _out("REQUEST_AUTHORIZATION")

    # Rule 5: instrument must resolve uniquely
    iref = f.get("instrument_ref")
    ins = tools.resolve_instrument(iref) if iref else []
    if len(ins) != 1:
        return _out("REQUEST_INFO")
    iid = ins[0]["id"]

    # Rule 6: explicit as_of required
    as_of = f.get("as_of")
    if not as_of:
        return _out("REQUEST_INFO")

    # Rule 7: not held
    p = tools.get_position(acc["id"], iid, as_of)
    if not p or not p.get("settled"):
        return _out("NOT_HELD", account_id=acc["id"], instrument_id=iid, as_of=as_of)

    settled = p["settled"]
    pending = p.get("pending") or 0

    # Rule 8: stated quantity mismatch vs settled + pending
    sq = f.get("stated_qty")
    if sq is not None:
        total = settled + pending
        if total <= 0 or abs(sq - total) / total > TOLERANCE:
            return _out("ESCALATE", account_id=acc["id"], instrument_id=iid)

    # Rule 9: confirm
    r = _out("CONFIRMED", account_id=acc["id"], instrument_id=iid, as_of=as_of, settled=settled)
    if pending > 0:
        r["pending"] = pending
        r["pending_date"] = p.get("pending_date")
    return r
