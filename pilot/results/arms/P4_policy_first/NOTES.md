# NOTES — P4 policy-first

**What I did:** I tabulated the 200 histories against tool lookups, wrote procedure.py and tuned it with harness.py. The harness now agrees with the operators on 189/200 cases, with 0 fact errors. I used the oracle on cases where my procedure disagreed with the operator or where a policy question was open.

**Oracle log (19/25 used):**
- 0018, 0191, 0052, 0024: CONFIRMED where the operator escalated with no qty mismatch. All OK.
- 0127: CONFIRMED was "not sure". On a second ask, ESCALATE was rejected with "fine to confirm". So the first answer was oracle noise.
- 0012: CONFIRMED with an assumed as_of (the request date). Rejected: a missing date means we ask for one.
- 0086: CONFIRMED despite a -15% mismatch. Rejected: this goes to escalation.
- 0163: pending reported. OK. 0060: pending omitted. Rejected, so pending must be reported.
- 0014, 0080, 0143, 0175: AUTH. OK. 0094: INFO. OK.
- 0025: picking the contact's account out of an ambiguous match. Rejected: ask to clarify. 0016: picking the held instrument out of an ambiguous ticker. Rejected.
- 0085: L2 contact, large holding, CONFIRMED. OK. 0056: tolerance measured against settled+pending. OK.

**Rules, in order:**
1. The sender is not a contact, or has auth_level < 2 → REQUEST_AUTHORIZATION.
2. The sender's email domain is not their own account's domain (personal mail) → REQUEST_AUTHORIZATION.
3. The account ref does not resolve to exactly one account → REQUEST_INFO.
4. The account is not the sender's account → REQUEST_AUTHORIZATION.
5. The instrument is not unique, or as_of is missing → REQUEST_INFO.
6. There is no position, or settled is 0 → NOT_HELD.
7. stated_qty differs from settled+pending by more than 10% → ESCALATE.
8. Otherwise → CONFIRMED, reporting pending and its date whenever pending is nonzero.

**Least sure about:**
- The exact tolerance. The data only shows a gap between 8% and 15%, and I picked 10%.
- What to do when settled is 0 but pending > 0. No history case covers it.
- What to do when as_of is later than the request date.
