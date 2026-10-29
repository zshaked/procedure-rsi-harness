# Notes (procedure.py, harness 25/25 full)

Rules: resolve account (several matches or none -> REQUEST_INFO, but AUTH if sender has no live domain-matched entitlement). Auth: contact known, live entitlement (expires >= sent), level >= 2, sender domain in client domains, else REQUEST_AUTHORIZATION. legal_hold -> ESCALATE; no_email_confirm ignored. Missing instrument/date/future date -> REQUEST_INFO. Date: non-business day -> previous business day; month-end = last day of prior month. Settled = ledger sum to as_of, split-adjusted. Pending = matched instructions settling after as_of, summed, latest date. No holding -> NOT_HELD. Client figure vs settled+pending beyond 10% -> ESCALATE. as_of_assumed always false.

Plan (written first): S2 branches by unlabeled count: auth_domain, auth_level, confirmed_pending, account_missing, not_held, auth_expired, instrument_missing, future_date, claim_total, no_email_confirm, not_held_claim, claim_settled_pending, legal_hold; S3: pending boundary (Q126), expiry boundary (Q59). Tolerance edges S4-excluded.

Oracle (15 used; one was an accidental repeat of Q54, so Q59 was never asked):
1 Q32 domain mismatch -> AUTH ok.
2 Q42 level 1 -> AUTH ok.
3 Q84 pending_date latest ok.
4 Q55 no account named, authorized sender: AUTH rejected ("we ask"); now REQUEST_INFO.
5 Q51 NOT_HELD ok.
6 Q168 expired -> AUTH ok.
7 Q93 no instrument -> REQUEST_INFO ok.
8 Q83 future date -> REQUEST_INFO ok.
9 Q183 figure = settled+pending ok.
10 Q54 flagged no_email_confirm: ESCALATE rejected; confirm with pending; flag now ignored.
11 Q130 empty ledger with client figure: ESCALATE rejected; NOT_HELD.
12 Q155 figure near settled, large pending: CONFIRMED rejected; compare with settled+pending only.
13 Q114 legal_hold ESCALATE ok.
14 Q4-0054 repeat (accident).
15 Q126 pending 3 days after as_of ok.

Least sure: 10% tolerance (evidence 8% pass, 15% fail); account-missing/ambiguous with unauthorized sender (AUTH, from one history case); expiry boundary; old tickers resolve; pending when as_of is on or after a split.
