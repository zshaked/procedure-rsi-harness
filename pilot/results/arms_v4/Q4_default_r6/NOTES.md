# Rules I believe the desk follows
1. Sender must be a known contact. Account is resolved from the mention (name, short name, ACC id, SA id). If the account is missing, unknown or ambiguous: REQUEST_INFO when the sender's domain matches any candidate/entitled account, else REQUEST_AUTHORIZATION.
2. Authorization: entitlement on that account, level >= 2, not expired at `sent`, and sender domain in the account profile domains (free-mail never matches). Otherwise REQUEST_AUTHORIZATION. This is checked before missing-instrument / missing-date.
3. Instrument missing/unresolved/ambiguous: REQUEST_INFO. Old tickers resolve. Date missing or later than `sent`: REQUEST_INFO. A date equal to `sent` (or today/current/latest) rolls to the previous business day with as_of_assumed=true. This last point is a guess.
4. Non-business dates roll back to the previous business day.
5. legal_hold on account: ESCALATE. no_email_confirm appears to be irrelevant.
6. Settled = sum of ledger over ALL sub-accounts with date <= as_of, with split ratio applied to rows dated before a split whose date <= as_of. Zero: NOT_HELD, and the client's figure is ignored.
7. Pending = matched instructions with settle_date > as_of (regardless of `sent`), summed; pending_date is the latest. Unmatched and cancelled are ignored.
8. A client-stated figure is accepted within 10% of settled OR of settled+pending, else ESCALATE. Observed factors 0.93-1.08 are accepted; 0.85, 1.5 and 0.33 are escalated.

# Oracle log (15 used)
1 Q0032 non-free-mail domain mismatch -> AUTH: ok.
2 Q0077 stated x1.08 -> CONFIRMED: ok (tolerance >= 8%).
3 Q0183 stated = settled+pending -> CONFIRMED with pending: ok. This led me to compare against both.
4 Q0033 no date -> REQUEST_INFO: ok.
5 Q0114 legal hold -> ESCALATE: ok.
6 Q0054 no_email_confirm, I said ESCALATE: rejected, should CONFIRM with pending, so I dropped any no_email rule.
7 Q0083 future date -> REQUEST_INFO: ok.
8 Q0055 account missing, single entitlement, I inferred the account: rejected, so REQUEST_INFO.
9 Q0130 held 0 but client states a figure, I said ESCALATE: rejected, so NOT_HELD.
10 Q0168 expired entitlement -> AUTH: ok.
11 Q0084 two pendings, date = latest: ok.
12 Q0043 ambiguous account, unrecognised domain -> AUTH: ok.
13 Q0147 old ticker -> CONFIRMED: ok.
14 Q0045 instrument missing -> REQUEST_INFO: ok.
15 Q0066 matches only settled+pending -> CONFIRMED: ok.

# Least sure
Exact tolerance (8-15%), same-day/"today" handling, negative (short) positions, quarter or week phrasings, and split rows dated exactly on the split date.
