# Induced desk rules (history-only arm)

1. **Resolve** the account (id, sub-account, name, short name; prefix match only if it is unique) and the instrument (ticker, former ticker, name, ISIN). If either is missing or ambiguous (e.g. "Falcon Capital" giving I/II/III, or a duplicate short name), or the email asks for "the positions" in general, or the date is in the future: **REQUEST_INFO**.
2. If the client profile has a legal hold or no_email_confirm flag: **ESCALATE**. (This is a guess. No history shows it.)
3. **Authorization**: the sender must be a known contact with a live entitlement of level 2 or higher on that exact account, sending from one of the client's registered domains. Personal email addresses fail. Otherwise **REQUEST_AUTHORIZATION**.
4. **Figure**: sum the ledger across all sub-accounts (not get_position_summary, which uses only the primary sub-account and the day before) for entries dated on or before as_of. Apply a split when as_of falls on or after its date. A weekend or holiday rolls back to the previous business day. A missing date is assumed to be the previous business day before `sent` (as_of_assumed=true).
5. If the client quotes a figure that differs from ours: **ESCALATE**.
6. A zero position gives **NOT_HELD**. Otherwise **CONFIRMED**, with pending = the sum of *matched* instructions settling after as_of, and pending_date = the earliest of those dates.

**Inputs:** I took the rules from the 25 histories and the tool docstrings. I used the unlabeled set to test the date and quantity parsers, to check client figures against different ways of computing the position, and to find edge cases (sub-account netting to zero, "positions held" requests, duplicate short names). Harness: 24/25. I treat Q2-0006 (the client figure matches ours, yet it was escalated) as an operator mistake.

**Least sure:** whether a zero position with a quoted client figure should be NOT_HELD or ESCALATE (I chose ESCALATE); the outcome for the profile flags; the default date when none is given; how pending is aggregated when there are several instructions; and how a split is treated when it falls between as_of and the email date.
