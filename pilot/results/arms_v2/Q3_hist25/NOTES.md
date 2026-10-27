# Induced desk procedure

Rules, applied in this order:
1. **Account.** Resolve `account_text` with search_accounts. If there are 0 or several matches (for example a "Brightwater Advisors" prefix that hits I/II/III), return REQUEST_INFO, even when the sender is entitled to one of them. If no account is named ("our fund"), use the sender's single live entitlement; otherwise REQUEST_INFO.
2. **Authorization.** The sender must be a known contact with an unexpired entitlement at level >= 3 on that account. Otherwise REQUEST_AUTHORIZATION. This check comes before the missing-instrument check (Q3-0015). Sender domain is ignored (Q3-0023 came from yahoo and was answered).
3. **Instrument.** The instrument must resolve to exactly one record (ticker, old ticker, name or ISIN). Otherwise REQUEST_INFO. An unparseable or future date also gets REQUEST_INFO.
4. **Profile.** `no_email_confirm` gives REQUEST_AUTHORIZATION (Q3-0024). `legal_hold` gives ESCALATE.
5. **Figure.**
   - as_of is the stated date, or the sent date (as_of_assumed=true) when none is given. If as_of is not a business day, it rolls back to the previous business day.
   - settled is the sum of ledger qty across ALL sub-accounts with date <= as_of. Each entry is multiplied by a split ratio when the split date falls after the entry and on or before as_of.
   - get_position_summary is not used: it covers the primary sub-account only and the previous business day.
   - If the client quotes its own figure and it differs from settled, return ESCALATE (Q3-0012). If settled is 0, return NOT_HELD. Otherwise CONFIRMED.
6. **Pending.** Matched instructions with as_of < settle_date <= sent + 10 business days. pending is their total qty and pending_date is the latest settle_date.

Least sure of:
- The pending window. Only Q3-0008 shows one; Q3-0018 and Q3-0020 show that far-dated instructions are left out.
- Weekend roll-back of as_of.
- The order of no_email_confirm vs missing info, and that legal_hold means ESCALATE (no direct example).
- Q3-0022 (not entitled, got REQUEST_INFO) is treated as an operator mistake.
