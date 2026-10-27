"""Reference-free verifier for the holdings-confirmation desk.

verify(request, response, tools) -> (ok: bool, failures: list[str])

The checklist below was induced from histories.jsonl (evidence case_ids cited on every check) and
then calibrated against the oracle (see ORACLE LOG at the bottom). It needs no reference reply:
every condition is derived from the request plus the system of record (`tools`).

Decision ladder the checks encode (first matching gate decides the outcome):
  G1 sender gate       -> REQUEST_AUTHORIZATION
  G2 account ambiguity -> REQUEST_INFO
  G3 entitlement       -> REQUEST_AUTHORIZATION
  G4 missing details   -> REQUEST_INFO
  G5 not held          -> NOT_HELD
  G6 stated-qty break  -> ESCALATE
  G7 otherwise         -> CONFIRMED (with system-of-record facts)
"""

OUTCOMES = {"CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"}
FREE_MAIL = {"gmail.com", "outlook.com", "proton.me", "yahoo.com", "hotmail.com", "icloud.com",
             "aol.com", "protonmail.com", "live.com", "msn.com"}
MIN_AUTH_LEVEL = 2          # level 1 never gets data; levels 2 and 3 are treated identically
QTY_TOLERANCE = 0.10        # stated vs (settled + pending); observed confirms <= 8%, escalations >= 15%


def _account_domain(tools, account_id):
    accs = tools.lookup_account(account_id) if account_id else []
    return accs[0]["domain"] if len(accs) == 1 else None


def expected(request, tools):
    """Return (outcome, facts) the checklist requires. facts is a dict for fact-bearing outcomes."""
    f = request.get("fields") or {}
    sender = (request.get("from") or "").strip().lower()
    dom = sender.split("@")[-1] if "@" in sender else ""
    contact = tools.get_contact(sender) if sender else None

    # G1a unknown sender -> authorization. No history case (all senders are contacts); conservative.
    if contact is None:
        return "REQUEST_AUTHORIZATION", None, "G1a unknown sender"
    # G1b auth_level 1 contacts always get REQUEST_AUTHORIZATION, even when the account matches and
    # even when the request is otherwise incomplete/ambiguous.
    # Evidence: P4-0020, P4-0036, P4-0040, P4-0041 (ambiguous acct), P4-0043, P4-0055 (ambiguous), P4-0142,
    # P4-0153, P4-0155.
    if contact.get("auth_level", 0) < MIN_AUTH_LEVEL:
        return "REQUEST_AUTHORIZATION", None, "G1b auth_level<2"
    # G1c sender writing from a personal / free-mail domain (not the contact's firm domain) -> authorization,
    # even when the contact is entitled to the account.
    # Evidence: P4-0031, P4-0081, P4-0091, P4-0105, P4-0159, P4-0169, P4-0099 (ambiguous acct), P4-0054.
    # Counter-examples judged operator mistakes: P4-0175 (confirmed), P4-0014 / P4-0152 (asked for info).
    firm_dom = _account_domain(tools, contact.get("account_id"))
    if dom in FREE_MAIL or (firm_dom and dom != firm_dom):
        return "REQUEST_AUTHORIZATION", None, "G1c non-firm sender domain"

    # G2 account reference must resolve to exactly one account; otherwise ask, without using the
    # sender's own account to disambiguate.
    # Evidence: P4-0003 (contact is one of the 2 candidates, still REQUEST_INFO), P4-0017, P4-0022, P4-0025,
    # P4-0026, P4-0035, P4-0037, P4-0075, P4-0076, P4-0089, P4-0118, P4-0139, P4-0164, P4-0170, P4-0171,
    # P4-0173, P4-0197.
    aref = f.get("account_ref")
    accs = tools.lookup_account(aref) if aref else []
    if len(accs) != 1:
        return "REQUEST_INFO", None, "G2 account not uniquely resolved"
    acc = accs[0]["id"]

    # G3 the contact must be entitled to that account (contact.account_id == resolved account) -> else
    # REQUEST_AUTHORIZATION; this gate is checked BEFORE missing instrument/date.
    # Evidence: P4-0006, P4-0009, P4-0010, P4-0027, P4-0039, P4-0042, P4-0057 (same firm domain, other acct),
    # P4-0058, P4-0023/P4-0073 (instrument missing, still RA), P4-0061/P4-0071/P4-0146/P4-0161 (as_of missing,
    # still RA), P4-0181. Counter-examples judged mistakes: P4-0080, P4-0143.
    # Oracle (P4-0143, P4-0073): "That sender isn't on the client's domain, so we treat them as unauthorized";
    # oracle (P4-0057, same firm domain, sibling account): "asking about an account that isn't theirs".
    # So both the sender domain must equal the resolved account's domain AND the contact must be on it.
    if dom != accs[0].get("domain") or contact.get("account_id") != acc:
        return "REQUEST_AUTHORIZATION", None, "G3 contact not entitled to account"

    # G4 instrument must resolve to exactly one instrument, and an as_of date must be given.
    # Evidence (instrument missing/ambiguous): P4-0140, P4-0141, P4-0151, P4-0160, P4-0167, P4-0016, P4-0103.
    # Evidence (as_of missing -> ask, never assume): P4-0005, P4-0012, P4-0033, P4-0069, P4-0072, P4-0078,
    # P4-0096, P4-0104, P4-0116, P4-0120, P4-0122, P4-0174, P4-0190, P4-0198. (P4-0094 RA judged mistake.)
    iref = f.get("instrument_ref")
    ins = tools.resolve_instrument(iref) if iref else []
    if len(ins) != 1:
        return "REQUEST_INFO", None, "G4a instrument not uniquely resolved"
    inst = ins[0]["id"]
    as_of = f.get("as_of")
    if not as_of:
        return "REQUEST_INFO", None, "G4b as_of missing"

    pos = tools.get_position(acc, inst, as_of)
    # G5 never held, or zero settled and nothing pending -> NOT_HELD (stated_qty does not matter).
    # Evidence: P4-0028, P4-0066 (stated qty given), P4-0083, P4-0095, P4-0114, P4-0124, P4-0149, P4-0154,
    # P4-0165; zero settled: P4-0148.
    if pos is None or (pos["settled"] == 0 and not pos["pending"]):
        return "NOT_HELD", {"account_id": acc, "instrument_id": inst, "as_of": as_of}, "G5 not held"

    facts = {"account_id": acc, "instrument_id": inst, "as_of": as_of, "settled": pos["settled"],
             "pending": pos["pending"] or 0, "pending_date": pos["pending_date"]}
    # G6 client's stated quantity compared with settled + pending; relative break > 10% -> ESCALATE.
    # Evidence ESCALATE: P4-0093 (15%), P4-0086 (15%), P4-0088, P4-0050 (50%), P4-0168 (52%),
    # P4-0179 (2% vs settled but 73% vs settled+pending). Evidence CONFIRMED: diffs 0-8% e.g. P4-0046, P4-0126,
    # P4-0193, P4-0082, P4-0189; P4-0056 (213% vs settled, 8% vs settled+pending).
    # Unexplained escalations judged mistakes: P4-0018, P4-0024, P4-0052, P4-0127, P4-0191.
    sq = f.get("stated_qty")
    if sq is not None:
        total = pos["settled"] + (pos["pending"] or 0)
        if total == 0 or abs(sq - total) / total > QTY_TOLERANCE:
            return "ESCALATE", facts, "G6 stated quantity break"
    return "CONFIRMED", facts, "G7 confirm"


def verify(request, response, tools):
    fails = []
    if not isinstance(response, dict):
        return False, ["response is not a dict"]
    out = response.get("outcome")
    # C0 outcome must be one of the five desk outcomes.
    if out not in OUTCOMES:
        return False, [f"C0 invalid outcome {out!r}"]

    exp, facts, why = expected(request, tools)
    # C1 outcome must match the decision ladder (see G1-G7 above).
    if out != exp:
        fails.append(f"C1 outcome {out} but checklist requires {exp} ({why})")
        return False, fails

    if out in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        # C2 account and instrument identify the resolved records (ids, not free text).
        # Evidence: every CONFIRMED/NOT_HELD reply quotes the ACC- id, e.g. P4-0000 (name ref -> ACC-10004).
        if response.get("account_id") != facts["account_id"]:
            fails.append(f"C2 account_id {response.get('account_id')} != {facts['account_id']}")
        if response.get("instrument_id") != facts["instrument_id"]:
            fails.append(f"C2 instrument_id {response.get('instrument_id')} != {facts['instrument_id']}")
    if out in ("CONFIRMED", "NOT_HELD"):
        # C3 as_of is the requested date, never assumed (no history case confirms without a date).
        # Evidence: all CONFIRMED/NOT_HELD replies echo the requested as_of (P4-0000 ... P4-0199).
        if response.get("as_of") != facts["as_of"]:
            fails.append(f"C3 as_of {response.get('as_of')} != {facts['as_of']}")
        if response.get("as_of_assumed"):
            fails.append("C3 as_of_assumed must be False")
    if out == "CONFIRMED":
        # C4 settled quantity is the system-of-record settled quantity as of the date (NOT the client's
        # stated quantity, NOT settled+pending). Evidence: P4-0004 (stated 15,185, replied 14,601),
        # P4-0029 / P4-0135 (qty_before used when trade_date > as_of), P4-0045 (qty_after).
        if response.get("settled") != facts["settled"]:
            fails.append(f"C4 settled {response.get('settled')} != {facts['settled']}")
        # C5 pending units (settling after as_of) are reported with their date whenever non-zero, and not
        # reported otherwise. Evidence: P4-0001, P4-0013, P4-0015, P4-0029, P4-0056, P4-0189;
        # not reported when pending_date <= as_of: P4-0008, P4-0034, P4-0177. Omissions P4-0064, P4-0163
        # judged mistakes.
        if facts["pending"]:
            if response.get("pending") != facts["pending"] or response.get("pending_date") != facts["pending_date"]:
                fails.append(f"C5 pending must be reported: {facts['pending']} on {facts['pending_date']}")
        else:
            if response.get("pending") or response.get("pending_date"):
                fails.append("C5 no pending settlement to report")
    else:
        # C6 non-confirm outcomes disclose no quantities.
        if response.get("settled") or response.get("pending"):
            fails.append("C6 quantities disclosed on a non-CONFIRMED outcome")
    if out in ("REQUEST_INFO", "REQUEST_AUTHORIZATION"):
        # C7 RI/RA replies identify nothing (no account/instrument confirmed to an unverified party).
        if response.get("account_id") or response.get("instrument_id"):
            fails.append("C7 RI/RA should not echo resolved account/instrument")
    return (not fails), fails


# ORACLE LOG (Phase 2): 21 of 25 questions used. Format: case | response | oracle | verify() at time of asking.
# Verifier agreed with the oracle on 20/21. The one disagreement (P4-0143 REQUEST_AUTHORIZATION judged
# "Not sure this is right") was contradicted by the oracle's own next answer on the same case
# (REQUEST_INFO rejected: "sender isn't on the client's domain ... unauthorized"), so it was treated as oracle
# noise; the G3 wording was refined to name the domain test explicitly. Calibrations confirmed:
#  - as_of is never assumed (P4-0012); pending must be reported iff it settles after as_of (P4-0064, P4-0034);
#  - stated qty is compared with settled+pending (P4-0179); unexplained historical escalations are mistakes
#    (P4-0018, P4-0024, P4-0052, P4-0127, P4-0191 all CONFIRMED acceptable);
#  - free-mail senders -> RA even if entitled (P4-0175, P4-0014, P4-0152); entitlement mismatch -> RA before
#    missing-field RI (P4-0080, P4-0073, P4-0143, P4-0057); missing as_of -> RI (P4-0094);
#  - ambiguous account is never disambiguated via the sender (P4-0003); ESCALATE must carry ids (P4-0088).
ORACLE_LOG = r"""
P4-0024 | {"outcome": "CONFIRMED", "account_id": "ACC-10154", "instrument_id": "ISIN9158829969", "as_of": "2026-02-12", "as_of_assumed": false, "settled": 10390, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0024", "acceptable": true, "reason": "Looks right.", "questions_left": 24} | VERIFY: (True, [])
P4-0179 | {"outcome": "CONFIRMED", "account_id": "ACC-10171", "instrument_id": "ISIN4975237862", "as_of": "2026-02-11", "as_of_assumed": false, "settled": 11067, "pending": 30106, "pending_date": "2026-05-03"} | ORACLE: {"case_id": "P4-0179", "acceptable": false, "reason": "Their number doesn't match ours closely enough; that goes to escalation.", "questions_left": 23} | VERIFY: (False, ['C1 outcome CONFIRMED but checklist requires ESCALATE (G6 stated quantity break)'])
P4-0175 | {"outcome": "CONFIRMED", "account_id": "ACC-10178", "instrument_id": "ISIN7006071145", "as_of": "2026-02-04", "as_of_assumed": false, "settled": 873191, "pending": 547, "pending_date": "2026-03-23"} | ORACLE: {"case_id": "P4-0175", "acceptable": false, "reason": "That sender isn't on the client's domain, so we treat them as unauthorized.", "questions_left": 22} | VERIFY: (False, ['C1 outcome CONFIRMED but checklist requires REQUEST_AUTHORIZATION (G1c non-firm sender domain)'])
P4-0012 | {"outcome": "CONFIRMED", "account_id": "ACC-10196", "instrument_id": "ISIN9770061438", "as_of": "2026-02-09", "as_of_assumed": true, "settled": 830773, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0012", "acceptable": false, "reason": "No as-of date, so we go back and ask for one.", "questions_left": 21} | VERIFY: (False, ['C1 outcome CONFIRMED but checklist requires REQUEST_INFO (G4b as_of missing)'])
P4-0052 | {"outcome": "CONFIRMED", "account_id": "ACC-10005", "instrument_id": "ISIN3387658650", "as_of": "2025-12-23", "as_of_assumed": false, "settled": 1422600, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0052", "acceptable": true, "reason": "Looks right.", "questions_left": 20} | VERIFY: (True, [])
P4-0064 | {"outcome": "CONFIRMED", "account_id": "ACC-10150", "instrument_id": "ISIN5179943530", "as_of": "2026-02-07", "as_of_assumed": false, "settled": 1615427, "pending": 351, "pending_date": "2026-05-21"} | ORACLE: {"case_id": "P4-0064", "acceptable": true, "reason": "Looks right.", "questions_left": 19} | VERIFY: (True, [])
P4-0014 | {"outcome": "REQUEST_AUTHORIZATION", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0014", "acceptable": true, "reason": "Looks right.", "questions_left": 18} | VERIFY: (True, [])
P4-0080 | {"outcome": "REQUEST_AUTHORIZATION", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0080", "acceptable": true, "reason": "Looks right.", "questions_left": 17} | VERIFY: (True, [])
P4-0064 | {"outcome": "CONFIRMED", "account_id": "ACC-10150", "instrument_id": "ISIN5179943530", "as_of": "2026-02-07", "as_of_assumed": false, "settled": 1615427, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0064", "acceptable": false, "reason": "The pending amount handling isn't right.", "questions_left": 16} | VERIFY: (False, ['C5 pending must be reported: 351 on 2026-05-21'])
P4-0088 | {"outcome": "ESCALATE", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0088", "acceptable": false, "reason": "The details are wrong.", "questions_left": 15} | VERIFY: (False, ['C2 account_id None != ACC-10010', 'C2 instrument_id None != ISIN2170313384'])
P4-0094 | {"outcome": "REQUEST_INFO", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0094", "acceptable": true, "reason": "Looks right.", "questions_left": 14} | VERIFY: (True, [])
P4-0127 | {"outcome": "CONFIRMED", "account_id": "ACC-10228", "instrument_id": "ISIN9351223620", "as_of": "2026-02-10", "as_of_assumed": false, "settled": 619051, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0127", "acceptable": true, "reason": "Looks right.", "questions_left": 13} | VERIFY: (True, [])
P4-0191 | {"outcome": "CONFIRMED", "account_id": "ACC-10038", "instrument_id": "ISIN6756460408", "as_of": "2026-02-17", "as_of_assumed": false, "settled": 16784, "pending": 47, "pending_date": "2026-05-15"} | ORACLE: {"case_id": "P4-0191", "acceptable": true, "reason": "Looks right.", "questions_left": 12} | VERIFY: (True, [])
P4-0003 | {"outcome": "CONFIRMED", "account_id": "ACC-10068", "instrument_id": "ISIN9617590942", "as_of": "2026-01-03", "as_of_assumed": false, "settled": 2230021, "pending": 48383, "pending_date": "2026-01-24"} | ORACLE: {"case_id": "P4-0003", "acceptable": false, "reason": "We can't tell which account they mean, so we ask them to clarify.", "questions_left": 11} | VERIFY: (False, ['C1 outcome CONFIRMED but checklist requires REQUEST_INFO (G2 account not uniquely resolved)'])
P4-0143 | {"outcome": "REQUEST_AUTHORIZATION", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0143", "acceptable": false, "reason": "Not sure this is right, please double-check.", "questions_left": 10} | VERIFY: (True, [])
P4-0143 | {"outcome": "REQUEST_INFO", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0143", "acceptable": false, "reason": "That sender isn't on the client's domain, so we treat them as unauthorized.", "questions_left": 9} | VERIFY: (False, ['C1 outcome REQUEST_INFO but checklist requires REQUEST_AUTHORIZATION (G3 contact not entitled to account)'])
P4-0073 | {"outcome": "REQUEST_INFO", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0073", "acceptable": false, "reason": "That sender isn't on the client's domain, so we treat them as unauthorized.", "questions_left": 8} | VERIFY: (False, ['C1 outcome REQUEST_INFO but checklist requires REQUEST_AUTHORIZATION (G3 contact not entitled to account)'])
P4-0057 | {"outcome": "NOT_HELD", "account_id": "ACC-10120", "instrument_id": "ISIN5562998040", "as_of": "2026-01-16", "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0057", "acceptable": false, "reason": "They're asking about an account that isn't theirs; needs authorization.", "questions_left": 7} | VERIFY: (False, ['C1 outcome NOT_HELD but checklist requires REQUEST_AUTHORIZATION (G3 contact not entitled to account)'])
P4-0018 | {"outcome": "CONFIRMED", "account_id": "ACC-10172", "instrument_id": "ISIN6069012281", "as_of": "2026-01-26", "as_of_assumed": false, "settled": 8397, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0018", "acceptable": true, "reason": "Looks right.", "questions_left": 6} | VERIFY: (True, [])
P4-0152 | {"outcome": "REQUEST_AUTHORIZATION", "account_id": null, "instrument_id": null, "as_of": null, "as_of_assumed": false, "settled": null, "pending": null, "pending_date": null} | ORACLE: {"case_id": "P4-0152", "acceptable": true, "reason": "Looks right.", "questions_left": 5} | VERIFY: (True, [])
P4-0034 | {"outcome": "CONFIRMED", "account_id": "ACC-10143", "instrument_id": "ISIN1945109704", "as_of": "2026-01-29", "as_of_assumed": false, "settled": 3168, "pending": 722, "pending_date": "2026-01-08"} | ORACLE: {"case_id": "P4-0034", "acceptable": false, "reason": "The pending amount handling isn't right.", "questions_left": 4} | VERIFY: (False, ['C5 no pending settlement to report'])
"""
