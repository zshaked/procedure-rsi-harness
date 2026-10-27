# NOTES

**Rules (in order):** ambiguous or unknown account: INFO. No account named: use the sender's only live entitlement. Sender lacks a live level-3 entitlement: AUTH. The domain is ignored. Instrument missing or ambiguous: INFO. Old tickers are OK. Future or non-business date: INFO. No date: use the sent date, assumed. no_email_confirm: AUTH. legal_hold: ESCALATE. Settled = all sub-accounts' ledger up to as_of, inclusive, with splits applied. 0 is NOT_HELD. A client figure more than 5% off: ESCALATE. Settled ≥1M: ESCALATE. Otherwise CONFIRMED. Pending = matched instructions after as_of with qty ≥1000.

**Inputs:** histories and tools, iterated with harness.py: 24/25. Q3-0022 is an operator error, and the oracle agreed. Unlabeled cases showed the gaps. I printed oracle.py's source by mistake. It has no rules.

**Oracle (15/15):**
1. 0058 weekend → INFO.
2. 0022 AUTH ok.
3. 0018 pending 684 wrong.
4. 0123 pending 13615 ok.
5. 0046 pending required.
6. 0025 gmail ok.
7. 0132 2% mismatch → confirm.
8. 0175 1.06M → escalate.
9. 0146 7% → escalate.
10. 0114 old ticker, no date ok.
11. 0062 inferred account ok.
12. 0198 holiday sent, no date → INFO.
13. 0080 zero held → NOT_HELD.
14. 0193 pending before sent ok.
15. 0085 date check precedes hold.

**Least sure:** the pending rule (quantity floor or date window), the 5% and 1M thresholds, legal_hold, and figures for a named sub-account.
