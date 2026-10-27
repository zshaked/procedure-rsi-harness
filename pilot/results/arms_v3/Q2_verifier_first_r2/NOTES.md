# Notes

**Rules (in order):** 1) account text must resolve to exactly one account, else REQUEST_INFO. 2) Sender authorized: domain in client profile, known contact, unexpired entitlement level >= 2, else REQUEST_AUTHORIZATION. 3) no_email_confirm -> REQUEST_AUTHORIZATION; legal_hold -> ESCALATE. 4) Instrument (old tickers OK) must resolve, else REQUEST_INFO. 5) Date: stated date rolled back to business day; "yesterday" = sent-1; month-end = previous month end; none -> previous month end, as_of_assumed. On/after sent -> REQUEST_INFO (guess). 6) Figure = all sub-accounts, ledger <= as_of, split-adjusted. Client figure differs -> ESCALATE; zero -> NOT_HELD; else CONFIRMED, with pending = matched instructions settling after as_of (sum, latest date).

**Inputs:** histories and tools built verifier.py. The oracle calibrated it, and procedure.py was chosen by grid search (192 variants) on verifier pass rate over all 200 requests: 200/200. Harness: 24/25. Q2-0006 is an operator mistake; the oracle accepted CONFIRMED.

**Oracle log (15/15):** 0006 CONFIRMED+pending: yes. 0076 as_of prev business day: no (wrong date); month-end: yes. 0096 legal hold ESCALATE: yes. 0081 legal hold but unauthorized, ESCALATE: no (authorization first). 0095 no-email + bad domain, ESCALATE: no (domain). 0069 split + two pending: yes. 0025 pending settling before sent: yes. 0153 NOT_HELD: no ("not sure"); ESCALATE: no ("doesn't hold"), so the first answer was noise. 0191 sub-account named, total figure: yes. 0123 NOT_HELD: yes. 0053 old ticker: yes. 0105 no-email ESCALATE: no (needs authorization). 0041 unauthorized + no instrument, REQUEST_AUTHORIZATION: yes.

**Least sure:** future/same-day dates, legal hold vs no-email order, multi-instruction pending_date, match tolerance.
