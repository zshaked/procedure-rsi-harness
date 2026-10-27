# Notes (policy-first)

**Rules, in order.**
1. Account ambiguous or not found: REQUEST_INFO. If none is given, use the sender's sole entitled account.
2. No contact, or no unexpired level-3 entitlement: REQUEST_AUTHORIZATION. Domain is irrelevant.
3. Instrument missing: REQUEST_INFO. Old tickers resolve.
4. Date (sent date if none, as_of_assumed) is future or not a business day: REQUEST_INFO.
5. no_email_confirm: REQUEST_AUTHORIZATION. legal_hold: ESCALATE.
6. Settled = split-adjusted ledger sum over all sub-accounts. 0: NOT_HELD. Negative, client figure >5% off, or >=1M: ESCALATE.
7. Pending = matched instructions after as_of with qty >= 1000.

**Inputs.** Fitted to the histories (24/25; Q3-0022 treated as an operator error). Used unlabeled cases to find edges and asked the oracle about my own outputs.

**Oracle log (15):**
1. 0018 pending 684: no
2. 0072: weekend date asks
3. 0123 pending: yes
4. 0046 pending: yes
5. 0175 4% diff: no, >=1M escalates
6. 0132 2% diff: yes
7. 0080 escalate on zero: no, NOT_HELD
8. 0025 gmail: yes
9. 0193 past pending: yes
10. 0085 legal hold: no, date first
11. 0051 future date: yes
12. 0137 inferred account: yes
13. 0114 old ticker: yes
14. 0198 holiday sent date: no, REQUEST_INFO
15. 0074 pending 656: no

**Least sure:** the pending threshold, 4-5% tolerance, the 1M cutoff, legal_hold, negatives, splits.
