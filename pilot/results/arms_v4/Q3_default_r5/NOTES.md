# Notes

## Rules believed
1. Account text must resolve to exactly one account (else REQUEST_INFO). No account named: infer from sender's single valid entitlement.
2. Authorization first: sender needs an unexpired level-3 entitlement on that account (level 1-2, other account, expired -> REQUEST_AUTHORIZATION). Beats missing-info checks.
3. Missing/ambiguous instrument -> REQUEST_INFO (ids resolve via ticker, former ticker, name).
4. Client no_email_confirm -> REQUEST_AUTHORIZATION; legal_hold -> ESCALATE.
5. Date: none -> sent date (assumed). Future or non-business day (weekend/holiday) -> REQUEST_INFO (no rolling).
6. Position = sum of all sub-accounts up to and including as_of, ledger rows before a split date multiplied by ratio. Zero -> NOT_HELD (claim ignored).
7. |position| >= 1,000,000 -> ESCALATE. Client figure differing by more than ~5% (unless equal to settled + matched pending) -> ESCALATE.
8. Pending: matched instructions settling after as_of (within ~90 days) reported with earliest date.

## Oracle (15 used)
1 Q84 AUTH for no_email: yes. 2 Q85 ESCALATE legal hold: yes. 3 Q74 ESCALATE for 0.08% claim diff: no -> tolerance. 4-5 Q74 pending reported / omitted (34d): both yes. 6 Q123 omit pending (20d): no -> pending required. 7 Q57 rolled weekend date: no -> INFO instead. 8 Q51 future date INFO: yes. 9 Q62 inferred account ESCALATE 8% diff: yes. 10 Q132 ESCALATE 2% diff: no -> tolerance. 11 Q175 CONFIRM 1.06M: no -> size rule. 12 Q91 ESCALATE zero position with claim: no -> NOT_HELD. 13 Q145 2.79M confirm: no (size). 14 Q193 pending reported though settling before sent: yes. 15 Q22 AUTH: yes (history reply was a mistake).

## Least sure
Tolerance (between 2% and 7%), pending window and base, size threshold exactly 1M, old-ticker handling, level 2 treated as unauthorized (only 2 history cases), negative positions, holiday handling when sent date itself is non-business.
