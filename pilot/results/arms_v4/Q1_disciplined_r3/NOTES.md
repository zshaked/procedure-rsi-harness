# NOTES
Plan (written before asking; branch hist/unl): auth_level 6/48, account_unresolved 3/43, confirmed 4/21, no_entitlement 3/16, date_nonbusiness 3/16, auth_domain 3/11, instrument_unresolved 1/8, date_missing 1/4, no_ledger 1/3, date_future 0/2, legal_hold 0/1, no_email_confirm 0/1, zero_position 0/1. S2 then S3, 15 cases.

Questions (case: answer -> change):
1 Q0090 INFO (no instrument, level 2): no -> auth check now precedes instrument INFO.
2 Q0152 INFO (no date): yes.
3 Q0028 INFO (empty ledger): no, not held -> empty/zero settled = NOT_HELD (history Q0019 an error).
4 Q0198 INFO (future date): yes.
5 Q0111 ESCALATE (legal hold, Saturday): no, ask date -> date checks precede hold.
6 Q0064 ESCALATE (no_email_confirm, no date): no -> same.
7 Q0134 NOT_HELD (net zero): yes.
8 Q0195 AUTH (expired 49d): yes.
9 Q0092 CONFIRMED ("yesterday", assumed=false, expiry +12d): yes.
10 Q0128 split 1 day after as_of, unadjusted: yes.
11 Q0121 split earlier, adjusted: yes.
12 Q0095 matched pending settling after as_of, before sent: yes.
13-14 Q0120, Q0137 CONFIRMED: no, client figure mismatch goes to escalation -> added figure check: stated vs settled (or settled+pending) within 5%, else ESCALATE. Stated/ours ratios in data: 1.00/1.02/1.04 ok; 0.93/1.08/0.85/1.5 mismatch.
15 Q0164 INFO ("yesterday" Sunday): yes.

Rules: unresolved/ambiguous account INFO; no entitlement on account INFO; level>=3, unexpired at sent, sender domain in profile, else AUTH; no instrument INFO; missing/future/non-business date INFO; hold flags ESCALATE; settled 0 NOT_HELD; figure mismatch ESCALATE; else CONFIRMED (all sub-accounts, entries <= as_of, split applied if split <= as_of; pending = matched, settling after as_of, latest date).

Least sure: no_entitlement INFO vs AUTH (Q0008 disagrees); 5% tolerance (4% ok, 7% not); pre-split client figures assumed mismatch; hold flags never confirmed; as_of==sent; unknown sender.
