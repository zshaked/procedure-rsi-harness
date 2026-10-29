# NOTES

## Rules believed
1. Sender must be a known contact writing from a domain registered for an account they hold an entitlement on; else REQUEST_AUTHORIZATION (free-mail lands here).
2. Account text ambiguous/missing -> REQUEST_INFO.
3. Sender needs an unexpired entitlement, level >= 2, on that account, with the sender domain in that account's profile domains; else REQUEST_AUTHORIZATION.
4. Missing/unknown instrument, missing date, or future date -> REQUEST_INFO.
5. Date: weekend/holiday -> previous business day; "month-end" = end of previous month.
6. legal_hold -> ESCALATE. no_email_confirm is ignored.
7. Settled = ledger over ALL sub-accounts up to as_of, split-adjusted (entries before a split date x ratio if split <= as_of). Not get_position_summary.
8. Pending = sum of matched instructions settling after as_of; pending_date = latest.
9. No holding -> NOT_HELD. Client's figure vs settled or settled+pending beyond 10% -> ESCALATE; else CONFIRMED.

## Oracle (15 used)
1. 0032 AUTH (corporate domain mismatch, entitled): ok.
2. 0039 INFO (no date): ok.
3. 0083 INFO (future date): ok.
4. 0055 INFO (no account, verified sender): ok.
5. 0114 ESCALATE (legal hold): ok.
6. 0054 ESCALATE (no_email_confirm): rejected, should confirm with pending; ignored the flag.
7. 0183 CONFIRMED (figure = settled+pending): ok.
8. 0130 NOT_HELD (client states a figure): ok.
9. 0148 CONFIRMED: rejected as "not entitled", contradicts data; treated as oracle error.
10. 0125 AUTH (gmail, ambiguous account): ok; moved sender check first.
11. 0119 CONFIRMED + pending: ok.
12. 0048 INFO (no instrument): ok.
13. 0077 CONFIRMED (+8% gap): ok; tolerance 10%.
14. 0096 AUTH (level 1): ok.
15. 0054 CONFIRMED + pending: ok.

## Least sure
Month-end phrase sent on a month's last day (0193); stated figure matching settled only when pending is large (0155); the 0148 rejection; as-of-day ledger entries counted as included.
