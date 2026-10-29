# NOTES

## Rules (in order)
1. Unknown sender, or sender domain not registered to any of their accounts (free-mail): REQUEST_AUTHORIZATION.
2. Account via search_accounts; ambiguous or missing: REQUEST_INFO. Unique account needs unexpired entitlement, level >= 2, sender domain in that account's domains, else REQUEST_AUTHORIZATION (before info checks).
3. Missing/unknown instrument, no date, or date after sent: REQUEST_INFO.
4. as_of = stated date (relative phrases from sent), moved back to previous business day. Settled = ledger sum over all sub-accounts to as_of; splits dated <= as_of multiply earlier rows. Pending = matched instructions settling after as_of, date = latest.
5. legal_hold: ESCALATE. no_email_confirm: ignored.
6. Settled 0: NOT_HELD (beats figure mismatch).
7. Client figure vs settled+pending off by >10%: ESCALATE, else CONFIRMED.

## Oracle (15 of 15 used)
1. Q4-0033 no date, REQUEST_INFO: ok.
2. Q4-0032 valid entitlement, foreign domain, AUTH: ok.
3. Q4-0077 figure 8% off, CONFIRMED: ok.
4. Q4-0155 figure matches settled only, CONFIRMED: rejected. Compare to settled+pending.
5. Q4-0064 NOT_HELD: ok.
6. Q4-0130 zero holding, client figure, ESCALATE: rejected, NOT_HELD. Moved NOT_HELD first.
7. Q4-0055 no account named, REQUEST_INFO: ok.
8. Q4-0083 future date, REQUEST_INFO: rejected, irrelevant reason; see 15.
9. Q4-0174 unauthorised, no date, AUTH: ok.
10. Q4-0045 no instrument, REQUEST_INFO: ok.
11. Q4-0138 level 1, AUTH: ok.
12. Q4-0054 no-email account, ESCALATE: rejected; confirm with pending (settle date before sent still counts). Dropped no_email rule.
13. Q4-0114 legal hold, ESCALATE: ok.
14. Q4-0049 former ticker, CONFIRMED: ok.
15. Q4-0134 future date, REQUEST_INFO: ok; treated 8 as noise.

## Least sure
Tolerance (8-15%); negative settled (left CONFIRMED); transaction exactly on as_of included; "month-end" sent on the 31st uses prior month; split ignored when after as_of; as_of_assumed never true; sub-account means whole account.
