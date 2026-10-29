# Notes

## Rules (check order)
1. Account text must resolve to exactly one account (no text: sender's sole entitlement). Else REQUEST_INFO.
2. Sender needs a contact record plus an unexpired level>=3 entitlement on that account. Else REQUEST_AUTHORIZATION.
3. Instrument must resolve to exactly one. Else REQUEST_INFO.
4. Profile no_email_confirm (or legal_hold, a guess) -> REQUEST_AUTHORIZATION.
5. Date: explicit or relative, else the sent date (assumed). Future or non-business day -> REQUEST_INFO.
6. Settled = ledger sum over all sub-accounts up to as_of, with entries before a split date times the ratio only when split date <= as_of.
7. Zero held -> NOT_HELD. Settled >= 1,000,000 -> ESCALATE. Client figure differing from settled (and from settled + matched pending) -> ESCALATE. Else CONFIRMED.
8. Pending = matched instructions settling after as_of with qty >= 1000 (sum, earliest date).

## Oracle (15 used)
1. Q0107 weekend as_of rolled back: no, non-business date -> ask. Changed to REQUEST_INFO.
2. Q0022 AUTH: yes, so the history reply was a mistake.
3. Q0198 INFO on assumed holiday date: yes.
4. Q0090 INFO: no, account is no_email_confirm -> AUTH. NEC is checked before date.
5. Q0051 INFO for future date: yes.
6. Q0123 no pending: no. Pending is reported even about 20 days out.
7. Q0046 no pending: no; with pending: yes. Far dates are fine.
8. Q0031 CONFIRMED: no, size -> escalation. Added the 1M rule.
9. Q0193 pending dated before sent: yes.
10. Q0148 raw figure, split after as_of: yes.
11. Q0074 with pending 656: no; without: yes. Dropped the window and added the qty >= 1000 floor. Client figure = settled + pending is accepted.
12. Q0080 ESCALATE (client figure, none held): no -> NOT_HELD.
13. Q0085 INFO: no, "entitlement lapsed". The account has legal_hold, so I set legal_hold -> AUTH (unverified).

## Least sure
- Legal hold outcome (AUTH vs ESCALATE).
- The 1,000,000 threshold (gap is 886k to 1.056M) and the pending floor of 1000.
- Split-adjusted figures when as_of is after the split date (docstring only).
- Pending date when several instructions qualify.
- Level 2 treated as insufficient.
