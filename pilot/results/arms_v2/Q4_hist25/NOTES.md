# Induced desk procedure

**Order of checks**
1. Resolve the account (id, sub-account, name or short name, with prefix fallback) and the instrument (ticker, old ticker, name or ISIN).
2. **Authorization.** If the account resolves to exactly one, the sender must be a known contact, on a non-free-mail domain listed in that client's profile, with an unexpired entitlement of level >= 2 on that account. Otherwise the outcome is REQUEST_AUTHORIZATION. If the account is missing or ambiguous: a free-mail, unknown or foreign-domain sender gets REQUEST_AUTHORIZATION, and anyone else gets REQUEST_INFO. The desk does not use entitlements to pick between ambiguous accounts.
3. A missing or ambiguous instrument, or a missing date, gives REQUEST_INFO.
4. If the client is on legal hold or has no_email_confirm set, the outcome is ESCALATE. This is assumed; no history shows it.
5. **Settled figure.** Sum the ledger across *all* sub-accounts with date <= as_of. Transactions dated before a split that is effective by as_of are multiplied by the split ratio. as_of is the requested date, rolled back to the previous business day if it is not one. get_position_summary is not used: it covers only the primary sub-account, always steps back a day and ignores splits. A settled figure of 0 gives NOT_HELD.
6. If the client states a figure that differs by more than 10% from settled, and also from settled+pending, the outcome is ESCALATE.
7. Otherwise the outcome is CONFIRMED. Pending is the sum of *matched* instructions with settle_date > as_of, and pending_date is the latest of those settle dates.

Forwarded-header lines and disclaimers are removed before parsing dates.

**Least sure about**
- The 10% tolerance. The histories only show 4% and 7% differences confirmed and 15% escalated.
- as_of_assumed: I set it true only for vague or relative dates such as month-end or today.
- How no_email_confirm is handled.
- Whether NOT_HELD takes precedence over a mismatching client figure.
- Whether the pending cutoff is as_of or the date the email was sent.
