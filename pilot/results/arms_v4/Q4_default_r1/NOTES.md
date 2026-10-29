# NOTES

## Rules (in order)
1. Unknown sender, or no entitlement plus registered e-mail domain on the account(s) concerned: REQUEST_AUTHORIZATION.
2. Account unnamed, unknown or ambiguous: REQUEST_INFO.
3. Entitlement level below 2, or expired: REQUEST_AUTHORIZATION.
4. No security, no date, or date after `sent`: REQUEST_INFO.
5. Legal hold: ESCALATE. `no_email_confirm` is ignored.
6. Client figure more than 10% from settled+pending: ESCALATE (this includes split-unaware figures).
7. Zero position: NOT_HELD.
8. Otherwise CONFIRMED.

Position: all sub-accounts, ledger on or before as-of, entries before a split multiplied once its date is reached. Dates roll back to the previous business day; "month-end" is the previous month's end. Pending: matched instructions settling after as-of; pending_date is the latest.

## Oracle (15 of 15; Q4- prefix omitted)
1. 0028 no date, REQUEST_INFO: yes.
2. 0083 future date, REQUEST_INFO: yes.
3. 0130 empty ledger, NOT_HELD: yes.
4. 0055 unnamed account, I inferred it from the sole entitlement: no, ask. Now REQUEST_INFO.
5. 0125 ambiguous name from gmail, REQUEST_AUTHORIZATION: yes. Sender screen first.
6. 0032 entitled but unregistered corporate domain, REQUEST_AUTHORIZATION: yes.
7. 0114 legal hold, ESCALATE: yes.
8. 0054 `no_email_confirm`, ESCALATE: no, confirm with pending. Flag ignored.
9. 0155 figure 1.04x settled, large pending, CONFIRMED: no, escalate. Compare to settled+pending.
10. 0187 only past-dated matched instruction, pending null: yes.
11. 0077 figure +8%, CONFIRMED: yes.
12. 0045 no security, REQUEST_INFO: yes.
13. 0112 two pending, latest date: yes.
14. 0191 ambiguous, sender entitled to one candidate, REQUEST_INFO: yes.
15. 0173 level 1, REQUEST_AUTHORIZATION: yes.

## Least sure
- Negative positions (treated as normal).
- Exact tolerance (between 8% and 15%).
- Expired entitlements (untested).
- Old tickers (resolved normally).
- As-of before a split already effective at `sent` (no adjustment).
- Legal hold versus missing details ordering.
- `as_of_assumed` is never true.
