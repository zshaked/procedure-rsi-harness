# Notes

Rules inferred:
1. Resolve account (ambiguous name -> REQUEST_INFO) and instrument (ticker/old ticker/name/ISIN).
2. Sender needs contact + entitlement on the account (level>=2, unexpired) + domain in profile; else REQUEST_AUTHORIZATION (freemail always fails). Checked before legal hold.
3. legal_hold -> ESCALATE. no_email_confirm: no effect.
4. Missing account/instrument/date, or future as-of -> REQUEST_INFO (never assume a date).
5. As-of = stated date rolled back to previous business day; relative phrases use sent date.
6. settled = all-sub-account ledger up to as-of, pre-split rows times ratio. Zero -> NOT_HELD; negative -> ESCALATE.
7. Pending = matched instructions with settle_date > as-of (sum, latest date).
8. Client figure vs settled+pending: beyond 10% -> ESCALATE.

Oracle (15):
1 Q4-0114 hold ESCALATE ok.
2 Q4-0054 no_email_confirm ESCALATE rejected: confirm with pending -> dropped flag.
3 Q4-0118 unauthorized+hold AUTH ok.
4 Q4-0104 figure +8% CONFIRMED ok.
5 Q4-0094 figure -7% CONFIRMED ok.
6 Q4-0130 zero holding vs figure ESCALATE rejected -> NOT_HELD.
7 Q4-0028 no date, assumed CONFIRMED rejected -> INFO.
8 Q4-0083 future date INFO ok.
9 Q4-0128 ambiguous account AUTH rejected -> INFO.
10 Q4-0131 account missing INFO rejected (odd reason).
11 Q4-0131 inferred account CONFIRMED rejected: "ask which account"; kept INFO.
12 Q4-0084 two pendings ok.
13 Q4-0155 figure ~settled, big pending: rejected -> compare to settled+pending.
14 Q4-0032 entitled, wrong domain AUTH ok.
15 Q4-0156 past-dated matched instruction not pending ok.

Least sure: tolerance edge (8-15%), "month-end" sent on a month-end day, INFO field filling, Q4-0131 inconsistency.
