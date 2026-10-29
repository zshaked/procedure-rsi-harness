# NOTES
Original pre-registered plan (S1 branch table, S2 unsupported branches, S3 conventions): scratch/plan_original.md. Q&A log: scratch/log.md.

## Rules I believe (gate order)
1. Account ambiguous/unknown -> REQUEST_INFO (none stated: sender's single entitlement).
2. Sender unknown, not entitled, level<3, or expired before sent date -> REQUEST_AUTHORIZATION.
3. Instrument missing/unknown/ambiguous -> REQUEST_INFO.
4. Date: none -> sent date, assumed; future or non-business day -> REQUEST_INFO (no rollback).
5. no_email_confirm -> AUTHORIZATION; legal_hold -> ESCALATE.
6. Stated qty matching neither settled nor settled+matched-pending -> ESCALATE; |settled|>=2,000,000 -> ESCALATE.
7. Settled 0 -> NOT_HELD; else CONFIRMED. Settled = split-adjusted ledger, all sub-accounts, date<=as_of.
8. Pending = matched instructions after as_of, shown if >=1% of settled; earliest date.

## Oracle (15/15 used)
1 0074 no: settled+pending stated is fine. 2 0087 no: weekend -> ask date. 3 0062 no "wrong security": inconclusive, no change. 4 0031, 5 0084, 6 0032, 7 0053 yes (expiry judged on sent). 8 0145 no: huge position escalates. 9 0193, 10 0046 no: pending must be reported -> materiality rule. 11 0051 yes. 12 0085 no: date check precedes legal hold. 13 0080, 14 0076 yes. 15 0165 no "sender not set up": data show valid level-3 entitlement; rule has 2+ supports, so by R2 no change.

## Least sure
Pending 1% threshold; size threshold (somewhere in 1.22M-2.79M); qty tolerance 0; implicit-account rule; ledger row dated on as_of (untested); Q3-0022 treated as operator mistake; legal_hold vs auth order; Q3-0165 maybe hidden sender rule or oracle error.
