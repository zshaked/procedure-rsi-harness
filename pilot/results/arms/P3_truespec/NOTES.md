# NOTES — P3 true-spec arm

**What I did.** Implemented policy.txt directly in procedure.py, ran harness.py, and inspected each of the 16 disagreements against the system of record. I made no changes to fit the history, because every residual looked like an operator error that contradicts the written policy.

**Oracle use.** 0 questions (budget 0).

**Rules implemented (in order).**
1. Sender must be a known contact with auth_level >= 3, else REQUEST_AUTHORIZATION. This check runs before account resolution.
2. Account ref must resolve to exactly one account, else REQUEST_INFO.
3. Contact's account must equal the resolved account, else REQUEST_AUTHORIZATION.
4. Instrument must resolve to exactly one, else REQUEST_INFO.
5. Missing as-of means request date, with as_of_assumed=true.
6. No position, or settled == 0, means NOT_HELD.
7. Stated qty differing from settled by >5% (of settled) means ESCALATE.
8. Settled > 1,000,000 means ESCALATE.
9. Otherwise CONFIRMED; pending/pending_date only if pending > 1,000.

**Result.** 184/200 = 0.920 agreement, 0 fact errors. The residuals look like operator mistakes. Examples: a 1.29M position confirmed; an 8,126 vs 5,417 mismatch confirmed; REQUEST_INFO given to unauthorized or wrong-account senders, i.e. the account was resolved before authorization was checked.

**Least sure of.** policy.txt has no rule 3 (it is referenced as an authorization check). I tested "sender domain must match account domain" and the history rejects it: 7 mismatched-domain senders were CONFIRMED. So I implemented nothing for it. Other open points: whether the 5% is measured against settled or stated qty (no case in the history separates the two), and whether settled == 0 counts as NOT_HELD.
