# NOTES (plan written before asking; full copy in scratch/plan_full.md)

Rules: resolve account (missing/ambiguous -> REQUEST_INFO). Sender needs unexpired (vs sent date) entitlement level>=2 for that account and a client email domain, else REQUEST_AUTHORIZATION. Then missing instrument -> REQUEST_INFO; legal_hold/no_email_confirm -> ESCALATE. as_of: stated date (US M/D; relative phrases from sent), non-business rolls back, absent = sent date (assumed). settled = all sub-accounts up to and including as_of, split-adjusted; zero -> NOT_HELD. pending = matched instructions settling after as_of (sum, earliest date). Stated figure must equal settled+pending, else ESCALATE.

Oracle (14 of 15):
1 Q2-0106 auth_domain REQUEST_AUTH: ok.
2 Q2-0187 auth_level: ok.
3 Q2-0041 REQUEST_INFO: rejected (entitlement too low); authorization now precedes missing-instrument check.
4 Q2-0037 INFO: ok.
5 Q2-0197 NOT_HELD: rejected ("not a business day", but it is a Wednesday); unchanged, treated as oracle error (see 13).
6 Q2-0096 legal hold ESCALATE: ok.
7 Q2-0121 expired: ok.
8 Q2-0076 pending 601: rejected ("pending amount"); guessed split between as_of and settlement multiplies pending (601 to 1803).
9 Q2-0025 matched pending only: ok.
10 Q2-0097 stated=settled with pending: rejected (escalation). R2: rule had two supporters, logged, no change yet.
R2 follow-up Q2-0051 (stated = settled+pending, CONFIRMED): ok. Second contradiction, so comparison now uses settled+pending (also fixes Q2-0006).
11 Q2-0089 multiple pending: ok.
12 Q2-0145 auth before legal hold: ok.
13 Q2-0157 NOT_HELD, "yesterday", not assumed: ok.

Least sure: pending split rule (Q2-0069 untested); no_email_confirm outcome; Q2-0197 anomaly; plain-number tolerance (exact assumed); k/mm parsing; future dates; holiday send dates.
