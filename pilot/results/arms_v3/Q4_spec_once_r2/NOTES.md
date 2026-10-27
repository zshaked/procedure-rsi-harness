# Notes

## Rules the desk follows (in order)
1. No account named: REQUEST_AUTHORIZATION if the sender's domain is not registered to any account they are entitled to (for example gmail). Otherwise REQUEST_INFO. An ambiguous or unresolvable account is also REQUEST_INFO. A sub-account resolves to its parent account.
2. The sender's domain must be one of the account's registered domains, and the sender must hold an entitlement of level 2 or higher that has not expired. Otherwise REQUEST_AUTHORIZATION.
3. legal_hold: ESCALATE. no_email_confirm is ignored.
4. A missing or ambiguous instrument, a missing date, or a date after `sent`: REQUEST_INFO.
5. as_of is the requested date rolled back to the previous business day. as_of_assumed is false.
6. settled is the sum over all sub-accounts of ledger entries dated on or before as_of, adjusted for splits. get_position_summary is not used. pending is the sum of matched instructions settling after as_of, and pending_date is the latest of those dates.
7. settled = 0: NOT_HELD, even if the client claims a position.
8. If the client's figure is more than 10% away from both settled and settled+pending: ESCALATE. Otherwise CONFIRMED.

## How I used the inputs
I ran scripts over the histories and the unlabeled requests. The client figures in the unlabeled requests showed which figure the desk uses: the whole account total for sub-account requests, the split-adjusted figure, and settled+pending. I spent all 15 oracle questions on the weakest rules (see spec.md). The harness gives 25/25.

## Least sure about
- The 10% tolerance. All I know is that 8% passes and 15% escalates.
- When as_of_assumed is ever true.
- A zero settled position that has pending instructions.
- A requested date equal to `sent`.
- The order of checks when legal hold coincides with other problems.
