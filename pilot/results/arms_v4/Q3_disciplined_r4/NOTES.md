# NOTES

Final harness full agreement: 24/25 (Q3-0022 is the lone miss, likely an operator mistake). Oracle questions used: 15/15.

## Rules believed
Order: ambiguous account -> REQUEST_INFO; no account named -> infer sole entitlement; entitlement for account, level>=3, unexpired at sent date, else REQUEST_AUTHORIZATION; missing instrument -> INFO; date not a business day -> INFO; no_email_confirm account -> AUTHORIZATION; legal_hold -> ESCALATE (untested); settled (all sub-accounts, ledger <= as_of inclusive, splits applied only if split date <= as_of) = 0 -> NOT_HELD; client figure more than ~5% off settled (not settled+pending) -> ESCALATE; settled >= 1,000,000 -> ESCALATE; else CONFIRMED, with matched pending settling within 30 days of sent. No date -> sent date, assumed=True.

## Plan (S2 then S3) and answers
1 Q0102 higher client figure, ESCALATE: yes. 2 Q0062 no account, AUTH: NO (account inferred; mismatch escalates) -> added inference; Q0024 re-explained by no_email_confirm. 3 Q0193 stale pending: yes. 4 Q0084 no_email_confirm AUTH: yes. 5 Q0080 figure vs zero holding, ESCALATE: NO (NOT_HELD) -> zero check first. 6 Q0032 NOT_HELD: yes. 7 Q0076 total-match CONFIRMED: NO (Saturday date -> INFO) -> non-business date INFO. 8 Q0085 legal hold: INFO yes (date check precedes). 9 Q0053 expired: yes. 10 Q0034 Sunday: INFO yes. 11 Q0145 split inside, CONFIRMED: NO (positions that size escalate) -> 1M threshold guessed. 12 Q0148 yes. 13 Q0072 INFO yes. 14 Q0132 2% off ESCALATE: NO (confirm) -> 5% tolerance. 15 Q0110 INFO yes.
Cut by cap: future as_of (Q0051), no-date non-business sent day (Q0198).

## Least sure
Size threshold (between 855k and 2.79M), tolerance (2-7%), pending window (7-42 days, never tested), split adjustment inside as_of (never verified), legal_hold outcome, future dates.
