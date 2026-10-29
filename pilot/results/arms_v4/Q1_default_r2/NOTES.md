# NOTES

## Rules I believe the desk follows (checked in this order)
1. Resolve account from mention (id, sub-account, name, short name). Missing or ambiguous (several hits) -> REQUEST_INFO, even if the sender is entitled to only one candidate.
2. Authorization: sender domain in the account's profile domains, an unexpired entitlement on that account (expiry vs sent date), level >= 3. Otherwise REQUEST_AUTHORIZATION. This comes before date/instrument checks.
3. Instrument missing/ambiguous -> REQUEST_INFO.
4. Date: missing, weekend/holiday (get_calendar), or in the future -> REQUEST_INFO. No roll-back to a business day. Relative phrases resolve against `sent` (yesterday, month-end = last day of previous month).
5. legal_hold or no_email_confirm -> ESCALATE (untested after date checks pass).
6. Settled = ledger summed over all sub-accounts up to as_of, entries dated before a split already effective at as_of multiplied by its ratio. No ledger/zero -> NOT_HELD. Not the cached summary.
7. Pending = matched instructions with settle_date > as_of (sum, latest date). Unmatched/cancelled ignored.
8. Client's stated figure more than 5% off ours (CONFIRMED path only) -> ESCALATE.

## Oracle questions (15 used)
1. Q1-0017 roll back Sunday to Friday: no, ask for date. Kept INFO.
2. Q1-0102 assume previous business day when no date: no. Kept INFO.
3. Q1-0025 month-end on Saturday rolled back: no.
4. Q1-0092 "yesterday" business day, assumed=False: yes.
5. Q1-0032 unentitled sender -> AUTH: yes (so histories Q5/Q22 look like mistakes).
6. Q1-0111 ESCALATE on legal hold with Saturday date: no, date check first.
7. Q1-0064 ESCALATE with no date: no, same.
8. Q1-0116 ambiguous name -> INFO: yes.
9. Q1-0128 split after as_of unadjusted, past-dated pending reported: yes.
10. Q1-0134 net-zero position with pending -> NOT_HELD: yes.
11. Q1-0028 empty ledger -> NOT_HELD: yes (history Q19 looks like a mistake).
12. Q1-0112 two pendings summed, latest date: yes.
13. Q1-0051 client figure 15% off: no -> added ESCALATE rule.
14. Q1-0053 future date -> INFO: yes.
15. Q1-0120 7% off: no -> tolerance set to 5% (4% was fine in histories).

## Least sure
- Tolerance between 4% and 7%; denominator choice.
- no_email_confirm outcome; ordering of hold vs discrepancy.
- When as_of_assumed is ever True (I never set it).
- Unauthorized sender with missing instrument (I return AUTH).
- Whether level 2 ever suffices.
