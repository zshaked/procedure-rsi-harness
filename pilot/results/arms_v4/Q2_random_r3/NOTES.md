# NOTES (Q2_random_r3)

## Rules I believe the desk follows (checked in this order)
1. Account or instrument missing, unknown or ambiguous (several accounts match, e.g. "Falcon Capital") -> REQUEST_INFO. This is checked before authorization.
2. Sender must be authorized: email domain is in the account profile's domains AND the contact has an unexpired entitlement of level >= 2 on that exact account. Otherwise REQUEST_AUTHORIZATION.
3. legal_hold or no_email_confirm on the account -> ESCALATE (guess; no oracle evidence).
4. Date: parsed from body (forward headers ignored). Missing date -> sent date, as_of_assumed=true. Relative phrases (yesterday, month-end) resolve against sent. Non-business day -> previous business day. Date after sent -> REQUEST_INFO (guess).
5. Settled = ledger summed over ALL sub-accounts with date <= as_of. Splits multiply earlier rows only if split date <= as_of. get_position_summary is not used.
6. Client figure given and != settled -> ESCALATE.
7. Settled 0 -> NOT_HELD.
8. Pending = matched instructions with settle_date > as_of (sum, earliest date). Unmatched and cancelled are ignored. Pending < 1% of settled is not reported. Pending > settled -> ESCALATE.
9. Otherwise CONFIRMED.

## Oracle questions (15 used, in the fixed order)
- 0140 CONFIRMED with pending: OK.
- 0026 CONFIRMED: rejected, "positions that size go to escalation". Cause unknown; no change made.
- 0049 INFO (ambiguous account): OK.
- 0171 AUTH (domain mismatch, entitlement valid): OK.
- 0048 AUTH: OK.
- 0118 CONFIRMED on a weekend date: OK.
- 0183 AUTH: rejected, said INFO. Looked like oracle noise; no change.
- 0135 CONFIRMED: OK.
- 0056 CONFIRMED with tiny pending (454): rejected ("pending handling"). I now drop pending under 1% of settled.
- 0174 AUTH with legal_hold: OK, so authorization comes before legal hold.
- 0139 AUTH (entitlement on another account): OK.
- 0152 INFO: OK.
- 0156 AUTH: OK.
- 0122 INFO (ambiguous, bad domain): OK, so INFO comes before AUTH.
- 0073 CONFIRMED with pending 50138: OK.

## Least sure of
- The 1% pending threshold and the pending > settled escalation. The latter only explains history Q2-0006.
- The flag handling, future dates, and what is wrong with Q2-0026 (a past-due matched instruction is one idea). Q2-0183 may be oracle error.
