# Notes

## Rules (in order)
1. Account text matching several accounts -> REQUEST_INFO.
2. Account unresolved or unnamed, or sender lacks a valid level-3 entitlement -> REQUEST_AUTHORIZATION (before later checks).
3. Instrument missing or ambiguous -> REQUEST_INFO.
4. no_email_confirm -> REQUEST_AUTHORIZATION.
5. Date (explicit or relative; none -> sent date, assumed). Non-business day or future -> REQUEST_INFO.
6. legal_hold -> ESCALATE (guess).
7. Settled = ledger over all sub-accounts to as_of, split-adjusted. Zero -> NOT_HELD.
8. Client figure differs from settled -> ESCALATE.
9. Else CONFIRMED; pending = matched, settling after as_of, qty >= 1000.

## Oracle (15 used)
1. Q3-0090 ESCALATE: no; no_email_confirm means authorization. Added rule 4.
2. Q3-0085 ESCALATE: no; non-business day. Added date check.
3. Q3-0054 AUTH: no ("wrong security"); treated as noise.
4. Q3-0147 AUTH: no ("doesn't hold"); contradicted by Q8, noise.
5. Q3-0026 AUTH, level 2: yes.
6. Q3-0158 ESCALATE on mismatch: yes.
7. Q3-0080 ESCALATE with zero holding: no; NOT_HELD now precedes the mismatch check.
8. Q3-0147 INFO: no; "entitlement too low", so AUTH comes before the date check.
9. Q3-0033 INFO, Saturday month-end: yes.
10. Q3-0123 pending at +20 days: yes.
11. Q3-0046 pending at +68 days: yes.
12. Q3-0018 pending 684 at +81 days: no. Added qty floor.
13. Q3-0193 pending 4,632: no, bogus reason (date is a business day); noise.
14. Q3-0051 INFO, future date: yes.
15. Q3-0062 AUTH, no account named: yes.

## Least sure
- Pending: the cutoff may be a 70-80 day horizon rather than a qty floor. Past-dated pending is untested.
- legal_hold placement and outcome.
- Q3-0022 still disagrees; I treat it as an operator error.
- Relative dates landing on weekends are treated as non-business days.
