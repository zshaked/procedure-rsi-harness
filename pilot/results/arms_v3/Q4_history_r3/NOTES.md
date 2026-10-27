# Induced desk procedure (history-only arm)

Rules, in order:
1. Personal-mailbox sender (gmail, yahoo, outlook, proton...) -> REQUEST_AUTHORIZATION.
2. Account mention must resolve to exactly one account (ACC id, sub-account, name, short name). Missing or ambiguous -> REQUEST_INFO. Entitlements are not used to break ties.
3. Sender domain must be in the account's profile domains, and the contact needs a live (unexpired) entitlement for that account at level >= 2. Otherwise -> REQUEST_AUTHORIZATION.
4. Instrument (ticker, old ticker, name or ISIN) and an as-of date must be present. A missing or future date -> REQUEST_INFO. The forwarded-header "Date:" line is ignored.
5. legal_hold or no_email_confirm -> ESCALATE.
6. as_of = the requested date, rolled back to the previous business day if needed (weekends and holidays). "month-end" means last month and is flagged as_of_assumed.
7. Settled = full ledger across all sub-accounts with date <= as_of, including when a sub-account was named. Pre-split lots are multiplied by the ratio once the split date is <= as_of. get_position_summary is not used: it reads only the primary sub-account and the prior day.
8. Pending = matched instructions settling after as_of. Report the sum and the latest date.
9. A client figure more than 10% away from both settled and settled+pending -> ESCALATE. This includes a client figure that is not split-adjusted, and a client figure when we hold nothing.
10. Settled 0 -> NOT_HELD, otherwise CONFIRMED.

Inputs: the histories (25/25 on the harness, and the figures, dates and pending amounts match the reply texts). The unlabeled client figures were used to set the tolerance (noise up to about 8%, real mismatches at 0.85x, 1.5x and the unadjusted split figure) and to confirm whole-account totals and pending inclusion.

Least sure of: no_email_confirm mapped to ESCALATE (could be REQUEST_AUTHORIZATION), as_of_assumed semantics, whether the order puts legal hold before authorization, and NOT_HELD vs ESCALATE when the client claims a figure we don't hold.
