# NOTES
Plan (S1-S5, fixed before asking): S2 branches qty_mismatch, auth_expired, confirm_pending, not_held, no_email_confirm, future_date, legal_hold; then S3 edges (split, roll, account inference, tolerance, zero-holding claim, ledger==as_of, expiry). 15 slots.

Rules: resolve account (ambiguous/unknown -> INFO; omitted -> sender's sole entitlement). Sender best level <3 -> AUTH. Non-business date (stated or assumed sent date) -> INFO. No entitlement on account / lapsed -> AUTH. Instrument missing -> INFO. Future date -> INFO. no_email_confirm -> AUTH; legal_hold -> ESCALATE. Settled = ledger sum over all sub-accounts, date<=as_of, split-adjusted only if split<=as_of. Settled>=1,000,000 -> ESCALATE. Zero -> NOT_HELD. Client figure must equal settled or settled+matched pending, else ESCALATE. Pending = matched, as_of<settle<=sent+30d.

Oracle (15 used):
1 Q3-0074 ESCALATE: no, "fine to confirm" -> claim may include pending.
2 Q3-0053 AUTH (expired): ok.
3 Q3-0123 CONFIRMED+pending: ok.
4 Q3-0198 NOT_HELD on holiday sent date: no, ask date -> non-business -> INFO (also fixes history Q22).
5 Q3-0084 AUTH: ok.
6 Q3-0051 INFO (future): ok.
7 Q3-0085 INFO (non-bd): ok.
8 Q3-0148 no split adjust: ok.
9 Q3-0145 CONFIRMED 2.79M: no, large positions escalate -> added 1M rule.
10 Q3-0034 INFO (Sunday): ok.
11 Q3-0127 INFO (Saturday): ok.
12 Q3-0072 INFO (Saturday): ok.
13 Q3-0080 ESCALATE (claim vs zero): no, NOT_HELD.
14 Q3-0165 ESCALATE: ok.
15 Q3-0032 NOT_HELD: no, entitlement lapsed (expiry +68d) -> 90-day margin.

Least sure: large-position threshold (1M guess, raw vs split-adjusted); expiry margin (90d guess, may be noise); pending window (30d, base sent vs as_of); account inference untested; legal_hold branch untested; whether pending is reported when claim includes it.
