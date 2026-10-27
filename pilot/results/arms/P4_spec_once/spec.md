# P4 desk procedure — induced spec

Notation: `contact = get_contact(from)`; `cands = lookup_account(account_ref)`; `ins = resolve_instrument(instrument_ref)`;
"account domain" = the resolved account's `domain`; sender domain = part after `@`.
Rules are applied in order; the first that fires decides.

1. **No contact, or contact auth_level < 2 -> REQUEST_AUTHORIZATION.**
   Evidence: all 9 auth-1 cases RA (P4-0020, 0036, 0041, 0055, 0043, 0155, 0040, 0142, 0153), including ones with ambiguous account or missing as_of (so this precedes rules 3, 5, 6). No unknown-sender cases exist in history (assumed). Confidence: high (auth1), medium (no contact).
2. **Sender domain is not the account's registered domain (all such senders in data are gmail/outlook/proton personal addresses) -> REQUEST_AUTHORIZATION.**
   Evidence: P4-0002, 0031, 0054, 0081, 0091, 0099, 0105, 0134, 0153, 0159, 0169, 0176 RA; precedes ambiguity (0099, n=3) and missing as_of (0081, 0159, 0169). Exceptions: 0014 (RI), 0152 (RI), 0175 (CONFIRMED). Implementation: compare against the domain of the contact's own account (equal to the resolved account when rule 4 passes). Confidence: high (oracle Q9, Q10, Q16, Q17 confirmed; history exceptions 0014/0152/0175 are operator mistakes).
3. **account_ref matches 0 or >1 accounts -> REQUEST_INFO.** (Desk does not disambiguate using the sender's own account.)
   Evidence: 18 ambiguous cases RI (0003, 0017, 0025, 0035, 0037, 0075, 0076, 0089, 0118, 0164, 0170, 0171, 0173, 0197, 0022, 0026, 0139 ...), incl. 0171/0139 where the contact's account is not a candidate (so precedes rule 4). Oracle Q12 (0025): using the sender's own candidate account is wrong -> ask to clarify. Confidence: high.
4. **Contact's account != resolved account -> REQUEST_AUTHORIZATION.**
   Evidence: ~38 cases (0006, 0009, 0010, 0027, 0039, 0042, 0057, 0058, ...); precedes instrument (0011, 0023, 0073, 0115) and as_of checks (0061, 0071, 0129, 0146, 0161). Exceptions 0080 (RI), 0143 (RI) are mistakes: oracle Q13, Q14 accepted RA. Confidence: high.
5. **instrument_ref resolves to 0 or >1 instruments -> REQUEST_INFO.**
   Evidence: 0140, 0141, 0151, 0160, 0167 (none), 0016, 0103 (FHA ambiguous). Confidence: high.
6. **No as_of in request -> REQUEST_INFO** (desk does not assume a date; as_of_assumed always false).
   Evidence: 0005, 0012, 0033, 0069, 0072, 0078, 0096, 0104, 0116, 0120, 0122, 0174, 0190, 0198 RI. Exception 0094 (RA) is a mistake (oracle Q18 rejected RA: 'No as-of date, so we go back and ask for one'). Oracle Q11 rejected assuming the request date. Confidence: high.
7. **Position: p = get_position(acc, ins, as_of). p is None or p.settled == 0 -> NOT_HELD** (account, instrument, as_of filled).
   Evidence: 0028, 0066, 0083, 0095, 0114, 0124, 0149, 0154, 0165 (never held); 0148 (settled 0). Stated qty irrelevant (oracle Q20: ESCALATE rejected for 0066). Settled 0 is NOT_HELD, not CONFIRMED 0 (oracle Q19). Confidence: high.
8. **Stated quantity given and it differs from settled+pending by more than ~10% -> ESCALATE** (account/instrument filled).
   Evidence: escalated ratios 1.50 (0050, 0088), 0.85 (0086, 0093), 1.56 (0168), 0179 (sq 11,288 vs settled 11,067 but settled+pending 41,173); confirmed ratios all within 0.93-1.08, incl. 0056 (sq 26,713 vs settled 8,536 but settled+pending 24,734 -> 1.08). Oracle Q3 (0179 CONFIRMED rejected: 'number doesn't match ours closely enough') confirms the base is settled+pending, not settled; Q5 (0056 ESCALATE rejected, 'fine to confirm') agrees. Threshold between 8% and 15% (no case in between, untestable with oracle); chose 10% relative to settled+pending. Confidence: high (base), medium (exact threshold).
   Unexplained escalations are operator noise: 0018, 0024, 0052, 0127, 0191 all accepted as CONFIRMED by the oracle (Q1, Q2, Q6, Q7, Q21).
9. **Otherwise CONFIRMED** with settled; report pending and pending_date when get_position's pending > 0.
   Evidence: 85 confirmed; pending reported in 25 cases, omitted in 0064, 0163 (mistakes: oracle Q10 accepted 0163 with pending; Q4 rejected 0001 without pending; Q5 says pending 'needs to be in there'). Confidence: high.

## Oracle log (21 of 25 used)
| # | case | response | acceptable | reason |
|---|------|----------|-----------|--------|
| 1 | P4-0018 | CONFIRMED 8,397 | yes | Looks right. |
| 2 | P4-0024 | CONFIRMED 10,390 | yes | Looks right. |
| 3 | P4-0179 | CONFIRMED 11,067 (+30,106 pending), stated 11,288 | no | Their number doesn't match ours closely enough; that goes to escalation. |
| 4 | P4-0001 | CONFIRMED 6,104 without pending | no | The pending amount handling isn't right. |
| 5 | P4-0056 | ESCALATE | no | Fine to confirm, but the pending amount and its settlement date need to be in there. |
| 6 | P4-0052 | CONFIRMED 1,422,600 | yes | Looks right. |
| 7 | P4-0191 | CONFIRMED 16,784 + 47 pending | yes | Looks right. |
| 8 | P4-0163 | CONFIRMED 3,922 + 29 pending | yes | Looks right. |
| 9 | P4-0175 | CONFIRMED (gmail sender) | no | That sender isn't on the client's domain, so we treat them as unauthorized. |
| 10 | P4-0152 | REQUEST_INFO (gmail sender) | no | same as above |
| 11 | P4-0033 | CONFIRMED as_of=request date, as_of_assumed=true | no | No as-of date, so we go back and ask for one. |
| 12 | P4-0025 | CONFIRMED using sender's account among 3 candidates | no | We can't tell which account they mean, so we ask them to clarify. |
| 13 | P4-0080 | REQUEST_AUTHORIZATION (contact on other account) | yes | Looks right. |
| 14 | P4-0143 | REQUEST_AUTHORIZATION (contact other account, no instrument) | yes | Looks right. |
| 15 | P4-0094 | REQUEST_INFO (no as_of) | no | Not sure this is right, please double-check. (oracle error, see 18) |
| 16 | P4-0014 | REQUEST_AUTHORIZATION (proton sender, no as_of) | yes | Looks right. |
| 17 | P4-0099 | REQUEST_INFO (proton sender, ambiguous account) | no | That sender isn't on the client's domain... |
| 18 | P4-0094 | REQUEST_AUTHORIZATION | no | No as-of date, so we go back and ask for one. |
| 19 | P4-0148 | CONFIRMED settled 0 | no | The account doesn't hold that security as of that date. |
| 20 | P4-0066 | ESCALATE (no position, stated qty) | no | The account doesn't hold that security as of that date. |
| 21 | P4-0127 | CONFIRMED 619,051 | yes | Looks right. |

(Note: a malformed invocation failed JSON parsing before reaching the oracle and did not consume budget; questions_left confirms 21 used.)
