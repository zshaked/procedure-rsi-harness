# NOTES
Rules (order): missing/ambiguous account or instrument (incl. ambiguous short names/old tickers) -> REQUEST_INFO. Then authorization: sender domain must be in the account profile domains AND sender has an unexpired (vs sent date) entitlement level >=2 on that account, else REQUEST_AUTHORIZATION. Then legal_hold / no_email_confirm -> ESCALATE (no_email_confirm is a guess, untested). as_of: parsed date, rolled back to previous business day if weekend/holiday; missing date -> sent date (rolled back), as_of_assumed=True. Settled = ledger sum over all sub-accounts up to as_of, splits applied (split date <= as_of, to rows before the split). Zero -> NOT_HELD (even if client states a figure). Client-stated figure must equal settled (or the unadjusted pre-split sum), else ESCALATE. Pending = sum of matched instructions settling after as_of, pending_date = latest settle date; if pending exists and a figure is stated it must equal settled+pending, else ESCALATE.

Oracle (15 used):
1 Q2-0006 CONFIRMED: rejected (figure escalates); led to pending+stated rule.
2 Q2-0075 weekend + matching figure CONFIRMED: ok (weekend not the cause).
3 Q2-0097 matched pending + stated=settled: rejected -> same rule.
4 Q2-0135 unmatched pending, stated=settled: ok.
5 Q2-0157 ESCALATE with stated but nothing held: rejected -> NOT_HELD precedes figure check.
6 Q2-0128 pre-split stated figure ESCALATE: rejected -> accept raw sum too.
7 Q2-0096 legal hold ESCALATE: ok.
8 Q2-0195 domain mismatch -> AUTH: ok.
9 Q2-0025 pending settling between as_of and sent: ok.
10 Q2-0069 two matched, earliest date: rejected; 11 latest date: ok.
12 Q2-0112 matched settling on as_of not pending: ok.
13 Q2-0055 sent on holiday, assumed date rolled back: ok.
14 Q2-0053 old ticker: ok.
15 Q2-0123 NOT_HELD: ok.

Least sure: no_email_confirm handling; whether a figure equal to settled+pending confirms (vs always escalates); numeric tolerance on stated figures (assumed exact); level-1 entitlements; ordering of INFO vs AUTH.
