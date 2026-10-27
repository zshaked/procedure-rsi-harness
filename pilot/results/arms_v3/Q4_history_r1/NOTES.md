# Induced desk procedure (history-only arm)

Rules, applied in order:
1. Sender must be a known contact and not on a free-mail domain (gmail/yahoo/outlook...) -> else REQUEST_AUTHORIZATION (Q4-0008, 0009).
2. Account mention must resolve to exactly one account -> else REQUEST_INFO (0002, 0017, 0022).
3. Contact needs an unexpired entitlement of level >= 2 on that account, and the sender domain must be one of the client profile's domains -> else REQUEST_AUTHORIZATION (0004, 0005, 0011, 0018, 0020).
4. legal_hold or no_email_confirm on the profile -> ESCALATE.
5. Instrument must resolve; a date must be present and not in the future -> else REQUEST_INFO (0014, 0016).
6. Settled = sum of ledger over all sub-accounts (not position summary), date <= as-of, pre-split lots multiplied by the ratio; weekend/holiday dates roll back to the previous business day. "month-end"/"end of last month" = last day of previous month (month-end flagged as_of_assumed). A stated client figure differing by >10% from both settled and settled+pending -> ESCALATE (0001, 0003, 0019 split-unadjusted, 0024).
7. 0 -> NOT_HELD, else CONFIRMED; pending = matched instructions settling after as-of, dated by the latest (0013, 0021).

Inputs: histories for rules (harness 25/25); unlabeled requests for phrasing coverage and claim/figure ratio clusters.

Least sure: the tolerance (10% vs 5% vs exact; 0000 and 0013 could be operator mistakes), outcome for no_email_confirm and legal hold (ESCALATE guessed), future dates (REQUEST_INFO guessed), the domain check for entitled third-party senders, and as_of_assumed semantics.
