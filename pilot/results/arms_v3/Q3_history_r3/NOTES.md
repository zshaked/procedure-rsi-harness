# Induced desk procedure (history-only arm)

Rules, in order:
1. Resolve account via `search_accounts(account_text)`; 0 or >1 hits -> REQUEST_INFO (no disambiguation by entitlement). If no account is mentioned, infer it from the sender's single unexpired entitlement, else REQUEST_INFO.
2. Authorization = sender contact has an unexpired entitlement to that account at level 3. Otherwise REQUEST_AUTHORIZATION (levels 1-2 fail). Sender domain is not checked (Q3-0023, a yahoo sender, was answered).
3. Instrument missing/unresolved -> REQUEST_INFO.
4. Profile: legal_hold -> ESCALATE; no_email_confirm -> REQUEST_AUTHORIZATION.
5. Date: free-text parse (ignoring forwarded `Date:` headers). No date -> sent date, as_of_assumed=true. Future/invalid -> REQUEST_INFO. Weekends/holidays roll back to the previous business day.
6. Settled = ledger summed over ALL sub-accounts up to as_of inclusive, split-adjusted (not `get_position_summary`, which uses the primary sub-account and the prior day).
7. A client-stated figure off by more than 5% from settled (and from settled+matched pending) -> ESCALATE.
8. Negative -> ESCALATE; zero -> NOT_HELD; otherwise CONFIRMED. Pending = matched instructions settling after as_of and within 30 days of the email.

Inputs: 25 histories for the ordering and outcomes. The 175 unlabeled requests were used to find date/quantity phrasings and the figure-deviation factors (exact, x1.02/1.04, x0.85/0.93/1.08/1.5).

Least sure: the 5% tolerance; the pending window (0008 reported, 0018/0020 omitted); legal_hold -> ESCALATE; account inference (only Q3-0024); treating Q3-0022 as an operator mistake.
