# Notes (policy-first arm)

**Rules (in order):** account from mention (exact match, else unique name prefix); no account named -> sender's sole entitled account; none/ambiguous -> REQUEST_INFO. Sender must be a contact with an unexpired level-3 entitlement on that account (domain not checked), else REQUEST_AUTHORIZATION. Instrument missing/unresolved -> REQUEST_INFO. Date: none -> sent date (assumed); unparseable, future, or not a business day -> REQUEST_INFO. legal_hold -> ESCALATE; no_email_confirm -> REQUEST_AUTHORIZATION. Settled = all sub-accounts' ledger up to as_of, split-adjusted. 0 -> NOT_HELD. Client figure differs -> ESCALATE. Settled >= 1,000,000 -> ESCALATE. Otherwise CONFIRMED, plus pending = matched instructions settling after as_of.

**Inputs:** base rules from histories and state; harness 24/25 (Q3-0022 is an operator error, per the oracle).

**Oracle log (15 used):**
1. 0076 ESCALATE: ok
2. 0059 weekend as_of CONFIRMED: NO, ask for date
3. 0020 with far-future pending: ok
4. accidental malformed call on 0193 (wasted)
5. 0193 pending settled before sent: ok
6. 0062 inferred account ESCALATE: ok
7. 0084 no_email_confirm REQ_AUTH: ok
8. 0145 2.79M CONFIRMED: NO, size escalation
9. 0080 zero held + client figure ESCALATE: NO, not held
10. 0031 1.22M CONFIRMED: NO, size escalation
11. 0198 no date, sent on holiday -> REQUEST_INFO: ok
12. 0051 future date REQUEST_INFO: ok
13. 0085 legal hold + weekend -> REQUEST_INFO: ok
14. 0046 matching figure + pending: ok
15. 0022 REQ_AUTH: ok

**Least sure:** legal_hold -> ESCALATE was never tested. Also the size threshold (855k-1.2M) and sub-account requests (whole account reported).
