# Notes

**Rules believed:** (1) account and instrument must each resolve to exactly one record (old tickers, short names, sub-accounts OK), otherwise REQUEST_INFO. (2) The sender needs an unexpired entitlement of level 2 or more on the account and an email domain registered for the client, otherwise REQUEST_AUTHORIZATION. (3) Legal hold leads to ESCALATE. (4) The date is explicit, relative (yesterday or month-end) or missing; a missing date means the email date with as_of_assumed=true. A non-business day rolls back to the previous business day. (5) settled = the raw ledger across all sub-accounts, inclusive of as_of and split-adjusted. pending = matched instructions settling after as_of, summed, with the latest date. (6) If the client's figure is not within 1% of settled+pending, ESCALATE. (7) Zero gives NOT_HELD, otherwise CONFIRMED.

**Inputs:** verifier.py came from the histories and tools, then oracle calibration. Verifier and oracle agree on 14 of 15 answers. The first 0153 answer contradicted the second. procedure.py was chosen by a grid search over 192 variants scored by verify() on all 200 requests (200/200). Harness 25/25.

**Oracle log:** 0006 CONF→no (figure vs settled+pending); 0051 CONF figure=settled+pending→yes; 0034 no-date→yes; 0096 legal-hold ESC→yes; 0095 AUTH→yes; 0177 AUTH→yes; 0095 ESC→no (domain); 0191 whole-account→yes; 0153 NOT_HELD→"not sure"; 0123 NOT_HELD→yes; 0153 ESC→no ("doesn't hold"); 0089 earliest pending date→no; 0025 pending→yes; 0053 old ticker→yes; 0076 unadjusted pending→no.

**Least sure:** I guessed no_email_confirm gives ESCALATE. The split-adjusted pending is a guess, as are the 1% tolerance, future dates giving REQUEST_INFO and negative totals giving ESCALATE.
