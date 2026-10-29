# NOTES

## Rules believed (procedure.py)
1. Account: ambiguous/unknown -> REQUEST_INFO; "our fund" -> sender's sole live entitlement.
2. Sender best live level <3 -> REQUEST_AUTHORIZATION.
3. Unknown/missing instrument, future or non-business as_of -> REQUEST_INFO.
4. No level-3 entitlement on this account -> AUTH; no_email_confirm -> AUTH; legal_hold -> ESCALATE (guess).
5. settled = ledger over all sub-accounts, date <= as_of, split-adjusted only for splits effective <= as_of (get_position_summary is a trap).
6. Zero -> NOT_HELD (even if client states a figure); >=1,000,000 -> ESCALATE; client figure off >5% (vs settled or settled+matched) -> ESCALATE; else CONFIRMED. Pending = matched instructions settling 0-30 days after the email.

## Oracle log (15 used)
1. Q3-0107 Saturday as_of rolled back: rejected, non-business date -> REQUEST_INFO.
2. Q3-0074 pending 656 at +34d: rejected; window.
3. Q3-0046 no pending at +68d: accepted.
4. Q3-0123 pending 13615 at +20d: rejected with unrelated "doesn't hold" (noise?).
5. Q3-0123 no pending: rejected on pending; report at 20d, window 30.
6. Q3-0051 future date REQUEST_INFO: accepted.
7. Q3-0145 split-adjusted CONFIRMED: rejected, size escalation.
8. Q3-0148 split day after as_of not applied: accepted.
9. Q3-0031 1.2M ESCALATE: accepted; threshold 1M.
10. Q3-0084 no_email_confirm AUTH: accepted.
11. Q3-0080 zero holding + client figure, ESCALATE: rejected -> NOT_HELD.
12. Q3-0132 +2% ESCALATE: rejected -> 5% tolerance.
13. Q3-0030 AUTH for level-3 sender, other account, Saturday: rejected; date check precedes account entitlement.
14. Q3-0050 level-2 sender, Saturday, AUTH: accepted; low level checked before date.
15. Q3-0045 level-2 elsewhere, Sunday, AUTH: rejected but reason said authorization; treated as noise.

Q3-0022 (history) now agrees; Q3-0010/0014/0015 explained by the level-first order.

## Least sure
Exact tolerance (2-7%) and pending window (20-33d); past-dated pending; legal_hold outcome; assumed date when email sent on a holiday; old-ticker handling; level-2 sender without entitlement on the account (item 15).
