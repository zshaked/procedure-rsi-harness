# Induced desk procedure (history-only arm)

Rules, in order:
1. Account: `search_accounts(account_text)`; 0 or >1 hits -> REQUEST_INFO (desk never disambiguates via sender). No account named -> use the sender's only entitled account, else REQUEST_INFO.
2. Authorization: sender must be a known contact with an unexpired entitlement of level 3 on that account (domain is irrelevant; level 1/2, expired or missing -> REQUEST_AUTHORIZATION).
3. Instrument missing/unresolved -> REQUEST_INFO. Date: free text parsed relative to `sent`; none -> sent date (as_of_assumed); future or invalid -> REQUEST_INFO; weekend/holiday -> previous business day.
4. Profile: no_email_confirm -> REQUEST_AUTHORIZATION; legal_hold -> ESCALATE.
5. Figure: sum of ledger across ALL sub-accounts with date <= as_of, split-adjusted (not the position summary, which uses primary sub-account and previous business day). Negative or pre-records (<2025-12-15) -> ESCALATE.
6. Client-stated figure that differs from settled (and is not settled + matched pending) -> ESCALATE.
7. 0 -> NOT_HELD; else CONFIRMED, with pending = matched instructions settling after as_of and within ~60 days of the email.

Inputs: 25 histories (24/25 agreement; Q3-0022 treated as operator mistake, unentitled sender should be REQUEST_AUTHORIZATION), unlabeled requests for phrasing coverage and to spot client figures equal to settled+pending, tool docstrings.

Least sure: the pending window (only bounded 34-81 days by histories), whether level 2 ever suffices, ESCALATE vs REQUEST_INFO for future dates and pre-records dates, exact-match vs tolerance on client figures, and ordering of no_email_confirm vs missing-instrument (Q3-0004).
