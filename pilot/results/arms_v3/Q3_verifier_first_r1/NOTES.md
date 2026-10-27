# Notes

**Rules (in order):** account must resolve to one id (if none named: sender's sole entitled account) else REQUEST_INFO; sender needs a live level-3 entitlement on it (free-mail domains fine) else REQUEST_AUTHORIZATION; no security, future date, or non-business date (weekend/holiday, incl. relative dates; no date = email date, as_of_assumed) gives REQUEST_INFO; legal_hold gives ESCALATE (guess); no_email_confirm gives REQUEST_AUTHORIZATION. Settled = all sub-accounts, ledger <= as_of, split-adjusted. Negative or >=1m, or a client figure off by >5% (unless it equals settled+pending), gives ESCALATE. Otherwise CONFIRMED (NOT_HELD if 0). Pending = matched instructions settling within 45 days after as_of.

**Method:** verifier.py came from the histories and tools, then the oracle. procedure.py: coordinate search scored by verify() on all 200 (200/200). Harness: 24/25. Q3-0022 counts as an operator error (Q5).

**Oracle (15/15):**
1. 0018 CONF with pending: ok
2. 0041 Sat CONF: no, not business day
3. 0059 INFO: "not sure" (treated as noise)
4. 0059 CONF 01-30: no, not business day
5. 0010 INFO: no, entitlement
6. 0025 gmail CONF: ok
7. 0051 future INFO: ok
8. 0129 no_email AUTH: ok
9. 0145 2.79m CONF: no, size
10. 0137 no-account ESC: ok
11. 0031 1.22m CONF: no, size
12. 0059 ESC: no, not business day
13. 0074 CONF + pending 656 (52d): no, pending handling
14. 0074 ESC: no, confirm settled
15. 0193 CONF + pending (17d): ok

**Least sure:** the pending window (36 to 52 days, or relative to email date), the 5% tolerance, legal_hold, sub-account scope and negatives.
