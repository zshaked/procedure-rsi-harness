# Desk rules (as induced)

Order: resolve account (missing/ambiguous -> REQUEST_INFO) -> authorization (known contact, sender domain in profile domains, unexpired entitlement level>=2 on that account, else REQUEST_AUTHORIZATION; no_email_confirm also -> REQUEST_AUTHORIZATION) -> instrument (missing -> REQUEST_INFO; legal_hold -> ESCALATE) -> figures.

As-of: stated date, relative phrases from `sent`, else sent date (assumed=True); non-business day rolls back. Settled = ledger over all sub-accounts up to as_of, rows before a split date multiplied once as_of >= split. Pending = matched instructions with settle > as_of (sum, latest date). Client figure must equal settled+pending, else ESCALATE. Zero position -> NOT_HELD.

# Oracle log (15)
1. Q2-0153 NOT_HELD (net zero, sub-account cited): yes.
2. Q2-0157 NOT_HELD though client quoted a figure: yes.
3. Q2-0051 CONFIRMED, client figure = settled+pending: yes.
4. Q2-0006 CONFIRMED, client figure = settled only: no, escalation. Changed comparison to settled+pending.
5. Q2-0097 ESCALATE, same pattern: yes.
6. Q2-0142 AUTH (legal hold, level-1 sender): yes; authorization precedes hold.
7. Q2-0096 legal hold ESCALATE: yes.
8. Q2-0105 AUTH (no_email account, instrument missing): yes.
9. Q2-0041 AUTH (level 1, instrument missing): yes; reordered checks.
10. Q2-0029 "month-end" rolled back, assumed false: yes.
11. Q2-0089 pending_date earliest: no. Changed.
12. Q2-0089 pending_date latest: yes.
13. Q2-0036 lookalike corporate domain AUTH: yes.
14. Q2-0112 matched instruction settling on as_of not pending: yes.
15. Q2-0055 holiday sent date, no as-of: prior business day, assumed true: yes.

# Least sure
- Tolerance for small figure differences (none seen below 2%); I allow only rounding implied by k/mm notation.
- Settled 0 with pending > 0; legal hold with missing instrument; no_email on a fully specified request (assumed AUTH).
- Whether pending dates and quantities need split adjustment.
- Hidden relative-date phrasings.
