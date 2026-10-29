# NOTES

## Rules (procedure.py, harness full agreement 23/25)
Order: resolve account text (unique hit, else INFO) -> account not in sender's entitlements -> INFO -> entitlement level>=3, unexpired (expires>=sent), sender domain in profile domains, else REQUEST_AUTHORIZATION -> instrument unique (else INFO) -> date (explicit/yesterday/month-end; none, non-business-day, or after sent -> INFO) -> legal_hold/no_email_confirm -> ESCALATE -> client figure vs ours >5% -> ESCALATE -> empty/zero -> NOT_HELD -> CONFIRMED. Settled = all sub-accounts' ledger <= as_of; pending = matched instructions settling after as_of; as_of_assumed false.

## Plan (S2 then S3) and answers (15 asked; 0 left)
1 Q1-0041 ambiguous -> INFO: ok
2 Q1-0168 no instrument -> INFO: ok
3 Q1-0048 no date -> INFO: ok
4 Q1-0028 empty ledger -> NOT_HELD: ok (history 0019 INFO treated as mistake)
5 Q1-0111 legal_hold ESCALATE: rejected, non-business date -> INFO. Flags now after date.
6 Q1-0064 no_email_confirm, ESCALATE: rejected, no date -> INFO. Same.
7 Q1-0195 expired entitlement -> AUTH: ok
8 Q1-0092 valid entitlement, "yesterday", as_of_assumed false: ok
9 Q1-0128 as_of day before split, raw: ok
10 Q1-0121 as_of after split, split-adjusted 11276: REJECTED "settled wrong". Rule had no history support, so switched to raw ledger sum (SPLIT_ADJUST=False).
11 Q1-0095 pending between as_of and sent: ok
12 Q1-0120 matched instr. before as_of excluded: REJECTED, client figure 7% off -> escalation. Discovered qty_mismatch; tolerance 5% (4% accepted in histories, 7% escalated).
13 Q1-0114 sub-account, 50% mismatch -> ESCALATE: ok
14 Q1-0053 as_of after sent: REJECTED, date not yet happened -> INFO (future_date).
15 Q1-0081 unentitled account -> INFO: REJECTED, wants AUTH. Rule has 2 history cases (0005, 0022) so R2 needs a second contradiction; kept INFO (0008 history says AUTH).

## Unsure
Unentitled-account INFO vs AUTH; split handling; tolerance 5%; ESCALATE for flags; as_of_assumed never true; as_of==sent.
