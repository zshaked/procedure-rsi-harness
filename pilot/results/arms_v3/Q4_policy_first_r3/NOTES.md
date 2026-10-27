# NOTES

**Rules I believe the desk follows:**
1. Account must resolve uniquely; else REQUEST_INFO (client domain) or REQUEST_AUTHORIZATION (unknown domain).
2. Sender domain in profile domains plus an unexpired entitlement at level 2 or higher; else REQUEST_AUTHORIZATION.
3. Missing instrument or date, or a date on/after the send date: REQUEST_INFO.
4. legal_hold: ESCALATE. no_email_confirm does not block.
5. as_of = date, rolled back to the previous business day. Settled = ledger summed across all sub-accounts up to as_of, split-adjusted for splits on or before as_of. as_of_assumed is always false.
6. Settled 0 gives NOT_HELD, even with a client figure.
7. Client figure off by over 10% from both settled and settled+pending: ESCALATE.
8. Otherwise CONFIRMED. Pending = matched instructions settling after as_of (sum, latest date).

**Inputs:** histories (harness 25/25); oracle 15/15 on my own outputs:
1. Q4-0094 ESC (7% gap): no, confirm
2. Q4-0012 assumed=T (month-end): flag wrong
3. Q4-0006 assumed=T (weekend): flag wrong
4. Q4-0016 CONF no date: no, ask for date
5. Q4-0083 CONF future: no
6. Q4-0114 ESC legal hold: yes
7. Q4-0054 ESC no_email: no, confirm with pending
8. Q4-0150 CONF unadjusted: no, mismatch → ESC
9. Q4-0130 NOT_HELD with client figure: yes
10. Q4-0091 sub-account → whole account: yes
11. Q4-0055 RI no account: yes
12. Q4-0038 CONF cross-domain entitled: no, domain
13. Q4-0066 multi-pending sum/max: yes
14. Q4-0083 RI future: "not sure, double-check"
15. Q4-0083 ESC future: no

**Least sure:** future dates; when as_of_assumed is true; no_email_confirm (one answer); exact tolerance (8–15% fits).
