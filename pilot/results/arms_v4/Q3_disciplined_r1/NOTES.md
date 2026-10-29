# NOTES
Harness 24/25 full (Q3-0022 treated as operator mistake). 15/15 oracle questions used. Plan (S1 table, S2 then S3) was written before asking; see scratch/PLAN_full.md.

## Rules (in order)
Ambiguous account -> INFO. No account named -> infer sole entitlement. Sender needs unexpired level>=3 entitlement on that account, else AUTH. No instrument -> INFO. As-of: none -> email date (assumed); future or non-business day -> INFO. legal_hold -> ESCALATE; no_email_confirm -> AUTH. Settled = ledger sum over all sub-accounts up to as-of, split-restated only if split date <= as-of. Zero -> NOT_HELD even if client claims a figure. Claim off by >3% from settled (or settled + matched pending) -> ESCALATE. Else CONFIRMED, plus matched pending settling within 45 days of the email.

## Oracle log (case: verdict -> effect)
1 0158 ok (-15% ESCALATE).
2 0080 ok (zero beats claim).
3 0062 rejected, ESCALATE expected -> infer account from sole entitlement (changed).
4 0084 ok (no_email_confirm -> AUTH).
5 0123 ok (pending 20 days out).
6 0053 ok (expiry judged at email date).
7 0051 ok (future date -> INFO).
8 0085 rejected, "not a business day, ask" -> rollback replaced by INFO; flags checked after date (changed).
9 0034 ok (Sunday -> INFO).
10 0041 rejected INFO ("no as-of date"): unexplained; rule had two oracle plus one history support (R2), unchanged.
11 0148 ok (split before email, after as-of: not restated).
12 0132 rejected CONFIRMED at +2% ("wrong account"): unexplained, no change.
13 0175 ok (+4% ESCALATE).
14 0076 ok (month-end Saturday -> INFO).
15 0198 ok (no date, holiday email -> INFO).

## Least sure
Tolerance anywhere in [2%,4%) (Q12 contradicts). Pending horizon (20-81 days; 45 is a guess). Auth-before-date order (Q3-0010/0014 vs 0022). Claim equal to settled+pending (never tested). Negative positions, multi-entitlement senders untested.
