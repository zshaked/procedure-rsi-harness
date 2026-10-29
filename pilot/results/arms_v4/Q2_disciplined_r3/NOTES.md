# NOTES (full pre-question plan: scratch/PLAN.md; S2 then S3 order, 15 cases)

Rules: account missing/ambiguous -> REQUEST_INFO (exact name beats family prefix). Authorise before anything about the security: known contact, entitlement unexpired, level>=2, sender domain in client domains, else REQUEST_AUTHORIZATION. No security -> REQUEST_INFO. Legal hold -> ESCALATE. as_of = stated/relative date (none: sent date, assumed), rolled back to prior business day. Settled = all sub-accounts <= as_of, split-adjusted; zero -> NOT_HELD. Pending = matched instructions settling after as_of (sum, latest date). Client figure != settled -> ESCALATE; pending > settled -> ESCALATE.

Oracle (case: verdict -> change):
1 0106 domain: ok.
2 0051 CONFIRMED rejected ("size") -> settled-only comparison plus pending-size escalation.
3 0078 level 1: ok.
4 0071 no security: ok.
5 0047 no account: ok.
6 0197 ESCALATE rejected -> zero holding is NOT_HELD even with a figure.
7 0153 NOT_HELD rejected ("security not named", false) -> treated as oracle error, no change.
8 0121 expired: ok.
9 0096 hold: ok.
10 0112 settle==as_of not pending: ok.
11 0025 pending vs as_of, unmatched excluded: ok.
12 0089 ESCALATE rejected (confirm with pending) -> R2: one contradiction, unchanged.
13 0069 earliest pending date wrong -> latest.
14 0086 level 2: ok.
15 0041 REQUEST_INFO rejected (entitlement) -> authorisation before security check.

Least sure: pending-size threshold (1.0 kept; data fit 1.33<ratio<=1.75); 0153 net-zero via sub-account; no_email_confirm (-> REQUEST_AUTHORIZATION, untested); future date -> REQUEST_INFO; splits applied if dated <= as_of.
