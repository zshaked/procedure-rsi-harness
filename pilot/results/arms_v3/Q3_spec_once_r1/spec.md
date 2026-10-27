# Desk rules — spec (Phase 1 draft, revised after oracle in Phase 2)

Evidence ids are history cases (H) or unlabeled analysis (U). Confidence: H/M/L.

1. **Account resolution.** Resolve `mentions.account_text` with `search_accounts` (id, sub-account id, name, short name; then name prefix). Exactly one hit -> that account. A sub-account id (SA-...) resolves to its parent account. Evidence: H 0001 (short name), 0011/0013/0018 (id, name). Conf H.
2. **Ambiguous account -> REQUEST_INFO.** Multiple hits (prefix of a family "X I/II/III", duplicate short names) -> REQUEST_INFO, even when the sender is entitled to only one of them. Evidence: H 0000, 0006, 0007, 0017, 0021. Conf H.
3. **No account mentioned.** Infer the account from the sender's entitlements if they name exactly one account; otherwise REQUEST_INFO. Evidence: H 0024 (inferred ACC-10254, which is no_email_confirm -> REQUEST_AUTHORIZATION); U 0127 client figure equals the inferred account's holding; oracle Q14 accepted. Conf H (single), L (multi -> INFO).
4. **Unknown account (no hit) -> REQUEST_INFO.** Conf M (not seen).
5. **Authorization.** Sender must be a known contact with a non-expired (expires >= sent date) entitlement on the resolved account at level 3. Otherwise REQUEST_AUTHORIZATION (no account/instrument fields). Level 1/2 -> AUTH (H 0002, 0009, 0010, 0003, 0015); entitlement only on another account -> AUTH (H 0005, 0014, 0016). H 0022 (other account -> REQUEST_INFO) treated as operator error. Unknown contact -> AUTH. Conf H (level), M (expiry).
6. **Sender e-mail domain is not checked** (H 0023; oracle Q7). Conf H.
7. **no_email_confirm profile -> REQUEST_AUTHORIZATION** (H 0024). Oracle Q8 confirmed. Order: after the instrument check (H 0004: NEC + no instrument -> REQUEST_INFO). Conf H (rule), M (order).
8. **legal_hold profile -> ESCALATE** (after the entitlement check: H 0003, oracle Q9 'entitlement isn't high enough' for L2+LH). Conf M (ESCALATE itself never directly confirmed).
9. **Instrument.** Resolve `instrument_text` with `search_instruments` (ticker, old ticker, name, ISIN). None given / no hit / several hits -> REQUEST_INFO. Evidence H 0004, 0019 (no instrument -> INFO). Conf H.
10. **Date.** Parse body (ISO, M/D/YYYY US, D-Mon-YYYY, Month D, YYYY, Wkd D Mon YYYY, "close of business D Month YYYY", yesterday = sent-1, end of last month / last day of last month / month-end = last day of previous month). Ignore forwarded-header "Date:" lines. No date -> use sent date, as_of_assumed = true (H 0023). Conf H.
11. **Non-business-day as_of** (weekend or market holiday per get_calendar) -> REQUEST_INFO, also when it comes from a relative phrase ('end of last month' on a Saturday). Oracle Q1, Q2 ('That date isn't a business day; we ask them which date they want'). Conf H. Explains H 0022 too.
12. **Future date** (after sent) -> REQUEST_INFO. Oracle Q10. Conf H. Date before ledger history (< 2025-12-15) -> ESCALATE (guess, conf L).
13. **Figure** = sum of ledger qty over *all* sub-accounts with date <= as_of, each pre-split transaction multiplied by split ratio when split date <= as_of. `get_position_summary` is NOT used (primary sub only, previous day). Evidence H 0001, 0018, 0020 (multi-sub sums), 0011. Splits: oracle Q13 (split-adjusted 2.79m escalated). Conf H.
14. **Zero (or no ledger) -> NOT_HELD** with account, instrument, as_of — even if the client states a figure (oracle Q15). Conf H.
14b. **Large position: settled >= 1,000,000 -> ESCALATE** (oracle Q12: 'Positions that size always go to escalation'; Q13). Threshold between 855,399 (H 0011 confirmed) and 1,056,400; 1,000,000 assumed. Conf H (rule), M (exact threshold).
15. **Client-stated figure** (we have / our figure is / records show / we show; k, mm suffixes): if differs from our figure by more than 2% -> ESCALATE (H 0012, 7% off). Within 2% (inclusive) -> CONFIRMED with OUR figure (oracle Q11, 2.0% off accepted). 4% untested; generator's exact-1.02 boundary suggests 2% inclusive. Conf M.
16. **Pending** (CONFIRMED only). Sum of *matched* instructions with as_of < settle_date <= as_of + 90 days; pending_date = latest such settle date. Evidence: H 0008 (36 d after as_of, reported); oracle Q3 (65 d, accepted), Q5 (17 d after as_of but before the email date, accepted), Q4 (107 d, 'pending handling isn't right'), H 0020 (129 d, not reported); unmatched excluded (oracle Q6). Window edge somewhere in 66-106 d (90 assumed); a sent-date-based window (<= sent+30) fits the same data. Conf M.

Order: account (1-4) -> authorization (5) -> instrument (9) -> no_email_confirm (7) -> legal hold (8) -> date (10-12) -> figure: zero -> NOT_HELD; negative -> ESCALATE (guess); >= 1m -> ESCALATE; client figure off > 2% -> ESCALATE; else CONFIRMED (+pending).

## Oracle log (15/15 used)
| # | case | response asked | verdict / reason | rule |
|---|---|---|---|---|
| 1 | Q3-0041 | CONFIRMED as_of 2026-01-30 (Sat 31 Jan rolled back) | no: "That date isn't a business day; we ask them which date they want." | 11 |
| 2 | Q3-0059 | CONFIRMED as_of 2026-01-30 ('end of last month'=Sat) + pending 664 | no: same reason | 11 |
| 3 | Q3-0123 | CONFIRMED + pending 13,615 settling 65 d after as_of | yes | 16 |
| 4 | Q3-0018 | CONFIRMED + pending 684 settling 107 d after as_of | no: "pending amount handling isn't right" | 16 |
| 5 | Q3-0193 | CONFIRMED + pending 4,632 settling after as_of but before email date | yes | 16 |
| 6 | Q3-0181 | CONFIRMED, unmatched instruction not reported | yes | 16 |
| 7 | Q3-0025 | CONFIRMED for gmail sender with L3 entitlement | yes | 6 |
| 8 | Q3-0084 | REQUEST_AUTHORIZATION (no_email_confirm, L3) | yes | 7 |
| 9 | Q3-0163 | ESCALATE (legal hold, L2) | no: "entitlement isn't high enough" | 5, 8 order |
| 10 | Q3-0051 | REQUEST_INFO (date after sent) | yes | 12 |
| 11 | Q3-0132 | CONFIRMED with client figure 2.0% higher | yes | 15 |
| 12 | Q3-0175 | CONFIRMED 1,056,400 (client +4%) + pending 86 d | no: "Positions that size always go to escalation before we confirm." | 14b |
| 13 | Q3-0145 | ESCALATE (split-adjusted 2,794,890; unadjusted 871,824) | yes | 13, 14b |
| 14 | Q3-0137 | ESCALATE, account inferred from sole entitlement, client off 15% | yes | 3, 15 |
| 15 | Q3-0080 | NOT_HELD although client states 1,447 | yes | 14 |
