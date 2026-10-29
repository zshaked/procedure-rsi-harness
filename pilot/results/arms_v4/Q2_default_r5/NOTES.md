# Notes

## Rules (as implemented)
1. Account/instrument via search_accounts/search_instruments on the mentions. Missing, unmatched or ambiguous (several "X I/II/III") -> REQUEST_INFO (checked before authorization).
2. Authorization: known contact, sender domain in the account profile domains, and an unexpired entitlement of level >= 2 on that account; otherwise REQUEST_AUTHORIZATION (checked before legal hold).
3. legal_hold or no_email_confirm on the profile -> ESCALATE.
4. As-of: parsed from the body (forwarded headers ignored); weekend/holiday -> previous business day; no date -> sent date, as_of_assumed=true. Future date -> REQUEST_INFO (guess).
5. Settled = sum of the ledger over all sub-accounts up to as_of, with each entry dated before a split (split date <= as_of) multiplied by its ratio. get_position_summary is not used.
6. Zero -> NOT_HELD (takes priority over a stated figure).
7. Pending = matched instructions settling after as_of; sum, latest settle date.
8. A client-stated figure must equal settled + pending, otherwise ESCALATE (k/mm figures get rounding tolerance).

## Oracle (15 used)
1. Q2-0006 CONFIRMED: rejected (stated figure equals settled, but a matched pending exists). Led to the rule 8 comparison.
2. Q2-0066 AUTH (outlook domain, entitled): ok. Confirms the domain check.
3. Q2-0096 ESCALATE (legal hold): ok.
4. Q2-0189 AUTH (no_email_confirm, bad domain): ok.
5. Q2-0194 AUTH (level 1): ok.
6. Q2-0157 ESCALATE (zero holding, stated figure): rejected. Changed to NOT_HELD first.
7. Q2-0123 NOT_HELD: ok.
8. Q2-0097 CONFIRMED (stated == settled, pending exists): rejected. Led to rule 8.
9. Q2-0051 CONFIRMED (stated == settled + pending): ok.
10. Q2-0025 pending relative to as_of (settle date before sent): ok.
11. Q2-0069 pending date = earliest: rejected. Changed to latest: ok.
12. Q2-0029 "month-end" = end of last month: ok.
13. Q2-0081 legal hold, no entitlement -> AUTH: ok.
14. Q2-0055 sent on a holiday, assumed date = previous business day: ok.

## Least sure
- Future as-of dates (REQUEST_INFO is a guess).
- no_email_confirm in isolation (all tests were confounded by domain).
- Settle date equal to as_of (excluded from pending).
- Tolerance on plain-number stated figures (exact required).
- Unrecognised date phrasings.
