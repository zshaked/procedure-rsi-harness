# Notes

## Rules I believe (in order)
1. Account ambiguous/unknown -> INFO. None named -> sender's single entitlement.
2. Sender needs unexpired entitlement level>=3 on that account, else AUTH (before all later checks).
3. Instrument missing/unresolved -> INFO.
4. Date missing -> email date (assumed). Non-business day or future -> INFO.
5. no_email_confirm -> AUTH; legal_hold -> ESCALATE.
6. Settled = ledger over all sub-accounts to as_of inclusive, split-restated. Zero -> NOT_HELD.
7. Settled >= 1,000,000 -> ESCALATE; client figure >5% off settled (or settled+pending) -> ESCALATE.
8. Else CONFIRMED; pending = matched instructions after as_of, only if total >= 1,000.

## Oracle log (15/15)
1. Q3-0031 CONFIRMED 1.2M: no, "that size escalates" -> size rule.
2. Q3-0046 no pending: no -> report far pending.
3. Q3-0046 pending 39,948 (unmatched excluded): yes.
4. Q3-0074 pending 656: no.
5. Q3-0074 pending omitted (client figure = settled+656): yes -> small pending dropped.
6. Q3-0034 Sunday rolled to Friday: no, "not a business day, ask" -> INFO.
7. Q3-0084 no_email account: AUTH yes.
8. Q3-0030 NOENT + Saturday: AUTH yes (auth first).
9. Q3-0132 +2% ESCALATE: no, confirm settled -> tolerance.
10. Q3-0102 +8% ESCALATE: yes.
11. Q3-0062 no account, +8%: inferred account ESCALATE yes.
12. Q3-0051 future date: INFO yes.
13. Q3-0080 zero, client claims shares: NOT_HELD yes.
14. Q3-0033 month-end Saturday: INFO yes.
15. Q3-0022 (history INFO): AUTH yes, so operator error.

## Least sure
- 5% tolerance (only 2% in, 7-8% out known); 1,000,000 size cut (between 887k and 1.056M).
- Pending cut 1,000 (between 802 and 4,632) and aggregation of several instructions.
- legal_hold -> ESCALATE and its order versus date check: untested.
- Splits dated after as_of but before the email: not restated (untested).
- Entitlement expiry compared with email date; negative positions.
