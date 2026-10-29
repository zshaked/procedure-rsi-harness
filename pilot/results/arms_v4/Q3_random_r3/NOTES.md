# NOTES (random arm, 15/15 oracle questions used)

## Rules in procedure.py (check order)
1. Account from mention via search_accounts; none or ambiguous -> REQUEST_INFO.
2. Sender must hold an unexpired level>=3 entitlement on the resolved account, else REQUEST_AUTHORIZATION (level 1-2, sibling account, unknown sender).
3. Instrument unresolved -> REQUEST_INFO.
4. Date: parse (ISO, dd-Mon-yyyy, M/D/Y, month names, "yesterday", month-end phrases); none given -> sent date, assumed=true. Non-business day or future date -> REQUEST_INFO.
5. no_email_confirm client -> REQUEST_AUTHORIZATION. legal_hold -> ESCALATE (guess).
6. Settled = sum of the whole ledger (all sub-accounts) with date <= as_of, split-adjusted when split date <= as_of. Not get_position_summary (primary sub-account only, previous day).
7. Client's stated figure differing by more than 5% -> ESCALATE; otherwise zero -> NOT_HELD, else CONFIRMED.
8. Pending: matched instructions settling 0-10 days after the email date (guess).

## Oracle log
1 Q3-0183 AUTH (level 2): ok.
2 Q3-0113 INFO (ambiguous account): ok.
3 Q3-0187 AUTH (level 2, Sunday date): rejected "wrong security"; read as noise, unchanged.
4 Q3-0049 AUTH (sibling-account entitlement): rejected "doesn't hold"; read as noise, unchanged.
5 Q3-0130 AUTH: ok. 6 Q3-0192 AUTH: ok. 7 Q3-0026 AUTH: ok. 8 Q3-0092 AUTH: ok.
9 Q3-0132 ESCALATE on a 2% claim gap: rejected "fine to confirm", so added a tolerance (5%, guessed between 2% and 7%).
10 Q3-0118 AUTH: ok.
11 Q3-0129 ESCALATE (no_email client): rejected, "must go through authorization", so no_email -> AUTH.
12 Q3-0078 ESCALATE (15% gap): ok.
13 Q3-0168 INFO (ambiguous account): rejected with an unrelated date reason; unchanged.
14 Q3-0058 INFO for Saturday date: ok, so non-business day -> INFO.
15 Q3-0066 AUTH: rejected, though the reason supports AUTH, so noise.

## Least sure of
- Claim tolerance (2% to 7% gap).
- Pending window (only Q3-0008 shows it).
- legal_hold outcome.
- Whether the date check comes before or after the authorization check (three weird oracle rejections).
- No account named: histories say AUTH (Q3-0024), I return INFO.
- Split handling.
