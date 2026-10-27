# NOTES — P3, spec-once-then-policy arm

**What I did.** I computed features for all 200 histories with the tools: contact auth level, whether the sender's account matches, how many accounts and instruments resolve, the position, and the gap between the stated and settled quantity. I grouped the outcomes by these features and wrote spec.md (12 rules, with evidence and confidence). Then I spent the oracle questions on the rules I was least sure of and on suspected operator errors, and implemented procedure.py from the spec. The harness gives 184/200 (0.92) with 0 fact errors. All 16 disagreements are cases the spec calls operator errors; the oracle confirmed 14 of them.

**Oracle.** I used 23 of 25 questions; all are logged in spec.md. One was wasted on a bug in how I built the response. One answer (0199) was vague and turned out to be oracle noise: a second question settled it.

**Rules (applied in order).**
1. Sender with auth level below 3 → REQUEST_AUTHORIZATION.
2. Account doesn't resolve to exactly one → REQUEST_INFO.
3. Sender's contact account is not the requested account → REQUEST_AUTHORIZATION. The email domain doesn't matter.
4. Instrument doesn't resolve to exactly one → REQUEST_INFO.
5. No as_of date → use the request date and set as_of_assumed.
6. No position, or settled = 0 → NOT_HELD.
7. Settled ≥ 1,000,000 → ESCALATE.
8. Stated quantity more than 5% away from settled → ESCALATE.
9. Otherwise CONFIRMED. Pending is reported only when it is ≥ 1,000.

**Least sure of.**
- The exact cut-offs: the mismatch tolerance is somewhere between 4% and 8%, the pending threshold between 885 and 6,186, and the large-position cut between 945,475 and 1,006,007.
- Whether a stated quantity should be compared against settled + pending. This was only seen for unauthorized senders, so I couldn't test it.
- Ambiguous instruments for an authorized sender, which I assumed are REQUEST_INFO.
