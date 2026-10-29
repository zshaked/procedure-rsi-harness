# NOTES
Plan (written before asking): S2 by unlabeled count: Q1-0133 account_ambiguous, Q1-0090 instrument_missing, Q1-0131 not_held, Q1-0143 no_date, Q1-0195 auth_expired, Q1-0121 split, Q1-0064 no_email_confirm, Q1-0111 legal_hold. S3: Q1-0025 month-end, Q1-0059 end-of-last-month, Q1-0164 yesterday-on-Monday, Q1-0080 no-entitlement, Q1-0102 as_of_assumed, Q1-0063/Q1-0092 expiry edges. S4-skipped: auth_level, auth_domain, confirmed, confirmed_pending, nonbusiness_date, account_missing.

Rules: resolve account (ambiguous/missing -> INFO); contact, entitlement row on that account, level>=3, unexpired at sent, sender domain in profile -> else REQUEST_AUTHORIZATION; then instrument (missing -> INFO); no date or non-business date -> INFO; legal_hold/no_email_confirm -> ESCALATE; settled = ledger up to as_of, split-adjusted; zero -> NOT_HELD; pending = matched instructions settling after as_of (sum, latest date). Never use get_position_summary.

Oracle (15 budget, 15 used):
1 Q1-0133 ambiguous account -> INFO: ok.
2 Q1-0090 instrument missing, level-2 sender -> INFO: rejected (auth first); moved instrument check after auth.
3 Q1-0131 empty ledger -> NOT_HELD: ok (Q0019 likely operator error).
4 Q1-0143 no date -> INFO: ok.
5 Q1-0195 expired entitlement -> AUTH: ok.
6 Q1-0121 split-adjusted figure: ok.
7 Q1-0064 ESCALATE with no date: rejected; date checks precede escalate.
8 Q1-0111 ESCALATE on Saturday date: rejected; same change.
9-11 Q1-0025, 0059, 0164 weekend month-end/yesterday -> INFO: ok.
12 Q1-0080 no entitlement on account -> INFO: rejected (AUTH). Per R2 (Q0005, Q0022 supported INFO) logged, no change.
13 Q1-0032 same rule, second contradiction -> changed to AUTH.
14 Q1-0102 no date, assume prev bd with as_of_assumed=true: rejected; flag always false.
15 Q1-0092 expiry +12d CONFIRMED yesterday: ok.
Q1-0063 (confounded expiry-low) was dropped for the R2 follow-up (item 13).

Least sure: ESCALATE field content and ordering vs figure (never validated on a clean case); pending when instruction settles on/before as_of; split edge dates; Q0005/Q0022 now disagree.
