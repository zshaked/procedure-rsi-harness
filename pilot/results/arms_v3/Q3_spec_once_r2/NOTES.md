# Notes

**Rules (applied in order):**
1. Resolve the account (mention, else an ACC-/SA- id in the body, else the sender's single entitled account). None or ambiguous: REQUEST_INFO.
2. The sender needs a non-expired, level>=3 entitlement on that account, otherwise REQUEST_AUTHORIZATION. The sender's domain is not checked.
3. Instrument missing or unresolved: REQUEST_INFO.
4. Client is no_email_confirm: REQUEST_AUTHORIZATION.
5. Date: unparseable, after `sent`, or not a business day (relative dates included): REQUEST_INFO. No date: use the sent date, as_of_assumed=true.
6. legal_hold: ESCALATE.
7. Settled = ledger across all sub-accounts up to and including as_of. A split counts only if its date is <= as_of. Never use get_position_summary.
8. 0 settled: NOT_HELD, even if the client states a figure. Negative, or >= 1,000,000: ESCALATE. A client figure more than 5% away from settled (and from settled+pending): ESCALATE.
9. Otherwise CONFIRMED. Matched instructions settling after as_of are reported as pending.

**Inputs:** I used scripts to compare the histories against state, then tabulated the 175 unlabeled cases by flag. I spent all 15 oracle questions on cases that separate competing hypotheses (log in spec.md). Two findings came only from the oracle: weekend dates go to REQUEST_INFO, and large positions are escalated. H-0022 was an operator mistake. Harness agreement is 24/25, and the one disagreement is that case.

**Least sure:**
- The exact large-position threshold: it lies between 855k and 1.06m.
- The figure tolerance: 2% passed and 7% failed, so I chose 5%.
- How pending is reported when there are several instructions (summed, latest date).
- Whether a named sub-account means the whole account.
- legal_hold leads to ESCALATE (never confirmed directly).
- Negative holdings.
- Whether a missing instrument is checked before no_email_confirm (only H-0004 shows it).
