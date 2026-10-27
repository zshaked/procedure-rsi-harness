# Notes

**Rules:** 1) free-mail sender → REQ_AUTH. 2) Account must resolve uniquely, else REQUEST_INFO (no disambiguation by entitlement). 3) Need the sender domain in the profile plus an unexpired entitlement of level ≥2, else REQ_AUTH. 4) Legal hold → ESCALATE. no_email_confirm is ignored. 5) Missing instrument or date, or a future date → REQUEST_INFO. 6) as_of rolls back to the previous business day; assumed=False. 7) settled = all sub-accounts, ledger ≤ as_of, split-adjusted. 8) 0 → NOT_HELD. 9) Client figure >10% off both settled and settled+pending → ESCALATE. 10) CONFIRMED; pending = matched instructions after as_of, dated by the latest.

**Method:** wrote verifier.py from histories and tools, then calibrated it with the oracle. procedure.py was chosen from a 512-variant grid search on verify() over all 200 requests (200/200).

**Oracle (15/15):**
- 0077 8% diff CONFIRMED: ok
- 0098 month-end assumed=False: ok
- 0033 no date: rejected
- 0183 client = settled+pending: ok
- 0114 legal hold ESCALATE: ok
- 0054 no_email_confirm ESCALATE: rejected, should confirm
- 0083 future REQUEST_INFO: ok
- 0055 unnamed account REQUEST_INFO: ok
- 0130 zero + client figure NOT_HELD: ok
- 0032 wrong domain REQ_AUTH: ok
- 0118 legal hold + level 1 REQ_AUTH: ok
- 0054 CONFIRMED + pending: ok
- 0168 expired REQ_AUTH: "not sure"
- 0190 expired REQ_AUTH: ok
- 0119 yesterday→Fri: ok

**Least sure:**
- Exact tolerance (anywhere from 8% to 15% fits).
- The 0168 verdict.
- Dates equal to the sent date.
- When as_of_assumed is true.
- Negative positions.
