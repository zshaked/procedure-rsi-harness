# NOTES

## Rules believed
- Resolve account and instrument via the search tools; fall back to ids in the body.
- Sender "recognised" = known contact, email domain in the account's profile domains, unexpired entitlement. Not recognised for any candidate account (resolved hits, or the sender's own accounts if none named) -> REQUEST_AUTHORIZATION. Checked before missing/ambiguous fields.
- Ambiguous or missing account/instrument -> REQUEST_INFO. Unique account but entitlement level 1 -> REQUEST_AUTHORIZATION.
- Date relative to `sent`; missing or future date -> REQUEST_INFO; non-business day rolls back to previous business day; month-end = last month's end.
- Settled = sum of ledger over ALL sub-accounts, date <= as_of (inclusive), x split ratio when split date <= as_of and entry predates it. Pending = matched instructions settling after as_of (sum, latest date). get_position_summary is not used.
- legal_hold -> ESCALATE. Zero position -> NOT_HELD. Client figure vs settled+pending differing by more than 10% -> ESCALATE. Else CONFIRMED with pending if any.
- no_email_confirm has no effect.

## Oracle (15 budget, 14 used)
1 Q0155 CONFIRMED w/ pending: no (figure matches neither; total used) - kept escalate.
2 Q0114 legal-hold ESCALATE: yes.
3 Q0054 no_email_confirm ESCALATE: no, should confirm with pending - removed NE rule.
4 Q0130 zero holding + mismatching figure: NOT_HELD, not ESCALATE - reordered.
5 Q0083 future date INFO: yes. 6 Q0148 inclusive boundary: yes.
7 Q0055 no account named: INFO yes. 8 Q0043 ambiguous + unrecognised: AUTH yes.
9 Q0168 expired entitlement: AUTH yes. 10 Q0045 no instrument: INFO yes.
11 Q0077 +8%, 12 Q0094 -7%: CONFIRMED yes. 13 Q0126 pending settling before sent: yes. 14 Q0066 multi pending: yes.

## Least sure
Tolerance threshold (8-15%); settled=0 with pending>0; legal-hold precedence; as_of_assumed never used.
