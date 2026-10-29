# Notes

## Rules I believe the desk follows (order matters)
1. Account text matching several accounts, or no account -> REQUEST_INFO. With no account text, the sender's single entitlement is used.
2. Sender needs a valid (unexpired) entitlement of level 3 on the account, otherwise REQUEST_AUTHORIZATION. This check comes before the missing-instrument check.
3. Missing or unresolvable instrument -> REQUEST_INFO.
4. Resolved as_of that is not a business day (weekend, holiday, month-end that falls on one) -> REQUEST_INFO. No date -> sent date, as_of_assumed=true.
5. Client with no_email_confirm -> REQUEST_AUTHORIZATION, with account, instrument and as_of filled.
6. legal_hold -> ESCALATE (a guess).
7. settled = sum of the ledger across sub-accounts up to as_of, with splits applied only if the split date is on or before as_of.
8. Zero position -> NOT_HELD. A stated figure matching neither settled nor settled plus open matched instructions -> ESCALATE.
9. Pending = matched instructions with as_of < settle_date <= sent+30 days, summed.

## Oracle questions (15 used; 2 were wasted by my own mistakes)
1. Q3-0077 INFO, ambiguous account though sender entitled: ok.
2. Q3-0085 AUTH: rejected, date 31-Jan is a Saturday -> INFO. Added the non-business-day rule.
3. Q3-0084 AUTH with null fields: rejected, wrong as-of date.
4. Q3-0084 ESCALATE: rejected, no-email clients go to authorization.
5. Q3-0084 AUTH with account, instrument and as_of: ok. Fields are now filled.
6. Q3-0107 INFO, derived month-end on a Saturday: ok.
7. Q3-0123 with a deliberately wrong account (my slip): rejected, pending handling.
8. Q3-0123 with correct fields and pending null: rejected, pending handling.
9. Q3-0072 (I sent it a CONFIRMED but it is a Saturday): wasted.
10. Q3-0123 with pending 13615: ok.
11. Q3-0193 with pending null: rejected, so pending counts even when settle_date < sent.
12. Q3-0148 split-adjusted settled: rejected, so a split after as_of is not applied.
13. Q3-0080 ESCALATE with settled 0: rejected, held 0 means NOT_HELD.
14. Q3-0074 CONFIRMED with pending 656: rejected.
15. Q3-0074 CONFIRMED with pending null: ok. Stated figure = settled + pending is consistent, and pending is outside the window.

## Least sure of
- The pending window (30 days from sent), and whether early instructions count.
- legal_hold behaviour (never observed at level 3 on a business day).
- Q3-0022 history (INFO) treated as an operator mistake.
- The tolerance on stated figures.
