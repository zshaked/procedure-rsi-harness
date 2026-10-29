# NOTES (full pre-registered plan and branch table: scratch/PLAN.md)

**Rules believed**
1. Unknown sender, or domain not registered for the account (ambiguous name: for any candidate; no account named: any entitled account), or no live entitlement of level >=2 on the sent date: REQUEST_AUTHORIZATION.
2. Ambiguous or missing account, missing or unresolved security, missing or future date: REQUEST_INFO.
3. Legal hold: ESCALATE.
4. as_of = stated date rolled back to previous business day; as_of_assumed always false. Settled = all sub-accounts up to as_of, split-adjusted. Pending = matched instructions settling after as_of (latest date).
5. Client figure >10% off settled or settled+pending: ESCALATE. No ledger line: NOT_HELD. Else CONFIRMED.

**Oracle questions (15/15)**
1 Q32 ok. 2 Q42 ok.
3 Q64 NOT_HELD rejected ("entitlement not high enough"): unchanged (L2 rule has >=2 history cases; one contradiction, R2).
4 Q43 rejected (domain): ambiguous name plus unregistered domain now REQUEST_AUTHORIZATION.
5 Q187 ok.
6 Q93 INFO rejected (wants CONFIRMED with pending): unchanged; no tool lists positions.
7 Q168 ok. 8 Q83 ok.
9 Q55 rejected ("didn't say which account"): missing account now REQUEST_INFO.
10 Q130 NOT_HELD rejected ("wrong security"): unexplained, unchanged.
11 Q114 ok.
12 Q54 ESCALATE rejected (wants CONFIRMED with pending): no_email_confirm flag now ignored.
13 Q60 ok. 14 Q147 ok. 15 Q59 ok.

**Least sure**
NOT_HELD (two rejections, different reasons), missing-security requests, the 10% tolerance and settled-versus-total basis (not asked; S4), pending_date choice, what no_email_confirm does.
