# Notes

## Rules I believe the desk follows (in order)
1. Account unresolved or ambiguous (several accounts share a name, or none named) -> REQUEST_INFO. Sender entitlements do not disambiguate.
2. Authorization -> REQUEST_AUTHORIZATION unless sender domain is in the account profile's domains AND the contact has a non-expired entitlement of level >= 2 on that account. This check comes before the instrument check.
3. Instrument unresolved -> REQUEST_INFO. Tickers, old tickers, names and ISINs all resolve.
4. legal_hold or no_email_confirm -> ESCALATE (guess; never tested).
5. as_of: stated date, "yesterday", "month-end" (last day of previous month). Non-business days roll back to the previous business day. No date -> sent date, rolled back, as_of_assumed=True.
6. settled = sum over ALL sub-accounts of ledger rows dated <= as_of. Rows before a split date are multiplied by the ratio only if the split date <= as_of.
7. A client-stated figure that differs from settled -> ESCALATE. No ledger rows or zero -> NOT_HELD.
8. Pending = sum of matched instructions settling after as_of, reported with the latest settle date. Unmatched and cancelled instructions are ignored.
9. get_position_summary is a trap: primary sub-account only, and the day before as_of.

## Oracle questions (15 of 15 used)
- Q2-0030, 0116, 0106: REQUEST_AUTHORIZATION, accepted.
- Q2-0091, 0049: REQUEST_INFO for an ambiguous account where the sender is entitled to exactly one candidate, accepted.
- Q2-0111, 0037: REQUEST_INFO, accepted.
- Q2-0035, 0028, 0084: CONFIRMED, accepted (0028: no split adjustment when the split is after as_of).
- Q2-0041: I answered REQUEST_INFO for a missing instrument, rejected because the entitlement was level 1. I moved the auth check before the instrument check.
- Q2-0055: sent on a holiday with no date, as_of is the previous business day and assumed, accepted.
- Q2-0164: ESCALATE on a stated-figure mismatch, accepted.
- Q2-0089: two matched pending instructions, rejected on the pending date. I used the earliest date and now use the latest.
- Q2-0123: NOT_HELD for an empty ledger, accepted.

## Least sure of
- Pending with several matched instructions: sum plus latest date is a guess, since the oracle only said the date was wrong.
- The legal_hold and no_email_confirm outcomes.
- Q2-0006 in the histories (stated figure equals ledger, but the operator escalated). I treat it as an operator mistake. Harness full agreement is 24/25.
- Unusual date phrasings ("month-end" with no "last").
