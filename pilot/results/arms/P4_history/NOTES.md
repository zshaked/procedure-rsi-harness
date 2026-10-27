# P4 history-only arm — notes

**What I did:** I joined every history row to the tools output (contact, the account it resolves to, the domain match, the instrument matches, the position) and read all 200 cases. From that I induced the rules, wrote `procedure.py` and checked it with `harness.py`. Result: **189/200 (0.945), 0 fact errors.**

**Oracle use:** none (budget 0).

**Rules I believe the desk follows (in order):**
1. **REQUEST_AUTHORIZATION** when any of these holds:
   - the sender is not a known contact;
   - the contact's auth_level is below 2;
   - the sender's email domain is not the domain of the contact's own account.
2. **REQUEST_INFO** if the account ref does not resolve to exactly one account.
3. **REQUEST_AUTHORIZATION** if the resolved account is not the contact's account.
4. **REQUEST_INFO** if the instrument is missing or ambiguous, or the as_of date is missing. The desk never assumes a date. A future as_of also gets REQUEST_INFO; this is my own guard and is not seen in the histories.
5. **NOT_HELD** if there is no position, or settled is 0.
6. **ESCALATE** if a stated quantity differs by more than 10% from settled plus pending at as_of.
   - Confirmed cases go up to about 8% difference; escalated ones start at about 15%.
   - Case 0056 shows the comparison includes pending.
7. Otherwise **CONFIRMED** with the system's settled figure, plus pending and pending_date when pending is above 0.

**Least sure of:**
- Six escalations have no quantity mismatch (0018, 0024, 0052, 0127, 0179, 0191). I found no feature that explains them, so I treated them as operator noise. There may be a hidden rule I missed.
- The exact 10% threshold. Anywhere between 8% and 15% fits the data.
- Freemail or wrong-domain senders who are registered to the right account. Seven replies were authorization requests and three were not (0014, 0152, 0175). I followed the majority.
- Whether operators sometimes leave pending out on purpose (0064, 0163, 0175).
