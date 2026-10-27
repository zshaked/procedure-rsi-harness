# Induced desk procedure (history-only arm)

Rules, in order:
1. Resolve account (search_accounts on the mention; ACC-/SA- ids accepted) and instrument (ticker, old ticker, name or ISIN). Missing, unknown or ambiguous (e.g. "Falcon Capital" matching I/II/III) -> REQUEST_INFO. The account is never inferred from the sender's entitlements (Q2-0002, Q2-0003). A future date -> REQUEST_INFO.
2. Authorization -> otherwise REQUEST_AUTHORIZATION. The sender's domain must be in the client profile domains (free-mail fails, Q2-0014), and the contact needs an entitlement on that account with level >= 2 that has not expired at `sent` (Q2-0009, Q2-0018).
3. legal_hold or no_email_confirm -> ESCALATE (a guess: no history covers it).
4. as_of: the requested date, rolled back to the previous business day if it falls on a weekend or holiday (Q2-0017). If no date is given, the previous business day before `sent`, with as_of_assumed=true. Relative dates ("yesterday", "month-end", "end of last month") are resolved from `sent`.
5. Settled = the ledger summed across ALL sub-accounts with date <= as_of, adjusting for splits that take effect on or before as_of (Q2-0004 needs every sub-account). get_position_summary is a trap: it covers the primary sub-account only and uses the day before as_of.
6. If the client states a figure that differs from settled -> ESCALATE (fits 7 escalations). A negative balance -> ESCALATE. Zero -> NOT_HELD. Otherwise CONFIRMED.
7. Pending = matched instructions settling after as_of (sum; latest date). Unmatched and cancelled instructions are ignored (Q2-0021).

Inputs: a dump of the tool data for every history case, plus surveys of phrasing and mentions in the unlabeled set to make the parsing robust. Harness: 24/25. Q2-0006 (figure matches, escalated anyway) is treated as an operator mistake.

Least sure about: the legal_hold/no_email_confirm outcome, how multiple pending instructions are aggregated, the future-date and "today" handling, and whether a stated figure matching settled+pending would count as a match.
