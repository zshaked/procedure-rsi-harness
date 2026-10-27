# NOTES (true-spec arm)

**What I did:** I implemented policy.txt in procedure.py, keeping its rule order, and checked the result with harness.py. I made 0 oracle calls.

**Rules as implemented:**
1. Sender is an unknown contact, or has auth_level < 2 -> REQUEST_AUTHORIZATION.
2. Sender's email domain differs from the domain of the contact's own account -> REQUEST_AUTHORIZATION. Rules 1 and 3 both run before the account is resolved (rule 4).
3. account_ref resolves (via lookup_account) to zero or several accounts -> REQUEST_INFO.
4. Resolved account is not the contact's account (or its domain differs from the sender's) -> REQUEST_AUTHORIZATION.
5. Instrument is missing or does not resolve to exactly one -> REQUEST_INFO. Missing as_of -> REQUEST_INFO.
6. No position, or settled <= 0 as of the date -> NOT_HELD.
7. stated_qty differs from settled+pending by more than 10% of settled+pending -> ESCALATE.
8. Otherwise CONFIRMED with the settled quantity. Pending quantity and date are included only if pending > 0.

**Harness:** 189/200 (0.945), 0 fact errors. Remaining disagreements:
- 4 cases: operators asked for info where the policy's auth-first order gives REQUEST_AUTHORIZATION. These include exact-name matches to a different account than the contact's.
- 1 case: operator demanded authorization where the policy gives REQUEST_INFO.
- 1 case: operator confirmed to a gmail sender.
- 5 cases: operator escalated where the policy confirms.

**Least sure of:**
- The policy numbering skips rule 9. Those 5 unexplained ESCALATEs (some with no stated quantity) may come from an unwritten rule 9. I found no consistent pattern, so I treated them as operator error.
- How rule 3 should be read before the account is resolved. I compare against the contact's account domain.
- The 10% tolerance base. I used settled+pending.
