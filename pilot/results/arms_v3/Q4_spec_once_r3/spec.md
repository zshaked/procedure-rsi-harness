# Desk procedure spec (Q4)

Evidence: histories H (25 labelled), unlabeled U (175), tools.py docstrings, state via tools.
Confidence: H = high, M = medium, L = low.

## Pre-processing
1. **Ignore forwarded-header lines** (`From:`, `Date:`, `Subject:` …) when looking for the position date. U has many "Date: 2026-02-09" header lines that are the forward date, not the position date. (H, structural)
2. **Position date parsing**, relative to `sent`: ISO, M/D/YYYY (US order, e.g. 1/23/2026, 12/16/2025), `27-Jan-2026`, `January 27, 2026`, `Sat 3 Jan 2026`, `close of business 22 December 2025`; `yesterday` = sent-1; `month-end` / `end of last month` / `the last day of last month` = last calendar day of the month before `sent` (H 0003, 0012, 0013 use 2026-01-31 → reported 2026-01-30). (H)
3. **Business-day roll-back**: if the date is a weekend/holiday, the figure is given for the previous business day (get_calendar). H 0006 Sat 3 Jan → 2026-01-02; 0012/0013 → 2026-01-30; 0024 Sun 25 Jan → (escalated). (H)
4. **Client figure parsing**: "our records show N units", "our figure is N", "we show N", "we have N shares"; supports `12,500`, `12.5k`, `1.2mm`, negative. (H)

## Decision order
5. **Account resolution** from `mentions.account_text` via search_accounts (id, sub-account, name, short name, else name prefix). More than one match → REQUEST_INFO, *without* using the sender's entitlements to disambiguate (H 0002, 0017, 0022 — in each the sender is entitled to exactly one candidate, still REQUEST_INFO). No match / no account text → see 6. (H)
6. **Missing account**: H 0009 (gmail sender, no account) → REQUEST_AUTHORIZATION. With a corporate sender with exactly one entitlement it is unclear whether the desk infers the account. Initial guess: REQUEST_INFO unless sender is unauthorised-looking. (L) → oracle
7. **Authorization** (after a unique account is found, before checking that instrument/date are present — H 0008 has no instrument yet REQUEST_AUTHORIZATION): requires (a) sender is a known contact, (b) a non-expired entitlement on that account with level ≥ 2 (H 0011 level 1 → REQUEST_AUTHORIZATION; H 0012/0013/0021 level 2 → CONFIRMED), (c) sender e-mail domain is in the client profile's domains (H 0008: entitled level 3 but gmail.com → REQUEST_AUTHORIZATION). Expired entitlement (expires < sent) → REQUEST_AUTHORIZATION (M, by docstring "Expired entitlements are included"). Whether (c) applies to corporate non-matching domains or only free-mail: (M) → oracle.
8. **Missing instrument or date** → REQUEST_INFO (H 0014, 0016 no date; instrument not found / ambiguous likewise). Instrument resolution via search_instruments (ticker, former ticker, name, ISIN). (H)
9. **Future date** (position date after `sent`, or maybe ≥ sent) → cannot confirm. Guess REQUEST_INFO. (L) → oracle
10. **Legal hold** on the client profile → ESCALATE (M; H 0017 legal-hold account was masked by ambiguity). → oracle
11. **no_email_confirm** on profile → guess ESCALATE (L). → oracle
12. **Figure** = sum of get_ledger over ALL sub-accounts with date ≤ as_of, each pre-split transaction multiplied by the split ratio when split date ≤ as_of (H 0007, 0010, 0012 sum all subs; H 0019: client quoted the unadjusted 877,081 and desk escalated vs 2,631,243). get_position_summary is a trap (primary sub only, previous-day). (H)
13. Sub-account given as account text → report at account level (ACC id, all sub-accounts) (M; H 0015 single-sub only) → oracle
14. **Figure = 0** → NOT_HELD with as_of. (M) If the client claims a holding and we have none: NOT_HELD vs ESCALATE unknown (L) → oracle
15. **Client figure check**: if the email states a figure and it differs from ours by more than a tolerance → ESCALATE (H 0001, 0003, 0024 ratio 0.85; 0019 split-unadjusted). Within tolerance → CONFIRMED with *our* figure (H 0000 ratio 1.04). The client figure is also accepted if it matches settled+pending (H 0013: client 53,131 vs settled+pending 57,130 = 0.93; U 0078/0112/0183 match settled+pending exactly). Tolerance: U ratios cluster at 1.00/1.02/1.04/1.08/0.93 vs 0.85/1.5/0.33/3; guess 10 % (M) → oracle
16. **Pending**: matched settlement instructions with settle_date > as_of (unmatched/cancelled ignored — H 0010, 0021). pending = sum, pending_date = latest settle date (H 0013: 02-23 & 04-05 → 04-05). Latest vs largest ambiguous (M) → oracle. Reported for CONFIRMED only; None otherwise.
17. **as_of_assumed**: true when the desk had to assume/adjust the date (e.g. weekend roll-back or relative phrase?) — unclear (L) → oracle.
18. Negative computed position → ESCALATE (L, not seen).

## Oracle log (13 of 15 used)
| # | case | response sent | answer | effect |
|---|------|---------------|--------|--------|
| 1 | Q4-0077 | CONFIRMED 284,227 (client 306,965, ratio 1.08) | acceptable | tolerance >= 8 % |
| 2 | Q4-0094 | CONFIRMED 18,642 (client 17,337, ratio 0.93) | acceptable | tolerance >= 7 %; with 0.85 escalations -> 10 % |
| 3 | Q4-0130 | NOT_HELD (client claims 5,570, ledger empty) | acceptable | rule 14: zero -> NOT_HELD even if client claims a figure |
| 4 | Q4-0114 | ESCALATE (legal hold, authorised) | acceptable | rule 10 confirmed |
| 5 | Q4-0054 | ESCALATE (no_email_confirm) | NOT acceptable: "Fine to confirm, but the pending amount and its settlement date need to be in there." | rule 11 revised: no_email_confirm does not block; pending counted vs as_of even if settle date < sent |
| 6 | Q4-0083 | REQUEST_INFO (date after sent) | acceptable | rule 9 confirmed |
| 7 | Q4-0055 | CONFIRMED with account inferred from sole entitlement | NOT acceptable: "They didn't say which account, so we ask." | rule 6: no account -> REQUEST_INFO (free-mail/unregistered sender -> REQUEST_AUTHORIZATION per H 0009) |
| 8 | Q4-0032 | CONFIRMED (entitled, corporate domain not in profile) | NOT acceptable: "sender address isn't one of the client's registered domains" | rule 7c applies to any non-registered domain |
| 9 | Q4-0091 | CONFIRMED 42,113 account total for sub-account SA-913114 | acceptable | rule 13: account-level total |
| 10 | Q4-0112 | CONFIRMED pending 39,038, pending_date 2026-04-30 (latest; largest is 03-09) | acceptable | rule 16: latest date |
| 11 | Q4-0012 | CONFIRMED month-end -> 2026-01-30, as_of_assumed=false | acceptable | rule 17: as_of_assumed false for parsed/rolled dates |
| 12 | Q4-0118 | REQUEST_AUTHORIZATION (level 1 + legal hold) | acceptable | auth check precedes legal hold |
| 13 | Q4-0054 | CONFIRMED 4,913 + pending 47,087 @ 2026-02-01 | acceptable | confirms #5 |

## Final rules (as implemented in procedure.py)
1. Account from mentions: >1 match -> REQUEST_INFO; 0 matches/absent -> REQUEST_AUTHORIZATION if the sender is unknown or writes from a domain not registered to any account they are entitled to, else REQUEST_INFO.
2. Authorization: known contact + sender domain in profile domains + entitlement on the account with level >= 2 and expires >= sent; else REQUEST_AUTHORIZATION.
3. Instrument unresolved/ambiguous, no date, or date >= sent -> REQUEST_INFO.
4. legal_hold -> ESCALATE (account, instrument). no_email_confirm ignored.
5. as_of = requested date rolled back to previous business day; settled = all sub-accounts' ledger <= as_of, split-adjusted.
6. settled == 0 -> NOT_HELD; settled < 0 -> ESCALATE.
7. Client figure present and not within 10 % of settled nor of settled+pending -> ESCALATE.
8. Else CONFIRMED; pending = matched instructions settling after as_of (sum), pending_date = latest; as_of_assumed = false.
