# Induced desk procedure

Rules, applied in this order:
1. Sender is on a personal domain (gmail, outlook...) or is not a known contact: REQUEST_AUTHORIZATION. This check comes before the missing-info check (Q4-0008, 0009, 0043).
2. Account missing, unknown or ambiguous (a name prefix matching several funds, or a duplicate short name), instrument missing or unknown, date missing, or date in the future: REQUEST_INFO.
3. The contact needs an unexpired entitlement on the account at level >= 2, and the sender's domain must be in the account's profile domains. Otherwise REQUEST_AUTHORIZATION. no_email_confirm also gives REQUEST_AUTHORIZATION, and legal_hold gives ESCALATE (both guesses).
4. as_of is the requested date, rolled back to the previous business day if needed (get_calendar). "Month-end" or "last day of last month" means the last calendar day of the previous month, then rolled. A bare "month-end" sets as_of_assumed=true.
5. No ledger rows at all for the account and instrument: REQUEST_INFO ("cannot locate", Q4-0040).
6. Settled is the sum of ledger qty dated <= as_of across all sub-accounts. A row is multiplied by a split's ratio if the split date is after the row and <= as_of. get_position_summary is not used: it covers only the primary sub-account and uses the previous day.
7. Pending is the sum of matched instructions settling after as_of. pending_date is the latest of those settle dates.
8. If the client quotes a figure more than 10% away from both settled and settled+pending: ESCALATE. This covers stale pre-split figures (Q4-0019).
9. Settled <= 0: NOT_HELD. Otherwise CONFIRMED.

Least sure: the 10% tolerance (the histories only show it lies between 4% and 15%), the meaning of as_of_assumed, NOT_HELD versus REQUEST_INFO when there is no ledger history, legal_hold and no_email_confirm, and whether a sub-account request should report only that sub-account. Q4-0032 is treated as an operator mistake.
