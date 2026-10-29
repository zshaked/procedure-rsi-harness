# Rules believed (procedure.py)
1. Account text missing, unmatched or ambiguous -> REQUEST_INFO (no disambiguation by entitlement).
2. REQUEST_AUTHORIZATION if the contact is unknown, the sender domain is not in the account profile domains, there is no unexpired entitlement (level >= 2) on that account, or the profile has no_email_confirm. This check comes before instrument checks.
3. Instrument missing, unmatched or ambiguous -> REQUEST_INFO.
4. Date: parse the text; relative phrases are resolved from `sent`; "month-end" is the end of last month; missing date means sent date with as_of_assumed true; weekends and holidays roll back to the previous business day.
5. legal_hold -> ESCALATE (account and instrument only).
6. Settled = sum of the ledger over all sub-accounts with date <= as_of. Holdings dated before a split are multiplied by its ratio only if the split date is <= as_of. The get_position_summary tool is not used.
7. Position of zero -> NOT_HELD, even if the client states a figure.
8. Pending = sum of matched instructions with settle_date > as_of; pending_date = the latest of them. Unmatched and cancelled instructions are ignored.
9. A stated client figure must equal settled + matched pending (or the unadjusted pre-split sum + pending). Any other value -> ESCALATE, with no tolerance.

# Oracle log (15 used)
1. Q2-0096 legal-hold ESCALATE: ok.
2. Q2-0105 my REQUEST_INFO was rejected. no_email_confirm means REQUEST_AUTHORIZATION, and it is checked before instrument checks. Reordered.
3. Q2-0066 domain mismatch -> REQUEST_AUTHORIZATION: ok.
4. Q2-0025 pending whose settle date is before `sent`: ok.
5. Q2-0069 two matched instructions: earliest pending_date rejected. Changed to the latest.
6. Q2-0069 latest pending_date: ok.
7. Q2-0128 stated figure equals the pre-split sum: my ESCALATE was rejected. It is now accepted as a match and CONFIRMED.
8. Q2-0157 my ESCALATE was rejected because the position is zero. Changed to NOT_HELD.
9. Q2-0157 NOT_HELD: ok.
10. Q2-0051 stated figure = settled + pending: CONFIRMED, ok.
11. Q2-0081 legal hold with an unauthorized sender: REQUEST_AUTHORIZATION, ok.
12. Q2-0029 month-end: ok.
13. Q2-0006 my CONFIRMED was rejected (stated figure ignores pending). This matches the history, so it was not a mistake.
14. Q2-0097 same pattern: CONFIRMED rejected. Rule 9 now compares against settled + pending.
15. Q2-0112 matched settle_date == as_of is not pending: ok.

# Least sure
- A future as_of date (I return REQUEST_INFO; never tested).
- Whether legal_hold ESCALATE should also carry as_of or settled.
- Level 1 versus 2 threshold (supported by only one history case).
- Stated figures that include unmatched pending.
- Year inference for dates written without a year.
