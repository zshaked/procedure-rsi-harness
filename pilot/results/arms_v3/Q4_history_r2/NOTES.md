# Notes: induced desk procedure (history-only arm)

The rules below are applied in this order:
1. If the sender is an unknown contact or writes from a free webmail domain (gmail, yahoo, outlook, proton…), the desk asks for authorization.
2. The account mention is resolved with `search_accounts`. If it is missing, unknown or ambiguous (several hits by short name or name prefix), the desk asks for more information.
3. The sender needs an entitlement on that account that has not expired at `sent` and has level 2 or higher. Otherwise the desk asks for authorization. A level 1 entitlement is refused. The sender's domain is not checked against the client's domains, because entitlements are authoritative.
4. If the instrument is missing or unresolved, or the date is missing or later than `sent`, the desk asks for more information.
5. If the account has `legal_hold` or `no_email_confirm` set, the request is escalated.
6. The as-of date is rolled back to the previous business day when needed. "month-end" and "end of last month" mean the last day of the previous month.
7. Settled quantity is the full ledger across all sub-accounts up to the as-of date, multiplied for splits whose date falls after the trade and on or before the as-of date. `get_position_summary` is a trap: it uses only the primary sub-account and the day before.
8. Pending is the sum of matched instructions settling after the as-of date. `pending_date` is the latest of those settle dates.
9. If the client's figure differs by more than 10% from both the settled figure and settled plus pending, the request is escalated.
10. Settled ≤ 0 gives NOT_HELD. Anything else gives CONFIRMED.

**Inputs.** I took the rules from the 25 histories and the state they touch, and checked them with harness.py (25/25). I used the 175 unlabeled requests to find phrasings and to see how far client figures are off (×1.02, 1.04, 0.93, 1.08, 0.85, 1.5, and 1/3 for splits).

**Least sure:**
- The tolerance. 10% fits Q4-0013. 5% would make that reply an operator mistake.
- Whether `no_email_confirm` leads to ESCALATE or REQUEST_AUTHORIZATION.
- The meaning of `as_of_assumed`. I set it when the date was rolled or vague.
- Pending on NOT_HELD.
- Requests dated on `sent` itself.
