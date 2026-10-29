# NOTES (draft, plan written before any oracle question)

## Branch table (S1): branch | hist decided | unlabeled decided
account_ambiguous 3|23, auth_no_entitlement 4|23, auth_domain 1|17, confirm_pending 2|14, qty_mismatch 4|13,
auth_low_level 1|12, no_date 2|10, account_missing 0|7, not_held 0|6, instrument_missing 0|5, auth_expired 0|4,
future_date 0|3, claim_vs_zero 0|2, auth_domain_noacct 1|2, legal_hold 0|1, no_email_confirm 0|1, confirm_plain 7|32.
S4 skips: account_ambiguous, auth_no_entitlement, qty_mismatch, no_date, confirm_plain (>=2 hist, full agreement).

## Plan (S2 then S3, 15 max)
1 Q4-0038 auth_domain: corporate (non-freemail) wrong domain, entitled; "freemail-only" rule would CONFIRM
2 Q4-0060 auth_low_level: level 1, downstream would CONFIRM if level 1 allowed
3 Q4-0055 account_missing: sole entitlement could be inferred -> CONFIRM vs REQUEST_INFO
4 Q4-0064 not_held: empty ledger -> NOT_HELD (vs CONFIRMED 0)
5 Q4-0048 instrument_missing: whole-fund ask; INFO vs ESCALATE
6 Q4-0190 auth_expired: expired entitlement; would CONFIRM if expiry ignored
7 Q4-0083 future_date: as_of after sent; INFO vs clamp/assumed
8 Q4-0130 claim_vs_zero: client claims 5570, we hold 0; ESCALATE vs NOT_HELD
9 Q4-0043 auth_domain_noacct: freemail sender, ambiguous account; AUTH vs INFO
10 Q4-0114 legal_hold: ESCALATE vs other
11 Q4-0054 no_email_confirm: ESCALATE vs REQUEST_AUTHORIZATION
S3 (by branch unl count: confirm_pending 14 first, then qty_mismatch 13; truncated at 15):
12 Q4-0155 basis: claimed ~ settled only (pending large); min-basis CONFIRM vs total-only ESCALATE
13 Q4-0148 txn dated exactly on as_of: inclusive (<=) vs exclusive
14 Q4-0071 pending whose settle date is after as_of but before sent: report or not
15 Q4-0104 tolerance low side (8% off, tol 10%): CONFIRM vs ESCALATE
Truncated (not asked): tolerance high side, as_of_assumed flag meaning, expiry-equality, month-end on last day.

---
# FINAL NOTES

## Rules believed
Sender must be a known contact. Account text must resolve to exactly one account (else REQUEST_INFO; freemail/foreign-domain sender with no resolvable account gets REQUEST_AUTHORIZATION). Authorization needs a non-expired entitlement of level >= 2 on that account AND sender domain in the account's profile domains, otherwise REQUEST_AUTHORIZATION. Missing/unknown instrument or no date -> REQUEST_INFO. Future date (after sent) -> REQUEST_INFO. As-of rolls back to the previous business day. Settled = ledger sum over all sub-accounts with date <= as_of, rows before a split date (<= as_of) multiplied by ratio. Pending = matched instructions settling after as_of; pending_date = latest. Client figure compared with settled+pending; relative gap > 10% -> ESCALATE. Zero position -> NOT_HELD. as_of_assumed always False.

## Oracle questions (15 used; all planned above before asking)
1 Q4-0038 ok (domain must match profile). 2 Q4-0060 ok (level 1 insufficient). 3 Q4-0055 ok (no account -> INFO). 4 Q4-0064 ok (NOT_HELD). 5 Q4-0048 ok (no instrument -> INFO). 6 Q4-0190 ok (expired -> AUTH). 7 Q4-0083 ok (future date -> INFO). 8 Q4-0130 REJECTED ESCALATE: claim vs zero holding -> NOT_HELD; changed. 9 Q4-0043 ok. 10 Q4-0114 REJECTED ESCALATE for legal_hold (reason pointed to REQUEST_INFO); changed to REQUEST_INFO on a single answer (zero-support rule). 11 Q4-0054 REJECTED ESCALATE for no_email_confirm: should CONFIRM with pending; flag now ignored. 12 Q4-0155 REJECTED CONFIRM: basis is settled+pending only (min-basis removed). 13 Q4-0148 ok (txn on as_of included). 14 Q4-0071 ok (pending relative to as_of). 15 Q4-0104 ok (8% off still confirmed).

## Least sure
legal_hold (oracle reason odd; could be oracle error, true rule maybe ESCALATE). Tolerance exact value (between 8% and 15%; 10% assumed). Month-end when sent on last day of month. Expiry equal to sent date. as_of_assumed meaning (never set). Level-2 vs 3 differences. Edge: settled 0 with pending > 0.
