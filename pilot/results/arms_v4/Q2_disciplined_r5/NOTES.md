# NOTES
Plan (S2 then S3, written before asking; S4 excluded auth/unresolved/qty_mismatch): Q2-0153 not_held, Q2-0096 legal_hold, 0077 holiday, 0191 "yesterday" flag, 0076/0069 split edges, 0112/0025 pending threshold, 0097 stated vs settled+pending, 0089 multi-pending, 0135 unmatched.
Branches hist/unl: auth 7/53, unresolved 4/44, confirm 5/41, qty_mismatch 7/23, confirm_pending 2/11, not_held 0/2, legal_hold 0/1.

Rules: unique account+instrument else REQUEST_INFO; auth = sender domain in profile domains + entitlement on account, level>=2, unexpired, else REQUEST_AUTHORIZATION; legal_hold -> ESCALATE; as_of = parsed date (non-business day -> previous business day), none -> sent date, assumed=true; settled = all sub-accounts summed to as_of, split-adjusted if split date<=as_of; zero -> NOT_HELD; pending = matched, settle>as_of, summed, latest date, ignored if <1000; client figure must equal settled+pending else ESCALATE.

Oracle (all acceptable unless noted):
1 0153 NOT_HELD, sub-account text = whole account: ok. 2 0096 legal hold ESCALATE: ok. 3 0077 holiday->prev bd: ok. 4 0191 yesterday, assumed false: ok.
5 0076 pending 601: REJECTED (amount). 6 0069 sum + earliest date: REJECTED (date) -> latest date.
7 0112 settle==as_of not pending: ok. 8 0025 pending kept, unmatched excluded: ok. 9 0089 sum+latest: ok.
10 0097 stated=settled but pending exists: REJECTED -> compare to settled+pending (also fixes history Q2-0006).
11 0135 unmatched excluded: ok. 12 0140 no-date with pending: ok. 13 0076 pending x3: rejected. 14 0076 pending omitted: ok. 15 0190 348 pending omitted: ok -> de minimis rule.

Least sure: de minimis threshold (1000 is a guess; absolute vs relative), exact-match tolerance, expiry compared to sent date, domain rule (one history case), no_email_confirm outcome (guessed ESCALATE), legal_hold precedence vs auth.
