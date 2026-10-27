# NOTES — verifier-first arm

**What I did.** Built per-case features from histories + tools, wrote `verifier.py` (reference-free checklist: decision checks A–F plus field checks 0–6, each citing case_ids), calibrated it with the oracle, then grid-searched procedure variants (check order, large/tolerance/pending thresholds, date handling) scored only by verify() pass rate over all 200 requests. Best variant → `procedure.py` (200/200 verify). Harness sanity check: 184/200 = 0.920 agreement, 0 fact errors.

**Oracle use.** 21 of 25 questions, all logged in `oracle_log.jsonl`. They targeted history contradictions and field rules. Verifier agrees with 20/21 verdicts. The one disagreement (P3-0120 REQUEST_INFO rejected, "not sure") was contradicted by a follow-up question, so I treat it as oracle noise.

**Rules I believe the desk follows (in order).**
1. Unknown sender, auth level < 3, or a contact linked to a different account (when the account resolves uniquely) → REQUEST_AUTHORIZATION. This check comes before completeness.
2. Account ambiguous or unresolved, or instrument missing, ambiguous or unresolved → REQUEST_INFO.
3. Missing as_of → use the request date, with as_of_assumed=true.
4. No position or zero settled → NOT_HELD. This takes precedence over a stated-quantity mismatch.
5. Settled ≥ 1,000,000, or stated quantity more than 5% off settled → ESCALATE (with ids).
6. Otherwise CONFIRMED with settled. Pending is reported only if ≥ 1,000.

**Least sure of.**
- The exact quantity tolerance: it lies somewhere between 4% (accepted) and 7–8% (rejected).
- The exact pending cutoff: it lies between 884 (omitted) and 6,187 (reported).
- Whether the large-position test uses settled or settled+pending.
- Zero settled with a nonzero pending, and requests from unknown senders: neither appears in the histories.
