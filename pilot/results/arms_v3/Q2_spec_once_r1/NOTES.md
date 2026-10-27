# Notes

**Rules (in order; full detail in spec.md):**
1. If the account (resolved with search_accounts) or the instrument (ticker, old ticker, name or ISIN) is missing or ambiguous: REQUEST_INFO. This check runs before authorization.
2. Authorization fails, giving REQUEST_AUTHORIZATION, unless all three hold: the sender's domain is in the profile's domains, the sender is a known contact, and that contact has an entitlement on the account with level >= 2 that has not expired by the sent date.
3. If the account has legal_hold: ESCALATE. If it has no_email_confirm: REQUEST_AUTHORIZATION (this one is a guess).
4. Date. A date in the email is used as given; relative phrases like "yesterday" or "end of last month" count as given. With no date, use the sent date and set as_of_assumed=true. A weekend or holiday rolls back to the previous business day. A future date gets REQUEST_INFO (guess).
5. Settled is the ledger summed over all sub-accounts up to as_of, adjusted for splits up to as_of. get_position_summary is not used.
6. Pending is the sum of matched instructions settling after as_of, skipping any that settle after a split that falls after as_of. pending_date is the latest of their settle dates.
7. If the client gives a figure, compare it with settled + pending. A gap of more than 1% (or more than the rounding in a "k"/"mm" figure) gives ESCALATE.
8. If settled and pending are both 0: NOT_HELD. Otherwise CONFIRMED.

**Inputs:** I analysed the histories with scripts against the tools, and used the unlabeled requests to find cases that separate competing hypotheses. I used all 15 oracle questions. They settled: comparing the client figure against settled + pending, which explains why history case 0006 was escalated; tolerance under 2%; a missing date means the sent date; split adjustment; dropping pending that crosses a split; no materiality threshold for pending; the domain check; legal_hold gives ESCALATE. Harness: 25/25.

**Least sure about:**
- What no_email_confirm leads to.
- Whether legal_hold is checked before or after authorization.
- How future dates are handled.
- The exact tolerance.
- pending_date when several instructions are pending.
- The NOT_HELD field format. My question on this was wasted because I sent the wrong account id.
