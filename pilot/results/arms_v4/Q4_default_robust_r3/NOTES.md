# Notes

## Rules (procedure.py)
1. Account via search_accounts(mention); instrument via search_instruments. Several accounts match -> REQUEST_INFO.
2. No account mentioned: REQUEST_INFO if the sender's domain matches an entitled account, else REQUEST_AUTHORIZATION.
3. REQUEST_AUTHORIZATION unless the sender domain is in the account profile domains AND the contact holds an unexpired entitlement of level >= 2 on that account.
4. legal_hold -> ESCALATE. no_email_confirm is ignored.
5. No instrument, no date, or a date after `sent` -> REQUEST_INFO.
6. As-of is rolled back to the previous business day. Settled = ledger sum over all sub-accounts up to as-of, with a split applied when the entry predates it and the split is on or before as-of. get_position_summary is not used.
7. Pending = matched instructions settling after as-of: summed, with the latest date.
8. Zero settled and no pending -> NOT_HELD.
9. The client's stated figure is compared with settled and with settled+pending. A difference over 10% on both -> ESCALATE. Unadjusted pre-split figures therefore escalate.

## Oracle log (15 used)
1. Q0094 CONFIRMED at 7% off: ok. I loosened the tolerance from 5% to 10%.
2. Q0077 CONFIRMED at 8% off: ok.
3. Q0066 CONFIRMED with pending: rejected ("entitlement") - probably noise.
4. Q0066 ESCALATE: rejected ("fine to confirm, pending needed"). So compare the claim with settled+pending.
5. Q0130 NOT_HELD although the client claims a holding: ok.
6. Q0032 AUTH for corporate other-domain sender: rejected.
7. Q0114 legal hold ESCALATE: ok.
8. Q0054 ESCALATE for no_email_confirm: rejected. I dropped that rule.
9. Q0062 AUTH, other-domain level 2: ok.
10. Q0085 AUTH, outlook level 3: rejected ("wrong security").
11. Q0141 AUTH, gmail level 3: ok.
12. Q0083 CONFIRMED with an assumed date for a future date: rejected ("hasn't happened yet").
13. Q0083 REQUEST_INFO: ok.
14. Q0054 CONFIRMED with pending: ok.
15. Q0055 REQUEST_INFO for no account: ok.

## Least sure
- The domain gate. Answers 6 and 10 contradict it; 9 and 11 plus histories Q0008 and Q0009 support it. I kept it, following R2 and the net evidence.
- as_of_assumed is always False; I never saw it True.
- Same-day dates are accepted.
- The ESCALATE tolerance is somewhere between 8% and 15%; I used 10%.
