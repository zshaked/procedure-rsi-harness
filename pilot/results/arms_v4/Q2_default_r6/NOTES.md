# Notes (Q2_default_r6)

## Rules believed
1. Account (search_accounts on mention) and instrument (search_instruments) must each resolve to exactly one; otherwise (missing, ambiguous e.g. "Falcon Capital", no instrument) -> REQUEST_INFO. This check comes before authorization.
2. Authorization: sender contact needs an unexpired (expires >= sent) entitlement level >= 2 on the resolved account AND sender domain in the account profile's domains. Otherwise REQUEST_AUTHORIZATION.
3. legal_hold -> ESCALATE. no_email_confirm: guessed ESCALATE (untested).
4. Position = sum of ledger qty over all sub-accounts with date <= as_of, each tx multiplied by split ratio when split date <= as_of and tx date < split date. Do not use get_position_summary.
5. as_of: non-business day rolls back to previous business day; no date -> sent date (rolled back), as_of_assumed true; relative dates ("yesterday", "month-end") resolved from sent; future date -> REQUEST_INFO (untested). Forwarded header "Date:" lines are ignored.
6. Pending = matched instructions with settle_date > as_of; qty summed, pending_date = latest date. Unmatched/cancelled ignored.
7. If the client states a figure it must equal settled + pending; any difference -> ESCALATE (also when ours is zero). Else zero position -> NOT_HELD, else CONFIRMED.

## Oracle (15 used)
- Q2-0006 CONFIRMED w/ pending: no (escalation; figure vs ours). Led to rule 7.
- Q2-0089 pending date min: no; latest date + summed qty: yes. Rule 6.
- Q2-0097 fig==settled with matched pending: no. Rule 7.
- Q2-0051 settled+pending==fig: yes (first try wasted: forgot instrument id).
- Q2-0025 pending with settle date before sent: yes.
- Q2-0169 fig vs zero position: ESCALATE yes.
- Q2-0096 legal hold: ESCALATE yes.
- Q2-0066 outlook sender, zero position, AUTH: no ("size" reason, looks like oracle noise); ignored.
- Q2-0198 1.4M position CONFIRMED: yes (no size rule).
- Q2-0196 domain mismatch AUTH: yes. Q2-0095 NEC ESCALATE: no (domain not registered).
- Q2-0055 holiday sent, assumed date rolled back: yes. Q2-0153 NOT_HELD: yes.

## Least sure
no_email_confirm outcome, future dates, matched settle_date == as_of, Q2-0006-type exact-match vs level, ambiguity of Q2-0066.
