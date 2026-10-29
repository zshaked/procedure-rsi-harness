## Rules
1. Account and instrument must each resolve to exactly one record (any id, name, ticker or former ticker); else REQUEST_INFO (ambiguous prefixes, shared short names, no instrument).
2. Authorised only if known contact, sender domain on the account profile, and an entitlement of level >= 2 not expired at sent date; else REQUEST_AUTHORIZATION.
3. Legal hold -> ESCALATE (after auth).
4. Dates M/D/Y, relative allowed; weekend/holiday (also an assumed sent date) rolls back; no date -> sent date, assumed. Future date -> REQUEST_INFO (guess).
5. Settled = ledger over all sub-accounts up to as_of, split-adjusted when split date <= as_of. Zero -> NOT_HELD, even if the client states a figure.
6. Pending = matched instructions settling after as_of, summed, earliest date.
7. Client's figure must equal settled + matched pending (1% tolerance), else ESCALATE; otherwise CONFIRMED.

## Oracle (15 used)
1. Q0125 AUTH, foreign domain, L3: ok (domain rule).
2. Q0097 CONFIRMED, claim = settled, pending exists: rejected, escalation (claim compares to settled + pending; explains Q0006).
3. Q0051 claim = settled + pending, CONFIRMED: ok.
4. Q0157 NOT_HELD with stated figure: ok.
5. Q0096 ESCALATE: rejected, business-day reason; treated as noise (Q7, Q13 contradict).
6. Q0096 REQUEST_INFO: rejected, legal hold -> escalation.
7. Q0034 assumed date: ok.
8. Q0177 AUTH, legal-hold account, free-mail sender: ok (auth precedes hold).
9. Q0029 month-end on Saturday rolls back: ok.
10. Q0053 former ticker: ok.
11. Q0140 level-2 sees pending: ok.
12. Q0089 two matched instructions, sum and earliest date: ok.
13. Q0055 assumed date on holiday rolls back: ok.
14. Q0025 pending settling between as_of and sent: ok.
15. Q0158 shared short name -> REQUEST_INFO: ok.

## Least sure
- no_email_confirm outcome (guessed ESCALATE; maybe REQUEST_AUTHORIZATION).
- Future dates; split between as_of and sent; pending settling exactly on as_of.
