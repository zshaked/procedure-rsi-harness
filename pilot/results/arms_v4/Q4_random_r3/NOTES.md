# Notes (random-question arm, r3)

## Rules believed
- Resolve account via search_accounts(mention) and instrument via search_instruments (ticker/old ticker/ISIN/name).
- Authorization first: unique account needs sender domain in the account profile's domains AND an unexpired entitlement level >= 2 (level 1 insufficient). With ambiguous/missing account: REQUEST_AUTHORIZATION only if the sender domain matches no entitled account; otherwise REQUEST_INFO.
- Ambiguous/missing instrument or missing date: REQUEST_INFO (fill ids where resolved).
- Date: relative to `sent` (month-end = last day of prior month, yesterday), US M/D/Y; weekend/holiday rolls back to previous business day.
- Settled = sum of ledger across all sub-accounts up to as_of, pre-split rows times ratio when split date <= as_of (not get_position_summary).
- Stated client figure differing from settled (or settled+pending) by more than ~10%: ESCALATE. Zero position: NOT_HELD.
- Pending = matched instructions settling after as_of; pending_date = latest. Unmatched/cancelled ignored.
- legal_hold / no_email_confirm: ESCALATE (guess, never observed).

## Oracle questions (15)
0133 CONFIRMED yes. 0155 CONFIRMED (4% off) no: escalate; kept 10% tolerance since 0104 (8%) and histories contradict. 0186 INFO for ambiguous account: no (entitlement); unexplained, treated as noise. 0176 ESCALATE yes. 0140 AUTH no: wanted INFO; led to domain-vs-entitled rule. 0119 CONFIRMED with pending 581: no (pending needed); unexplained, unchanged. 0052 AUTH yes. 0125 INFO no: sender domain unregistered, so AUTH; added domain rule. 0050 AUTH yes. 0097 AUTH no ("wrong security"); unexplained, unchanged. 0028 INFO yes. 0026 AUTH yes. 0037 INFO yes. 0104 ESCALATE (8% off) no: confirm; tolerance raised to 10%. 0158 INFO yes.

## Least sure
Tolerance threshold (4% vs 8% answers conflict), pending rule/date choice, flag handling, zero-position with stated figure (ESCALATE), 0119/0097/0186 rejections.
