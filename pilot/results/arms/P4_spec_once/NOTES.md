# NOTES (P4, spec-once-then-policy arm)

**Process.** Phase 1: scripted feature extraction over all 200 histories (contact/auth level, sender vs account domain, account and instrument resolution counts, as_of presence, position, stated quantity vs position) and wrote spec.md with 9 ordered rules. Phase 2: spent 21 of 25 oracle questions on the rules and history exceptions I was least sure of (log in spec.md). Phase 3: implemented procedure.py from spec.md. Harness: 189/200 (0.945), 0 fact errors. All 11 disagreements are history cases the oracle ruled were operator mistakes.

**Rules (in order).**
1. Unknown sender or auth_level < 2 -> REQUEST_AUTHORIZATION.
2. Sender domain is not the client's domain (personal gmail/outlook/proton addresses) -> REQUEST_AUTHORIZATION.
3. Account reference matches 0 or 2+ accounts -> REQUEST_INFO. The desk never picks the sender's own account.
4. Sender's contact belongs to a different account -> REQUEST_AUTHORIZATION.
5. Instrument matches 0 or 2+ instruments -> REQUEST_INFO.
6. No as_of -> REQUEST_INFO. The desk never assumes a date.
7. No position, or settled is 0 -> NOT_HELD.
8. Stated quantity is more than 10% away from settled+pending -> ESCALATE.
9. Otherwise CONFIRMED, always reporting pending and pending_date when pending is above 0.

**Least sure of.**
- The exact tolerance in rule 8. The history only shows that 8% is accepted and 15% is escalated, so 10% is a guess.
- Senders with no contact record. No history case has one.
- Whether the rule 8 comparison divides by the desk's figure or the client's.
