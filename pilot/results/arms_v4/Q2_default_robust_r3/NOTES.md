# Notes

## Rules believed (procedure.py)
1. Account text must resolve to exactly one account (else REQUEST_INFO; entitlements do not disambiguate).
2. Authorization (checked before instrument resolution): contact has an unexpired entitlement on that account at level >= 2, and sender domain is in the account profile's domains (free-mail fails). no_email_confirm also forces authorization (untested).
3. Instrument must resolve uniquely (ticker, old ticker, name, id); otherwise REQUEST_INFO.
4. As-of date: parsed from body (many formats, relative ones against `sent`); non-business day moves to previous business day; no date means sent date with as_of_assumed true.
5. Settled = sum of ledger rows over all sub-accounts dated <= as_of, rows before a split multiplied by the ratio when as_of >= split date.
6. legal_hold gives ESCALATE. Zero settled gives NOT_HELD (takes priority over a mismatch). Client's stated figure must equal settled or settled + matched pending; otherwise ESCALATE.
7. CONFIRMED reports matched instructions with settle_date > as_of: summed quantity, latest settle date.

## Oracle log (15 used)
- Q2-0006 CONFIRMED: rejected ("number doesn't match"), yet stated equals settled. Logged as one contradiction, no change (rule has 2+ supporting cases, R2). Treated as noise.
- Q2-0097 (stated equals settled, pending present): accepted.
- Q2-0075 (weekend date, stated figure): accepted.
- Q2-0123 NOT_HELD: accepted. Q2-0096 legal hold ESCALATE: accepted.
- Q2-0036 corporate domain mismatch gives authorization request: accepted.
- Q2-0128 split, stated pre-split figure gives ESCALATE: accepted.
- Q2-0025 pending with settle date before sent: accepted.
- Q2-0069 two matched instructions: earliest date rejected, sum with latest date accepted. Changed.
- Q2-0051 stated = settled + pending: ESCALATE rejected, so changed to accept either.
- Q2-0145 legal hold with level 1 gives authorization: accepted.
- Q2-0157 stated nonzero but zero held: ESCALATE rejected, so NOT_HELD first. Changed.
- Q2-0157 NOT_HELD: accepted.
- Q2-0041 missing instrument, level 1: REQUEST_INFO rejected, so authorization is checked first. Changed.

## Least sure
Q2-0006 anomaly; no_email_confirm handling; matched pending with zero settled; future-dated requests; other relative-date phrasings; ambiguity versus authorization when the account is ambiguous.
