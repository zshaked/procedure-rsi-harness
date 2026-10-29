# Rules believed (procedure.py)
Order: resolve account (search_accounts; 0 or >1 hits -> REQUEST_INFO; no mention -> sender's sole entitlement) -> authorization (contact has entitlement for that account, level>=3, not expired at sent date, else REQUEST_AUTHORIZATION) -> instrument resolution (ticker/old ticker/name/ISIN; fail -> REQUEST_INFO) -> date (none: sent date, as_of_assumed; explicit non-business day -> REQUEST_INFO; future -> INFO) -> no_email_confirm -> REQUEST_AUTHORIZATION -> legal_hold -> ESCALATE -> figure = sum of ledger over ALL sub-accounts, dated <= as_of, pre-split rows x ratio for splits dated <= as_of -> stated quantity differs -> ESCALATE; zero -> NOT_HELD; >= 1,000,000 -> ESCALATE; else CONFIRMED with pending = matched instructions settling within 10 days after sent.
Not used: get_position_summary (primary sub-account only, day before).

# Oracle log (15/15 used)
1 0153 auth (level 2): ok. 2 0142 auth: ok. 3 0176 auth: ok. 4 0169 auth: ok.
5 0195 ESCALATE on qty mismatch with Saturday date: rejected, non-business date -> ask; added the REQUEST_INFO rule.
6 0161 auth: ok. 7 0197 info (ambiguous account): ok. 8 0069 auth: ok.
9 0145 CONFIRMED 2.79M: rejected, large positions escalate; added 1,000,000 threshold.
10 0086 auth: rejected "no as-of date", but the email has a date; treated as oracle error, unchanged.
11 0192 auth despite Saturday date: ok (auth precedes date check; so history Q3-0022 is probably a mistake).
12 0167 auth: rejected "wrong account" (exact-name account vs sender's "X I" sibling).
13 0143 identical pattern: accepted, so 0167 treated as oracle error.
14 0105 info for ambiguous account though sender entitled to one: ok. 15 0139 auth: ok.

# Least sure
Large-position threshold (between 855k and 2.79M); pending horizon (7-12 days); legal_hold -> ESCALATE and no_email_confirm -> auth (unverified); split applied only if split date <= as_of; stated quantity compared to settled only; 0086 and 0167 might be real rules.
Harness: 24/25 full; remaining miss Q3-0022 (judged an operator mistake).
