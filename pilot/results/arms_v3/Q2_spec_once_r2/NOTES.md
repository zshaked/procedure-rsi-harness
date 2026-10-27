# Notes

**Rules (in order).**
1. If the account or instrument mention resolves to zero or several records, the outcome is REQUEST_INFO. This includes ambiguous fund families and colliding short names. Sub-account ids and former tickers resolve normally.
2. The sender must pass authorization: the contact is known, the sender's domain is in the account profile's domains, and the sender holds an unexpired entitlement of level 2 or higher on that account. Otherwise the outcome is REQUEST_AUTHORIZATION. no_email_confirm is also treated as REQUEST_AUTHORIZATION (a guess).
3. A legal hold gives ESCALATE. This check comes after authorization.
4. The as_of date comes from the body (explicit date, "yesterday", "month-end"/"last day of last month"). A weekend or holiday rolls back to the previous business day. With no date, as_of is the sent date and as_of_assumed is true.
5. Settled is the ledger total over all sub-accounts up to and including as_of, adjusted for splits. Do not use get_position_summary.
6. Pending is the sum of matched instructions settling after as_of with quantity of at least 1,000. Smaller ones are not reported.
7. If settled is 0 or less, the outcome is NOT_HELD, even when the client states a figure.
8. If the client states a figure, it must match settled + pending, or the pre-split equivalent. Otherwise the outcome is ESCALATE.

**Inputs.** I analysed the histories with scripts and used the client figures in the unlabeled set as weak labels. For example, 0051's figure equals settled + pending, and the ratios such as 1.02 and 1.5 are taken against settled + pending. I used all 15 oracle questions on the uncertain rules; they are recorded in spec.md. The harness agrees on 25/25.

**Least sure about.**
- The outcome for no_email_confirm (never tested cleanly).
- The exact pending threshold of 1,000. A relative cut above 1.2% would also fit.
- The comparison tolerance, set at 0.5%. Only a tolerance below 2% is confirmed.
- How several material pendings are combined (summed, with the latest date).
- Future-dated requests, which I treat as REQUEST_INFO.
