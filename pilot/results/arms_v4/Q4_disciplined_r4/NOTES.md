# NOTES
Rules: unknown contact -> AUTH; ambiguous account -> INFO; no account -> INFO; no entitlement / expired (vs sent) / level<2 / sender domain not in TARGET account's domains -> AUTH; legal_hold -> ESCALATE; no instrument, no date or future date -> INFO; as_of = stated date (previous business day if non-business); settled = ledger sum, all sub-accounts, dated <= as_of, split ratio on rows before a split on/before as_of; pending = matched instructions settling after as_of (latest date); client figure vs settled+pending off by >10% -> ESCALATE; empty position -> NOT_HELD (client figure but no position -> ESCALATE); else CONFIRMED. no_email_confirm ignored.

Plan (branch table, S2/S3 order) was written before asking; S4 excluded well-supported branches.

Oracle, 14 of 15 used:
1 Q0096 L1 sender -> AUTH: ok.
2 Q0141 gmail sender -> AUTH: ok.
3 Q0055 no account named -> INFO: ok.
4 Q0161 empty ledger -> NOT_HELD: ok.
5 Q0168 expired entitlement -> AUTH: ok.
6 Q0083 future date -> INFO: ok.
7 Q0045 no instrument -> INFO: ok.
8 Q0130 figure but no position -> ESCALATE: ok.
9 Q0054 no_email_confirm -> ESCALATE: rejected ("fine to confirm, pending amount and date needed"); removed that branch.
10 Q0114 legal_hold -> ESCALATE: ok.
11 Q0030 level 2 -> CONFIRMED: ok.
12 Q0032 entitled sender, domain not in target's domains -> CONFIRMED: rejected; kept target-domain rule (had briefly tried any-entitled-account domains).
13 Q0059 expired 14d -> AUTH: ok.
14 Q0112 as_of 1 day before sent -> CONFIRMED+pending: ok.

Least sure: 10% tolerance (seen 4% and 7% ok, 15% escalate); as_of_assumed always False; "month-end" = previous month-end; as_of-dated rows included; matched instructions already past as_of excluded; check ordering for legal_hold.
