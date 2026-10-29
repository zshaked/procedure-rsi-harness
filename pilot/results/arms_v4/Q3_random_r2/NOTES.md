# Notes

## Rules I believe
1. Account text must resolve to exactly one account (search_accounts); missing/ambiguous -> REQUEST_INFO.
2. Sender must have an unexpired level>=3 entitlement on that account, else REQUEST_AUTHORIZATION (checked before instrument/date problems).
3. Instrument missing/unresolved/ambiguous -> REQUEST_INFO.
4. Legal hold -> ESCALATE (guess, never observed).
5. Date: parse the body; none -> sent date with as_of_assumed=true. Non-business day (weekend/holiday, incl. an assumed sent date) or future date -> REQUEST_INFO (no roll-back).
6. Settled = all-sub-account ledger sum with date <= as_of, split-adjusted for splits on/before as_of (ignore later txns and later splits). Do not use get_position_summary.
7. Client-stated figure that differs from ours -> ESCALATE. Zero position -> NOT_HELD.
8. Pending = matched instructions settling after as_of and within 30 days of sent (horizon is a guess).

## Oracle questions (15 used)
Q0184 AUTH (level 1) ok. Q0158 ESCALATE (figure mismatch) ok. Q0190 ESCALATE mismatch (SA id, Sunday date) ok.
Q0059 CONFIRMED with rolled-back Saturday date: REJECTED ("not a business day; we ask them") -> changed to REQUEST_INFO.
Q0131 INFO (Sunday date) ok. Q0081, Q0066, Q0037, Q0075, Q0095, Q0118 AUTH (level 1/2) ok.
Q0198 INFO (sent date is Good Friday holiday) ok. Q0171 INFO (no instrument) ok.
Q0051 INFO (future as-of date; my guess) ok. Q0057 INFO (Sunday) ok.

## Least sure
Pending-instruction window and whether past-dated matched instructions count; split handling (never exercised); legal_hold / no_email_confirm outcomes; histories Q0022 and Q0024 disagree with my rules (likely operator mistakes); tolerance on stated-figure mismatch.
