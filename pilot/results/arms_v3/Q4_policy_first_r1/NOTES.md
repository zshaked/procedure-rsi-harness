# Induced desk rules (in order)
1. Sender domain not in any client profile (gmail/yahoo/outlook/proton) -> REQUEST_AUTHORIZATION.
2. Account text (id, sub-account, name, short name, unique name prefix) must resolve to exactly one account, else REQUEST_INFO (no disambiguation by entitlement).
3. Authorized = sender domain in that account's profile domains AND contact entitlement on it, level >= 2, not expired; else REQUEST_AUTHORIZATION.
4. Instrument (ticker/old ticker/name/ISIN) unresolved, no date, or date after `sent` -> REQUEST_INFO.
5. legal_hold -> ESCALATE.
6. as_of = requested date, rolled back to previous business day if weekend/holiday; month-end/yesterday relative to sent. as_of_assumed false.
7. settled = all sub-accounts, ledger date <= as_of, split-adjusted when split date <= as_of (not the position-summary view).
8. pending = matched instructions settling after as_of (sum, latest date).
9. Client figure must be within 10% of settled or settled+pending, else ESCALATE.
10. settled 0 -> NOT_HELD; else CONFIRMED.

Harness: 25/25 (Q4-0000, Q4-0013 operator replies explained by tolerance / pending).

# Oracle log (15 used, all "acceptable" unless noted)
1 0000 CONFIRMED 4% diff - ok; 2 0104 CONFIRMED 8% - ok; 3 0183 fig=settled+pending CONFIRMED - ok;
4 0044 CONFIRMED 15% - NOT ok ("doesn't match closely enough; escalation"); 5 0054 no_email_confirm CONFIRMED - ok;
6 0114 legal hold ESCALATE - ok; 7 0118 legal hold+unauthorized REQ_AUTH - ok; 8 0083 future date REQUEST_INFO - ok;
9 0064 NOT_HELD settled null - ok; 10 0067 no date + figure REQUEST_INFO - ok; 11 0084 month-end as_of_assumed false - ok;
12 0148 same-day ledger included - ok; 13 0156 sub-account mention -> whole-account total - ok;
14 0066 12.8% vs settled, 4% vs settled+pending CONFIRMED - ok; 15 0147 old ticker CONFIRMED - ok.

# Least sure
Exact tolerance (between 8% and 15%); meaning of no_email_confirm and as_of_assumed (never true); split handling when as_of precedes split; ordering of freemail check vs ambiguity.
