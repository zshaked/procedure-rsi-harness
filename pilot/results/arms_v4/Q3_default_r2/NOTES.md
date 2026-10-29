# NOTES

## Rules (first that fires wins)
1. Account: named (id/sub-account/name/short name); none named -> sender's single entitled account; ambiguous/unresolved -> REQUEST_INFO (no entitlement-based disambiguation).
2. Sender needs unexpired entitlement level >=3 on it, else REQUEST_AUTHORIZATION (precedes everything below).
3. Instrument missing/unresolved -> REQUEST_INFO.
4. Date: none -> email date (assumed); weekend/holiday (incl. "yesterday", month-end) or future -> REQUEST_INFO.
5. no_email_confirm -> REQUEST_AUTHORIZATION; legal_hold -> ESCALATE (guess).
6. Settled = ledger, all sub-accounts, date <= as_of, splits effective by as_of applied. Zero -> NOT_HELD; client figure >5% off -> ESCALATE; else CONFIRMED.
7. Pending = matched instructions settling after as_of, qty >= 1000 (dust ignored), no horizon; sum + earliest date.

## Oracle (15 used)
1. Q0034 CONFIRMED rolled back from Sunday: no, non-business date -> ask. Added rule 4.
2. Q0010 REQ_AUTH (Sunday date): yes -> auth first.
3. Q0022 REQ_AUTH: no ("wrong as-of date"), unexplained; kept.
4. Q0063 REQ_AUTH: yes.
5. Q0024 REQUEST_INFO (no account): no, client takes no email confirmations -> infer account; rule 5.
6. Q0123 (I mistyped the instrument): wasted.
7. Q0050 REQ_AUTH (relative weekend date): yes.
8. Q0080 ESCALATE (claims 1447, none held): no -> NOT_HELD first.
9. Q0074 ESCALATE (claim = settled+656): no, fine to confirm -> tolerance.
10. Q0018 with pending 684: no -> dust excluded.
11. Q0074 CONFIRMED, no pending: yes.
12. Q0132 ESCALATE (2% off): no -> tolerance (5% is a guess; 7% escalated in history).
13. Q0123 pending 13615 (+20d): yes.
14. Q0046 no pending: no -> large pending reported at +68d, no horizon.
15. Q0033 REQUEST_INFO (Saturday month-end): yes.

## Least sure
Q0022 anomaly; tolerance size; dust threshold (1000 vs up to 10000); future dates; legal hold; holiday email date with no date given; split boundary (as_of before split date unadjusted); negative positions.
