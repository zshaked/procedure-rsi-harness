# NOTES
Plan (S1 table, 9 S2 branches, 3 S3 edges = 12 questions) written before asking; copy in scratch/plan.md. 3 unused.

## Rules
- Account text with several hits -> REQUEST_INFO. No account named -> REQUEST_INFO, unless sender unverifiable for every account -> REQUEST_AUTH.
- REQUEST_AUTH: no entitlement on account, entitlement expired before sent, level < 2, or sender domain not in profile domains.
- Then unresolved instrument, no date, or date after sent -> REQUEST_INFO.
- legal_hold or no_email_confirm -> ESCALATE.
- Settled = ledger over all sub-accounts, date <= as_of, rows before a split (split date <= as_of) times ratio. Weekend/holiday dates roll back; month-end = previous month-end.
- Zero and no pending -> NOT_HELD (before client-figure check). Client figure >10% from both settled and settled+pending -> ESCALATE. Else CONFIRMED; pending = matched instructions settling after as_of, pending_date = latest.

## Oracle (12 used; all acceptable except #4)
1 Q4-0032 corporate domain mismatch -> REQUEST_AUTH. Kept.
2 Q4-0171 level 1 -> REQUEST_AUTH. Kept.
3 Q4-0130 empty ledger plus client figure -> NOT_HELD. Kept.
4 Q4-0055 unnamed account -> REQUEST_AUTH: rejected ("didn't say which account, so we ask"). Changed to REQUEST_INFO (rule had one history case); REQUEST_AUTH kept for unverifiable senders (history 0009).
5 Q4-0093 no instrument -> REQUEST_INFO. Kept.
6 Q4-0168 expired -> REQUEST_AUTH. Kept.
7 Q4-0083 future date -> REQUEST_INFO. Kept.
8 Q4-0114 legal hold -> ESCALATE. Kept.
9 Q4-0054 no_email_confirm -> ESCALATE. Kept.
10 Q4-0096 level 1. Kept.
11 Q4-0157 holiday date -> NOT_HELD, rolled back. Kept.
12 Q4-0059 expired. Kept.

## Least sure
10% tolerance (histories bracket 8%-15%; protocol barred asking); claim matched to settled OR settled+pending; pending cutoff; as_of_assumed always false; unnamed account with level-1 sender (Q4-0122); month-end sent late in month; splits between as_of and sent.
