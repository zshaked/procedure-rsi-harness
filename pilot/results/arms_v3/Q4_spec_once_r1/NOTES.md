# NOTES

**Rules (in order):**
1. No account named: free-mail/unknown sender gets REQUEST_AUTHORIZATION; otherwise REQUEST_INFO. An account that is ambiguous or not found gets REQUEST_INFO. The account is never guessed from entitlements.
2. Sender domain not in the account's registered domains, or no unexpired entitlement on the account: REQUEST_AUTHORIZATION.
3. Legal hold: ESCALATE.
4. Entitlement level below 2: REQUEST_AUTHORIZATION. The no_email_confirm flag is ignored.
5. Instrument or date missing, or date on/after the sent date: REQUEST_INFO.
6. Date parsing covers explicit formats, "yesterday" and "month-end" (last day of the previous month). Non-business days roll back to the previous business day.
7. Settled is the ledger summed over all sub-accounts, dated on or before as_of, with split adjustment. Zero gives NOT_HELD (this beats a stated figure). Negative gives ESCALATE (guess).
8. Pending is matched instructions settling after as_of: the sum, with the latest date.
9. A stated client figure more than 10% off both settled and settled+pending gives ESCALATE. Otherwise CONFIRMED. as_of_assumed is always false.

**Inputs:** I analysed the histories and unlabeled cases with scripts (scratch/). From the client figures I found the generator's ratios (1.02, 1.04, 1.08, 0.93, 0.85, 1.5, settled+pending) and used them to target oracle questions. I used all 15 questions (logged in spec.md). They settled tolerance bounds, legal hold, no_email_confirm, future dates, NOT_HELD precedence, pending date, the inclusive boundary, expiry and the domain requirement. The harness was only used to check the implementation: 25/25.

**Least sure:**
- The exact tolerance (somewhere between 8% and 15%).
- Legal hold outranking a level-1 entitlement (rests on one oracle answer).
- Same-day dates.
- Negative positions.
- as_of_assumed semantics.
- The "no account" sender test.
