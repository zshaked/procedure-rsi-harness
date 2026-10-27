# P4 verifier-first arm

**What I did.** I worked out the decision ladder from the 200 histories by joining each request to the system of record. Then I wrote `verifier.py`, a reference-free checklist with gates G1-G7 and field checks C0-C7, each citing evidence case_ids. I calibrated it with the oracle. Finally I wrote `procedure.py` by searching 1,728 parameterised variants (gate order, tolerance, comparison basis, pending handling, zero-position handling, sender-domain rule), scoring each by its `verify()` pass rate. The chosen procedure passes 200/200 verifier checks. Harness agreement is 189/200 with 0 fact errors.

**Oracle use (21/25).** The verifier agreed with the oracle on 20 of 21 answers. The one conflict was P4-0143. The oracle's next answer on the same case (that the sender is not on the client's domain) contradicted its first one, so I treated the first as noise. All 11 remaining harness disagreements were asked about. The oracle said each one was an operator mistake. The full log is in `verifier.py` (`ORACLE_LOG`).

**Rules.**
1. REQUEST_AUTHORIZATION when the sender is unknown, has auth_level 1, or writes from a free-mail or non-firm domain.
2. REQUEST_INFO when the account reference does not resolve to exactly one account. The sender's own account is never used to break the tie.
3. REQUEST_AUTHORIZATION when the sender's domain differs from the account's domain, or the contact is not on that account.
4. REQUEST_INFO when the instrument does not resolve to exactly one, or as_of is missing. The date is never assumed.
5. NOT_HELD when there is no position, or nothing is settled and nothing is pending.
6. ESCALATE when the stated quantity differs from settled + pending by more than 10%.
7. Otherwise CONFIRMED with the settled quantity. Pending units and their date are reported when they settle after as_of.

**Least sure:**
- The escalation threshold: the data only places it somewhere between 8% and 15%.
- Unknown senders: no history case had one.
- A position with zero settled but a non-zero pending amount.
