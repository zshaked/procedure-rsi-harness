# NOTES (harness 25/25 full; oracle 15/15 used; full pre-ask plan: scratch/plan_full.md)

Rules: REQUEST_AUTHORIZATION if sender unknown, no entitlement on the asked account, domain not registered for that account (no unique account named: not registered for any of his accounts), expired (expires < sent) or level < 2. Ambiguous or missing account/instrument/date, or date after sent -> REQUEST_INFO. Legal hold -> ESCALATE. Position = ledger over all sub-accounts dated <= as_of (non-business day rolled back), pre-split lots times ratio when split <= as_of; pending = matched instructions settling after as_of. Zero settled and pending -> NOT_HELD. Client figure off settled+pending by >10% -> ESCALATE; else CONFIRMED. as_of_assumed always false.

Plan (S2 nine branches, then S3 six edges) was written before asking.
Questions (each submitted my own output):
1 Q4-0042 level 1 -> AUTH: ok
2 Q4-0055 no account -> REQUEST_INFO: ok
3 Q4-0064 empty ledger -> NOT_HELD: ok
4 Q4-0083 future date -> REQUEST_INFO: ok
5 Q4-0093 no instrument -> REQUEST_INFO: ok
6 Q4-0190 expired -> AUTH: ok
7 Q4-0130 empty ledger plus client figure, ESCALATE: rejected ("doesn't hold") -> NOT_HELD
8 Q4-0054 no_email_confirm, ESCALATE: rejected ("fine to confirm", with pending) -> flag ignored
9 Q4-0114 legal hold -> ESCALATE: ok
10 Q4-0032 cross-entitled sender: rejected (domain not registered)
11 Q4-0062 same: rejected -> R2 met, domain check now per asked account (took the slot of Q4-0126, redundant after Q8)
12 Q4-0049 former ticker: ok
13 Q4-0077 8% off: ok
14 Q4-0030 expiry 48 days after sent: ok
15 Q4-0155 figure near settled only, pending present: rejected -> compare with settled+pending

Least sure: tolerance between 8% and 15%; negative positions; ledger entry dated exactly as_of (included); split dated between as_of and sent; expiry on the sent day; legal hold versus missing slots order.
