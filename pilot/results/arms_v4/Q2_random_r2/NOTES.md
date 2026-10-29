# Notes

## Rules I believe the desk follows
1. Resolve account (id / sub-account / name / short name / name prefix). Missing or ambiguous (several matches) -> REQUEST_INFO. Missing or ambiguous instrument -> REQUEST_INFO. Future as-of date -> REQUEST_INFO (guess).
2. Authorization: sender needs an unexpired entitlement of level >= 2 on the resolved account AND sender email domain in the account's profile domains. Otherwise REQUEST_AUTHORIZATION.
3. As-of: explicit date, relative date (yesterday, month-end), or sent date if absent (as_of_assumed true). Non-business day -> previous business day (assumed stays false).
4. Settled = sum of ledger across all sub-accounts up to as_of inclusive, times split ratio for entries before a split dated <= as_of.
5. Pending = matched instructions settling after as_of (split-adjusted if the split falls between as_of and settle date: guess). Cancelled and unmatched are ignored.
6. Client's stated figure is acceptable if it equals settled, settled + pending, or the pre-split raw sum. Otherwise ESCALATE. legal_hold -> ESCALATE. Zero position -> NOT_HELD (guess).

## Oracle questions (15 used)
- 0117 sat date -> prior Friday: ok.
- 0051 I had ESCALATE: rejected, stated figure = settled + matched pending; now CONFIRMED with pending.
- 0096 legal hold, ESCALATE: ok.
- 0128 I had ESCALATE (stated pre-split figure): rejected; now accept pre-split raw sum and CONFIRM with adjusted figure.
- 0073 confirmed with pending: ok.
- 0188 mismatch, ESCALATE: ok.
- 0104 ambiguous account, REQUEST_INFO: ok.
- 0143 level 1, REQUEST_AUTHORIZATION: ok.
- 0076 no date, split + pending: rejected ("pending amount handling"); I guessed split-adjusting pending (x3). Unverified.
- 0120 no account, future date, INFO: ok.
- 0061 ambiguous prefix, INFO: ok.
- 0161, 0183 domain mismatch, AUTHORIZATION: ok.
- 0055 assumed date on holiday moves to prior business day: ok.
- 0141 holiday date adjusted: ok.

## Least sure of
Q0076 pending handling (could instead be omit-when-date-assumed), NOT_HELD triggers, no_email_confirm flag (ignored), future dates, unmatched pending, history Q0006 treated as operator mistake. Harness full agreement 24/25.
