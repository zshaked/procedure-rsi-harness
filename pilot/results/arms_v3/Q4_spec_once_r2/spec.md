# Desk procedure spec (phase 1: from histories, unlabeled requests, tools)

Notation: S = settled figure, P = pending, conf = confidence before oracle.

## Parsing
1. **Account resolution.** `search_accounts(account_text)`; sub-account ids (SA-...) resolve to the parent account. 0 hits with a text given, or >1 hits (prefix match on "Calloway Pension Trust", shared short name "SP") -> REQUEST_INFO. Evidence: 0002, 0017, 0022 (all ambiguous -> REQUEST_INFO even when the sender's domain would disambiguate). conf high.
2. **Instrument resolution.** `search_instruments` on ticker / old ticker / name / ISIN. Missing instrument ("positions held in fund X") or 0 / >1 hits -> REQUEST_INFO. Old tickers resolve to the current instrument. conf medium (no labelled example of a missing instrument from an authorised sender; 0008 was gmail -> auth).
3. **Date.** Formats: ISO, M/D/YYYY (US order: 1/31/2026 occurs), DD-Mon-YYYY, "Month D, YYYY", "[Dow] D Month YYYY", "close of business ...", "yesterday" (sent-1), "month-end" / "end of last month" / "the last day of last month" (last calendar day of the month before `sent`). No date -> REQUEST_INFO (0002, 0014, 0016). conf high.
4. **as_of** = requested date rolled back to the previous business day if it is a weekend or holiday (`get_calendar`): Sat 3 Jan -> 01-02 (0006), month-end Jan -> 01-30 (0012), Sun 1 Feb -> 01-30 (0013). conf high.
5. **Client figure**: "our records show N", "our figure is N", "we show N", "we have N shares"; accept 12,500 / 12500 / 12.5k / 1.2mm / negatives.

## Authorization (checked after account ambiguity, before info completeness)
6. Sender's email domain must be one of the account profile's `domains`; otherwise REQUEST_AUTHORIZATION, even with a valid entitlement (0008 gmail, L3). Freemail sender with no account -> REQUEST_AUTHORIZATION (0009). conf high for freemail, medium for a corporate domain of another firm with an entitlement (0032 type).
7. Sender must be a known contact with an entitlement to the account, level >= 2, not expired (expires < sent). Level 1 -> REQUEST_AUTHORIZATION (0011). No entitlement -> REQUEST_AUTHORIZATION (0004, 0005, 0018, 0020). Expired: conf medium (no example).
8. Account with `legal_hold` -> ESCALATE (suspected; no labelled example). conf low-medium.
9. Account with `no_email_confirm` -> cannot confirm by email; suspected REQUEST_AUTHORIZATION or ESCALATE. conf low.
10. Missing account but the sender (domain-matched) has exactly one entitlement: either infer that account or REQUEST_INFO. conf low.

## Figure
11. S = sum of `get_ledger` over **all** sub-accounts with date <= as_of; entries dated before a split date multiply by the ratio when the split date <= as_of (0019: client sent unadjusted 877,081, desk escalated). `get_position_summary` is NOT used (primary sub-account only, day before). Evidence: 0006, 0007, 0010 sum all subs. conf high.
12. Sub-account requests report the whole parent account (client figures in 0035, 0091, 0115 equal the account total, not the sub-account). conf medium-high.
13. P = sum of **matched** instructions with settle_date > as_of; pending_date = latest such settle_date; reported only when P > 0 (0013, 0021; unmatched ignored in 0010). Raw qty (not split-adjusted, 0021). conf medium-high.
14. S == 0 (no position) -> NOT_HELD with as_of. conf medium. If the client claims a non-zero holding while we hold 0: ESCALATE or NOT_HELD? conf low.
15. Requested date after `sent` (future) or = sent: unsure (REQUEST_INFO vs confirm latest with as_of_assumed). conf low.
16. as_of_assumed: false for explicit dates; for "month-end" style relative dates unsure. conf low.

## Reconciliation
17. If the client gave a figure and it differs materially from S -> ESCALATE (0001, 0003, 0024 at -15%; 0019 split). Small differences are confirmed with our figure (0000 at +4%). Tolerance unknown between 4% and 15%; 0013 (client 53,131 vs S 18,980, S+P 57,130) was confirmed — possibly an operator mistake, or the client figure is compared with S+P. A client figure equal to S+P (0078, 0183) is suspected acceptable. conf medium.
18. Otherwise CONFIRMED with account, instrument, as_of, S, and P/pending_date when P > 0.

## Order of checks
parse -> account ambiguous/unresolved (REQUEST_INFO) -> sender authorisation (REQUEST_AUTHORIZATION) -> legal hold / no-email (ESCALATE?) -> missing instrument/date (REQUEST_INFO) -> compute -> NOT_HELD / ESCALATE on mismatch / CONFIRMED.
Note 0017 (ambiguous SP, sender level 1) went to REQUEST_INFO, so ambiguity precedes auth; 0009 (no account, gmail) went to auth, so a missing account from an unrecognised domain is an auth case.

# Phase 2: oracle questions (15/15 used)

| # | case | response asked | answer | effect |
|---|------|----------------|--------|--------|
| 1 | 0077 | CONFIRMED, S=284,227 vs client 306,965 (+8%) | acceptable | tolerance >= 8% (rule 17) |
| 2 | 0114 | ESCALATE (legal_hold, L2) | acceptable | rule 8 confirmed |
| 3 | 0054 | CONFIRMED with P=47,087 (no_email_confirm account) | acceptable | rule 9: flag ignored |
| 4 | 0032 | CONFIRMED (corporate domain of another firm, L3 entitlement) | NOT acceptable: "sender address isn't one of the client's registered domains" | rule 6 confirmed for any domain |
| 5 | 0183 | CONFIRMED, client figure = S+P | acceptable | rule 17: compare client to S or S+P |
| 6 | 0083 | CONFIRMED latest figure, as_of_assumed=true (future date) | NOT acceptable: "asked about a date that hasn't happened yet" | rule 15 |
| 7 | 0106 | CONFIRMED month-end, as_of_assumed=false | acceptable | rule 16 |
| 8 | 0157 | NOT_HELD although client claims 6,619 | acceptable | rule 14: zero -> NOT_HELD regardless of claim |
| 9 | 0083 | REQUEST_INFO (future date) | acceptable | rule 15 -> REQUEST_INFO |
| 10 | 0131 | CONFIRMED with account inferred from single entitlement | NOT acceptable: "didn't say which account, so we ask" | rule 10 -> REQUEST_INFO |
| 11 | 0123 | CONFIRMED, Sunday rolled to Friday, as_of_assumed=false | acceptable | rules 4, 16 |
| 12 | 0054 | ESCALATE (no_email_confirm) | NOT acceptable: "fine to confirm, but pending amount and date needed" | rule 9 flag ignored; rule 13 |
| 13 | 0118 | ESCALATE (legal hold, level 1) | NOT acceptable: "entitlement isn't high enough" | auth precedes legal hold |
| 14 | 0119 | CONFIRMED, "yesterday"=Sunday rolled to Fri, as_of_assumed=false, P=581 | acceptable | rules 3, 4, 13, 16 |
| 15 | 0168 | REQUEST_AUTHORIZATION (expired entitlement) | acceptable | rule 7 |

# Final rules (after oracle)
1. Account text missing -> REQUEST_AUTHORIZATION if the sender's domain is not registered to any client account (0009), else REQUEST_INFO (oracle 10). Unresolvable / ambiguous account -> REQUEST_INFO (0002, 0017, 0022). Sub-account -> parent account. [high]
2. Sender domain must be in the account's registered domains, else REQUEST_AUTHORIZATION (0008, oracle 4). [high]
3. Sender must be a known contact entitled to the account at level >= 2 and not expired (expires >= sent), else REQUEST_AUTHORIZATION (0011, oracle 13, 15). [high]
4. legal_hold -> ESCALATE (after auth) (oracle 2, 13). no_email_confirm is ignored (oracle 3, 12). [medium-high]
5. Missing / unresolvable / ambiguous instrument -> REQUEST_INFO. Missing date -> REQUEST_INFO. Requested date after `sent` -> REQUEST_INFO (oracle 9). [high / medium for instrument]
6. as_of = requested date rolled back to previous business day; as_of_assumed = false (oracle 7, 11, 14). [medium: no case seen where it is true]
7. S = all sub-accounts, ledger date <= as_of, split-adjusted for splits with date <= as_of applied to entries dated before the split. [high]
8. P = sum of matched instructions settling after as_of, pending_date = latest; included when P != 0. [high]
9. S == 0 -> NOT_HELD (with account, instrument, as_of), even if the client claims a holding (oracle 8). [medium-high]
10. Client figure given and not within 10% of S nor of S+P -> ESCALATE (0001/0003/0024 at 15%, 0019 split). [medium: threshold between 8% and 15%]
11. Else CONFIRMED.
Order: account presence/ambiguity -> domain -> entitlement -> legal hold -> instrument/date -> compute.
Note: 0017 (ambiguous SP) precedes auth; 0008 (gmail, no instrument) is auth before missing-instrument info, consistent with the order.
