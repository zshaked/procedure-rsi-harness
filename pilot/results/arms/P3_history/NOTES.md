# NOTES (history-only arm, 0 oracle questions)

**Method.** I joined each history row with tool lookups (contact, auth, account, instrument, position) and tabulated outcomes. Majority patterns became rules; isolated contradictions were treated as operator errors. 183/200 (0.915), 0 fact errors.

**Rules I believe the desk follows (in order):**
1. If the sender is not a contact, or auth_level < 3: REQUEST_AUTHORIZATION.
2. If the account ref doesn't resolve to exactly one account: REQUEST_INFO.
3. If the resolved account isn't the contact's own account: REQUEST_AUTHORIZATION. This includes "X" when the sender belongs to "X II".
4. If the instrument is missing or not exactly one match: REQUEST_INFO.
5. If as_of is missing: use the request date (as_of_assumed=true).
6. If there's no position or settled is 0: NOT_HELD, even with a stated qty.
7. If settled >= 1,000,000, or a stated qty differs from settled: ESCALATE.
8. Otherwise CONFIRMED with settled. Report pending/pending_date only when pending >= 1,000.

**Least sure of:**
- The exact 1M cutoff (>= vs >), since two large positions were confirmed (0010, 0069).
- Whether there's a tolerance on stated qty. 0126 and 0144 were confirmed at about 2-4% off, but 0115 was escalated at 3.9%.
- The pending cutoff: it sits somewhere between 884 (not reported) and 6,187 (reported).
- P3-0099: escalated with only a small position plus a pending settlement due the day after. Treated as noise.
- The 4 REQUEST_INFO replies to level-3 senders on the wrong account, which I treated as errors.
