# Spec: holding-confirmation desk (final, after oracle)

Evidence = history case ids (H) and unlabeled cases (U), analysed with scratch/sim.py and scratch/facts.py; O# = oracle question below.

Decision order (first match wins):

1. **No account named** (`mentions.account_text` empty, nothing in body) -> if the sender is unknown or writes from a domain that is not a registered domain of any account they are entitled to (free-mail): REQUEST_AUTHORIZATION (H0009); else REQUEST_INFO (O9). The account is never inferred from entitlements. Confidence: medium-high.
2. **Account text resolves to 0 or >1 accounts** (`search_accounts`, incl. sub-account ids, short names, name prefix) -> REQUEST_INFO; ambiguity is not broken by entitlements/domain. H0002, H0017, H0022. High.
3. **Sender domain not in the account's `profile.domains`** -> REQUEST_AUTHORIZATION, even with a valid entitlement. H0008 (gmail, level 3), O15 (other corporate domain, level 3). High.
4. **No unexpired entitlement on the account** (`expires` < sent) -> REQUEST_AUTHORIZATION. H0004/0005/0018/0020, O12 (expired), O14. High.
5. **Legal hold** on the account -> ESCALATE. O4; O13 says it outranks a level-1 entitlement (single oracle answer, oracle can be wrong). Medium-high (ordering vs rule 6: medium).
6. **Entitlement level < 2** -> REQUEST_AUTHORIZATION. H0011; H0012/0013 (level 2 ok). High.
7. **`no_email_confirm` flag is ignored** -> O5 ("fine to confirm"). Medium.
8. **Instrument missing/unresolved/ambiguous, or no date** -> REQUEST_INFO. H0014, H0016, H0002. High.
9. **Dates**: ISO, M/D/YYYY (D/M if first part >12), D-Mon-YYYY, "Month D, YYYY", "D Month YYYY", weekday prefixes, "close of business", "yesterday" (sent-1), "today", "month-end"/"end of last month"/"the last day of last month" (last calendar day of month before sent). Forwarded "Date:" header ignored. A date that is non-business is rolled to the previous business day (get_calendar). H0006, H0012, H0013, H0019, H0003, H0021. High.
10. **Requested date on/after the sent date** -> REQUEST_INFO. O6 (future date). Same-day treated as future (unverified). Medium.
11. **Settled** = sum of `get_ledger` over ALL sub-accounts, date <= as_of inclusive (O11), transactions before a split dated <= as_of multiplied by the ratio (H0019). Even when a sub-account is named, the whole account is reported (U0091/U0115). Not `get_position_summary`. High.
12. **Settled == 0** -> NOT_HELD with as_of (O7), and this beats a stated client figure (O8). Negative settled -> ESCALATE (guess, no evidence). Medium / low.
13. **Pending** = matched instructions with settle_date > as_of (even if before sent: O5); pending = sum, pending_date = latest settle_date (H0013, O10). Unmatched/cancelled ignored (H0010, H0021). High.
14. **Client figure** stated (records show / we show / our figure is / we have ...): if it is within 10% of settled OR of settled+pending -> fine; else ESCALATE. H0001/0003/0024 (-15%) and O2 (+50%) escalate; H0000 (+4%), O1 (+8%), H0013 (-7% of settled+pending), O3 (exactly settled+pending) confirm. Tolerance between 8% and 15%; 10% chosen. Medium.
15. Otherwise **CONFIRMED**: account_id, instrument_id, as_of, settled, pending/pending_date only when pending > 0. `as_of_assumed` = false always (the desk never assumes a date; it asks). Low-medium on as_of_assumed.

ESCALATE responses carry account_id and instrument_id where resolved.

## Oracle log (15/15 used)
| # | case | response tested | answer |
|---|------|-----------------|--------|
| O1 | Q4-0077 | CONFIRMED 284227 (client +8%) | acceptable |
| O2 | Q4-0036 | CONFIRMED 943836 (client +50%) | NOT: "doesn't match closely enough; escalation" |
| O3 | Q4-0183 | CONFIRMED 7053 + pending 16628 (client = settled+pending) | acceptable |
| O4 | Q4-0114 | ESCALATE (legal hold, authorized) | acceptable |
| O5 | Q4-0054 | REQUEST_AUTHORIZATION (no_email_confirm) | NOT: "fine to confirm, but pending amount and date needed" |
| O6 | Q4-0083 | REQUEST_INFO (date after sent) | acceptable |
| O7 | Q4-0107 | NOT_HELD (ledger empty) | acceptable |
| O8 | Q4-0130 | ESCALATE (held 0, client says 5570) | NOT: "doesn't hold that security as of that date" |
| O9 | Q4-0055 | REQUEST_INFO (no account, corporate sender) | acceptable |
| O10 | Q4-0084 | CONFIRMED, pending 1165, date = latest 2026-05-07 | acceptable |
| O11 | Q4-0148 | CONFIRMED incl. txn dated on as_of | acceptable |
| O12 | Q4-0190 | REQUEST_AUTHORIZATION (expired entitlement) | acceptable |
| O13 | Q4-0118 | ESCALATE (legal hold, level-1 sender) | acceptable (I mis-sent account_id; oracle seems to grade mainly outcome) |
| O14 | Q4-0082 | ESCALATE (legal hold, foreign domain, no entitlement) | NOT: "isn't entitled; authorization needed" |
| O15 | Q4-0032 | CONFIRMED (entitled, other corporate domain) | NOT: "sender address isn't one of the client's registered domains" |
