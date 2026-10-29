# Notes

## Rules (order matters)
1. Account unresolved/ambiguous (prefix names, no mention) -> REQUEST_INFO (ambiguity is NOT resolved via the sender's entitlements).
2. Authorization -> REQUEST_AUTHORIZATION unless contact exists, sender domain is in the account profile domains, and an entitlement for that exact account has level>=3 and is unexpired at `sent`. Runs before date checks.
3. Instrument unresolved -> REQUEST_INFO; date missing, non-business day (weekend/holiday, incl. relative dates), or after `sent` -> REQUEST_INFO (no rolling back).
4. legal_hold / no_email_confirm -> ESCALATE (account+instrument), after the INFO checks.
5. Settled = all ledger sub-accounts with date<=as_of, entries dated before a split (split date<=as_of) multiplied by ratio. Zero/empty -> NOT_HELD.
6. Pending = sum of "matched" instructions with settle_date>as_of (raw qty), pending_date = latest. as_of_assumed always False.

## Oracle (15)
1. Q1-0005 AUTH ok -> history INFO was an operator mistake (same for 0022).
2. Q1-0017 weekend rolled back: rejected -> INFO.
3. Q1-0016 assumed prior-business-day date: rejected -> INFO.
4. Q1-0019 NOT_HELD ok (empty ledger).
5. Q1-0195 expired level-3 AUTH ok.
6. Q1-0111 ESCALATE rejected only because Sat date -> INFO checks precede ESCALATE.
7. Q1-0095 pending already past sent, split after as_of: ok.
8. Q1-0121 split before as_of adjusted: ok.
9. Q1-0128 pending after split: raw, ok.
10. Q1-0092 "yesterday" with as_of_assumed false: ok.
11. Q1-0134 NOT_HELD zero after sale: ok.
12. Q1-0041 ambiguous name -> INFO ok.
13. Q1-0064 ESCALATE rejected (no date).
14. Q1-0053 future date INFO ok.
(1 unused.)

## Least sure
ESCALATE triggers (legal_hold vs no_email_confirm) never verified on a clean case; when as_of_assumed should be true (never found); AUTH vs INFO ordering for unresolved accounts.
