# Notes

**Rules (in order):**
1. Resolve the account (id, sub-account, name, short name). If it is missing or matches more than one account: REQUEST_INFO. A sub-account resolves to its parent account, and the figure covers the whole account.
2. Sender check. The sender needs an entitlement on the account at level 2 or higher that has not expired at the sent date. Their email domain must be registered to that client, or to another client they are entitled on. Free-mail and unknown domains fail. Any failure: REQUEST_AUTHORIZATION.
3. If the client has `no_email_confirm`: REQUEST_AUTHORIZATION. If it has `legal_hold`: ESCALATE.
4. Resolve the instrument (ticker, old ticker, name, ISIN). If it is missing or ambiguous: REQUEST_INFO.
5. Date. If none is given, use the previous business day before sent and set as_of_assumed=true. Relative dates are allowed (yesterday, month-end). A weekend or holiday rolls back to the previous business day. A future date gets REQUEST_INFO.
6. Settled = ledger summed over all sub-accounts up to as_of, adjusted for splits. Never use the position summary. Settled of 0 or less: NOT_HELD.
7. Pending = matched instructions with settle_date after as_of. Report their sum, with pending_date set to the latest of those settle dates.
8. A client figure must equal settled+pending; the same total without the split adjustment also counts. Otherwise ESCALATE. Abbreviated figures match at the precision stated.

**Inputs:** I wrote scripts to survey all 200 requests against the tools, then wrote spec.md. I used all 15 oracle questions on rare or conflicting cases. They showed:
- the client figure is compared with settled+pending (this explains case 0006);
- free-mail senders and `no_email_confirm` both go to REQUEST_AUTHORIZATION;
- legal hold goes to ESCALATE;
- zero holdings are NOT_HELD;
- a figure that predates a split still matches;
- the no-date assumption above holds.

**Least sure:**
- The domain rule: the oracle accepted 0125 but rejected 0193, which may be a single oracle error.
- Matching tolerance and how pending dates are combined.
- How legal hold ranks against the instrument check.
- How future dates and "today" are handled.
