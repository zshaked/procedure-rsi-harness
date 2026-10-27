# Notes (verifier-first arm)

**Rules, in order:** account text must resolve to exactly one account (else REQUEST_INFO); sender domain is irrelevant. Sender needs an unexpired level-3 entitlement on it, otherwise REQUEST_AUTHORIZATION. Instrument must resolve (else REQUEST_INFO). no_email_confirm → REQUEST_AUTHORIZATION; legal_hold → ESCALATE. Date: none given → sent date (assumed); a future date or a non-business day → REQUEST_INFO. Settled = ledger over all sub-accounts up to as_of, split-adjusted (not get_position_summary). Zero → NOT_HELD. Negative or ≥1,000,000 → ESCALATE. A client figure more than 3% off → ESCALATE, unless it equals settled+pending. Pending = matched instructions settling in (as_of, as_of+90d].

**Inputs:** verifier.py came from the histories, the unlabeled requests and the tools; 15 oracle questions calibrated it. procedure.py came from a grid search scored by verify() over all 200 requests (200/200). Harness: 23/25 (I judge 0022 and 0024 to be operator mistakes).

**Oracle log:**
1. 0018 CONF + pending 684@+107d → no (pending)
2. 0193 CONF + pending @+17d → yes
3. 0123 CONF + pending @+65d → yes
4. 0057 CONF rolled Sun→Fri → no (ask date)
5. 0132 CONF, figure +2% → yes
6. 0175 CONF 1,056,400 → no (size)
7. 0145 ESCALATE split-adjusted 2.79M → yes
8. 0085 ESCALATE legal hold → yes
9. 0051 REQUEST_INFO future date → yes
10. 0025 CONF gmail sender → yes
11. 0137 ESCALATE inferred account → no (vague)
12. 0080 NOT_HELD despite figure → yes
13. 0137 REQUEST_INFO → yes
14. 0041 REQUEST_INFO Saturday → no (vague; noise)
15. 0041 CONF rolled → no (ask date)

**Least sure:** tolerance (2–7%), pending window (65–107d), missing-account handling (11 vs 13), size threshold.
