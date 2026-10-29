# NOTES

## Rules (in order)
1. Unknown sender, or sender domain not among the account's domains -> REQUEST_AUTHORIZATION.
2. Account missing/unresolved/ambiguous -> REQUEST_INFO (ambiguous resolves only for "our account <name>", via the sender's entitlement).
3. No valid entitlement (level >= 2, unexpired at sent) -> REQUEST_AUTHORIZATION.
4. Instrument unresolved, date missing or future -> REQUEST_INFO.
5. as_of = stated date rolled back to a business day. settled = all sub-accounts, entries <= as_of, split-adjusted if split <= as_of. Pending = matched instructions settling after as_of (sum, latest date).
6. legal_hold -> ESCALATE; settled 0 -> NOT_HELD; client figure >10% off settled+pending -> ESCALATE; else CONFIRMED.

## Oracle questions (15/15)
1. Q4-0104 CONFIRMED at 8% off: yes. Tolerance 10%.
2. Q4-0183 CONFIRMED, figure = settled+pending: yes. Compare to total.
3. Q4-0033 undated REQUEST_INFO: no ("entitlement too low"), yet sender is level 3. Treated as oracle error.
4. Q4-0039 undated REQUEST_INFO: yes.
5. Q4-0032 entitled, wrong domain, AUTH: yes. Domain checked per account.
6. Q4-0117 ambiguous, REQUEST_INFO: no. Led to rule 2 exception.
7. Q4-0055 no account named, REQUEST_INFO: yes.
8. Q4-0114 legal hold, ESCALATE: yes.
9. Q4-0054 no_email_confirm, ESCALATE: no (confirm with pending). Flag ignored.
10. Q4-0117 CONFIRMED: yes.
11. Q4-0155 figure matches settled only: no, escalate. Total-only comparison.
12. Q4-0113 ambiguous resolved by entitlement: no, clarify.
13. Q4-0068 ambiguous resolved by matching figure: no. Kept "our account" cue only.
14. Q4-0130 zero position, client figure, NOT_HELD: yes (before reconciliation).
15. Q4-0147 old ticker, past-dated matched ignored: yes.

## Least sure
- Why Q4-0117 resolves but 0113, 0068, history 0022 do not (cue vs exact figure vs oracle noise).
- Q4-0033 (undated, level 3).
- Future dates, negative positions, pending_date with several instructions, no_email_confirm: guesses.
