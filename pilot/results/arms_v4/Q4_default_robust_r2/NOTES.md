# Notes

## Rules believed
1. Account: more than one candidate -> REQUEST_INFO (checked first). Zero candidates: unverifiable sender domain -> REQUEST_AUTHORIZATION, else REQUEST_INFO.
2. Authorization: sender domain must be in the account profile's domains; contact needs an unexpired entitlement on the account, level >= 2 (level 3 if no instrument named). Otherwise REQUEST_AUTHORIZATION, checked before missing-instrument and missing-date.
3. Missing instrument, missing date, or date after `sent` -> REQUEST_INFO.
4. as_of = stated date, rolled back to previous business day. "month-end" / "last day of last month" = last day of the month before `sent`. "yesterday" = sent-1.
5. settled = sum of all sub-account ledger rows dated <= as_of; rows dated before a split (split date <= as_of) are multiplied by the ratio.
6. pending = matched instructions with settle_date > as_of; pending_date = latest. Unmatched and cancelled are ignored.
7. legal_hold -> ESCALATE. No holding -> NOT_HELD. Client figure matches neither settled nor settled+pending within 10% -> ESCALATE.
8. no_email_confirm is ignored. get_position_summary is a trap (primary sub-account only, strictly before as_of).

## Oracle (15 used)
1. Q4-0062 corporate domain mismatch, entitled: AUTH. ok.
2. Q4-0094 figure 7% off: ESCALATE. rejected.
3. Q4-0077 figure 8% off: ESCALATE. rejected. Two contradictions, so tolerance 5% -> 10%. Q4-0013 now agrees.
4. Q4-0078 claim = settled+pending: CONFIRMED with pending. ok.
5. Q4-0114 legal hold: ESCALATE. ok.
6. Q4-0054 no_email_confirm: CONFIRMED with pending. ok, so the flag is ignored.
7. Q4-0134 future date: INFO. ok.
8. Q4-0122 no account: INFO. ok.
9. Q4-0093 account-wide request, level 2: INFO. rejected (wants authorization).
10. Q4-0151 same, level 3: INFO. ok. So I added the level-3 rule for account-wide requests.
11. Q4-0130 NOT_HELD with a client figure. ok.
12. Q4-0118 legal hold with level 1: AUTH. ok.
13. Q4-0178 matched instruction before as_of is not pending. ok.
14. Q4-0168 expired entitlement: AUTH. ok.
15. Q4-0128 ambiguous account, bad domain: AUTH. rejected. Now INFO first.

## Least sure
- Exact tolerance (between 8% and 15%).
- Level 3 for account-wide requests rests on one answer.
- as_of_assumed is never true; I found no trigger.
- no_email_confirm rests on one answer.
- Order of legal_hold against missing fields.
