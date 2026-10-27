# Notes (verifier-first)

**Rules believed:** 1) account must resolve uniquely (SA-id → parent), else REQUEST_INFO. 2) Sender: entitlement on that account, level ≥2, unexpired at send date, domain in client domains, else REQUEST_AUTHORIZATION. 3) no_email_confirm → REQUEST_AUTHORIZATION (even before instrument). 4) instrument unique (old tickers OK), else REQUEST_INFO. 5) legal_hold → ESCALATE. 6) as_of = stated/relative date (month-end = last month-end), no date → send date (assumed); roll back to previous business day; future → REQUEST_INFO (guess). 7) settled = ledger, all sub-accounts, ≤as_of, split-adjusted (not position_summary). 8) settled ≤0 → NOT_HELD. 9) client figure vs settled + matched pending ≥1,000 settling after as_of; differs >1% → ESCALATE. 10) else CONFIRMED with that pending.

**Method:** verifier.py from histories/tools, oracle-calibrated (15/15 agreement). procedure.py picked by coordinate search over 18 convention knobs, scored by verifier pass rate on all 200 (200/200). Harness 25/25.

**Oracle log** (case: response → verdict):
1. 0006 CONFIRMED (settled=client) → no, figure mismatch
2. 0051 CONFIRMED, client=settled+pending → yes
3. 0076 no-date as_of=prev bday → wrong date
4. 0076 as_of=sent, pending 601 → pending wrong
5. 0140 as_of=sent, pending 38,954 → yes
6. 0076 pending ×split 1803 → pending wrong
7. 0076 no pending → yes
8. 0050 pending 303 → pending wrong
9. 0190 pending 348 omitted → yes
10. 0097 CONFIRMED omitting 13,615 → no, escalate
11. 0153 sub-account figure → no, account not held
12. 0081 hold+unentitled ESCALATE → no, authorization
13. 0157 zero+client figure NOT_HELD → yes
14. 0053 old ticker, month-end → yes
15. 0105 no_email ESCALATE → no, authorization

**Least sure:** pending threshold (1,000 vs relative ~2%), multi-pending date (latest), 1% tolerance, future dates.
