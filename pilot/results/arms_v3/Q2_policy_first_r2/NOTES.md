# NOTES

**Rules, in order**
1. Account or instrument missing or ambiguous → REQUEST_INFO. Lookups use the search tools, which cover sub-accounts, short names, old tickers and ISINs. Entitlements are never used to guess.
2. Authorization needs a contact, a sender domain in the client's domains, and an unexpired entitlement at level ≥2. Otherwise → REQUEST_AUTHORIZATION. This comes before legal hold.
3. legal_hold or no_email_confirm → ESCALATE.
4. A weekend or holiday rolls back to the previous business day (not assumed). No date → the business day before `sent`, assumed. Future date → REQUEST_INFO.
5. Settled = all sub-accounts, split-adjusted. Pending = matched instructions settling after as_of, summed, with the latest date.
6. Settled 0 → NOT_HELD.
7. Client figure ≠ settled+pending → ESCALATE (1% tolerance, wider for k/mm). A pre-split figure is accepted.
8. Otherwise → CONFIRMED.

**Inputs:** histories (harness 25/25), unlabeled cases for rare situations, oracle on my own outputs.

**Oracle log (15)**
- 0006 CONFIRMED → no, mismatch
- 0097 CONFIRMED (figure = settled) → no, mismatch
- 0051 typo id → wrong security
- 0051 figure = settled+pending, CONFIRMED → yes
- 0069 → pending date wrong (min→max)
- 0055 no date → yes
- 0096 legal hold → yes
- 0142 legal hold, level 1, REQUEST_AUTH → yes
- 0095 ESCALATE → no, domain
- 0169 ESCALATE → no, NOT_HELD
- 0191 sub-account, whole account → yes
- 0025 → yes
- 0112 → yes
- 0128 ESCALATE → no, confirm
- 0128 split-adjusted CONFIRMED → yes

**Least sure:** no_email_confirm for an authorized sender, the tolerance size, future dates, and pending on NOT_HELD.
