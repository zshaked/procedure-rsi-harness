# Notes (verifier-first)

**Rules:**
1. Free-mail sender: AUTH.
2. Account missing or ambiguous: INFO.
3. Sender domain not on the profile, or no live entitlement of level 2+: AUTH.
4. Legal hold: ESCALATE (no_email_confirm ignored).
5. Missing instrument or date, or a date on/after sent: INFO.
6. as_of is the date rolled back to the previous business day (month-end and yesterday are relative to sent).
7. settled sums all sub-accounts, split-adjusted. 0 gives NOT_HELD.
8. pending sums matched instructions settling after as_of, dated by the latest one.
9. Client figure more than 10% from settled+pending: ESCALATE.
10. Otherwise CONFIRMED. as_of_assumed is False (True only for dates with no year).

**Oracle (15/15)**, case/response/verdict:
- 0013 assumed=T: no
- 0077 8% off: ok
- 0094 7% low: ok
- 0183 matches settled+pending: ok
- 0155 matches settled only: no, escalate
- 0016 no date, assumed: no, ask
- 0021 yesterday, assumed=F: ok
- 0012 month-end, assumed=F: ok
- 0055 no account, INFO: ok
- 0032 off-profile domain: no
- 0114 legal hold, ESC: ok
- 0054 no_email_confirm, ESC: no, confirm with pending
- 0083 future date, INFO: ok
- 0130 zero, NOT_HELD: ok
- 0118 level 1 plus legal hold, AUTH: ok

verify() matches all 15. The search-chosen procedure passes verify() on 200/200 requests and matches the operators on 25/25.

**Least sure:** the tolerance (between 8% and 15%), ignoring no_email_confirm (one answer), what as_of_assumed means, and the order of legal hold versus missing info.
