# Induced desk procedure

Rules, in order:
1. **Account.** Resolve the cleaned mention with `search_accounts`. Several matches or none: REQUEST_INFO. No mention: use an ACC-/SA- id in the body, else the sender's only unexpired entitlement.
2. **Authorization.** The sender needs a level-3, unexpired entitlement on the account, else REQUEST_AUTHORIZATION. The email domain is ignored.
3. **Instrument.** Missing, ambiguous or unknown: REQUEST_INFO.
4. **Date.** In the future or not a business day: REQUEST_INFO. No date: use the sent date and set as_of_assumed=true.
5. **Profile.** no_email_confirm: REQUEST_AUTHORIZATION. legal_hold: ESCALATE.
6. **Figures.** settled is the sum of ledger rows across all sub-accounts with date ≤ as_of. A row is multiplied by the split ratio if it is recorded before a split dated ≤ as_of. `get_position_summary` is not used: it covers only the primary sub-account and the previous business day. Negative settled, or a client-stated figure that differs: ESCALATE. Zero: NOT_HELD. Otherwise CONFIRMED.
7. **Pending.** pending is the sum of matched instructions with settle_date > as_of and qty ≥ 1000. pending_date is the latest of their settle dates.

# What I am least sure of
- The 1000 pending threshold. Instruction quantities fall into two groups split at about 1000. A settle-date window would also fit.
- Whether authorization comes before the date check. The histories split 3 to 2.
- Q3-0031 was escalated for no reason I can find. It could be a mistake or a review rule for positions over 1mm.
- Dates before the ledger starts on 2025-12-15, and how to combine several pending instructions.
