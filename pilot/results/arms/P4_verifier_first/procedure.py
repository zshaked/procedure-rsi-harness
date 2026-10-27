"""Holdings-confirmation desk procedure. Deterministic; uses only `tools` and the standard library.

Gate order (selected by search against verifier.py, see NOTES.md):
  1 sender      unknown contact, auth_level < 2, or writing from a non-firm / free-mail domain -> REQUEST_AUTHORIZATION
  2 account     account_ref must resolve to exactly one account (no disambiguation via sender) -> REQUEST_INFO
  3 entitlement sender domain == account domain and contact.account_id == account          -> REQUEST_AUTHORIZATION
  4 details     instrument resolves to exactly one, and as_of present (never assumed)      -> REQUEST_INFO
  5 position    never held, or zero settled with nothing pending                           -> NOT_HELD
  6 stated qty  |stated - (settled + pending)| / (settled + pending) > 10%                 -> ESCALATE
  7 otherwise   CONFIRMED with settled as of as_of; pending + date when settling after as_of
"""

FREE_MAIL = {"gmail.com", "outlook.com", "proton.me", "protonmail.com", "yahoo.com", "hotmail.com",
             "icloud.com", "aol.com", "live.com", "msn.com", "gmx.com", "mail.com"}
QTY_TOLERANCE = 0.10


def _resp(outcome, account_id=None, instrument_id=None, as_of=None, settled=None, pending=None, pending_date=None):
    return {"outcome": outcome, "account_id": account_id, "instrument_id": instrument_id, "as_of": as_of,
            "as_of_assumed": False, "settled": settled, "pending": pending, "pending_date": pending_date}


def respond(request, tools):
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()
    dom = sender.split("@")[-1] if "@" in sender else ""

    # 1 sender gate
    contact = tools.get_contact(sender) if sender else None
    if contact is None or (contact.get("auth_level") or 0) < 2 or dom in FREE_MAIL:
        return _resp("REQUEST_AUTHORIZATION")
    home = tools.lookup_account(contact.get("account_id") or "")
    if len(home) == 1 and home[0].get("domain") != dom:
        return _resp("REQUEST_AUTHORIZATION")

    # 2 account must be unambiguous
    aref = f.get("account_ref")
    accs = tools.lookup_account(aref) if aref else []
    if len(accs) != 1:
        return _resp("REQUEST_INFO")
    acc = accs[0]

    # 3 entitlement
    if acc.get("domain") != dom or contact.get("account_id") != acc["id"]:
        return _resp("REQUEST_AUTHORIZATION")

    # 4 instrument and date
    iref = f.get("instrument_ref")
    ins = tools.resolve_instrument(iref) if iref else []
    as_of = f.get("as_of")
    if len(ins) != 1 or not as_of:
        return _resp("REQUEST_INFO")
    inst = ins[0]["id"]

    # 5 not held
    pos = tools.get_position(acc["id"], inst, as_of)
    if pos is None or (pos["settled"] == 0 and not pos["pending"]):
        return _resp("NOT_HELD", acc["id"], inst, as_of)

    # 6 stated quantity break
    pending = pos["pending"] or 0
    sq = f.get("stated_qty")
    if sq is not None:
        total = pos["settled"] + pending
        if total == 0 or abs(sq - total) / total > QTY_TOLERANCE:
            return _resp("ESCALATE", acc["id"], inst, as_of)

    # 7 confirm
    if pending:
        return _resp("CONFIRMED", acc["id"], inst, as_of, pos["settled"], pending, pos["pending_date"])
    return _resp("CONFIRMED", acc["id"], inst, as_of, pos["settled"])
