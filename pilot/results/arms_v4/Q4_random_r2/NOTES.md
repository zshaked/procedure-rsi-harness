# Notes

## Rules I believe the desk follows (checked in this order)
1. Account text matching >1 account -> REQUEST_INFO. No account found/mentioned -> REQUEST_INFO if the sender is verified for some account, else REQUEST_AUTHORIZATION.
2. Authorization: the sender must have an unexpired entitlement of level >= 2 on the resolved account, and the sender's email domain must be in that account's profile domains. Otherwise REQUEST_AUTHORIZATION.
3. legal_hold or no_email_confirm on the account -> ESCALATE (guess; no oracle evidence).
4. Instrument unresolved, or no as-of date -> REQUEST_INFO.
5. As-of date: parse the free text; "month-end" and similar mean the last day of the previous month; "yesterday" is sent minus 1. A non-business day moves back to the previous business day.
6. Settled = ledger summed over ALL sub-accounts with date <= as_of. Quantities dated before a split that is on or before as_of are multiplied by its ratio. get_position_summary is not used.
7. Pending = matched instructions with settle_date > as_of (sum). pending_date is the latest such date. Unmatched and cancelled instructions are ignored.
8. If the client's stated figure differs by more than 10% from settled+pending, ESCALATE. Otherwise CONFIRMED, or NOT_HELD when the position is zero (NOT_HELD is a guess; it never appeared).

## Oracle questions (15 budget, all spent)
Accepted as-is: Q4-0169, 0035, 0153, 0172, 0191, 0071, 0067, 0026, 0170, 0132, 0075, 0041, 0093. No change was needed.
Q4-0196 (no account mentioned, sender verified): I asked REQUEST_INFO and was told REQUEST_AUTHORIZATION. I mistakenly re-asked with REQUEST_AUTHORIZATION, which was rejected with "they didn't say which account, so we ask". The two replies contradict. I kept REQUEST_INFO for a verified sender, which also matches Q4-0009 (gmail sender -> AUTH).
Protocol breach: the Q4-0196 re-ask used up one question, so Q4-0155 was never asked.

## Least sure of
- The 10% mismatch tolerance (4% and 7% were confirmed in histories; 15% was escalated).
- The legal_hold and no_email_confirm outcomes.
- The NOT_HELD conditions.
- as_of_assumed is never True.
- Whether pending should be split-adjusted.
