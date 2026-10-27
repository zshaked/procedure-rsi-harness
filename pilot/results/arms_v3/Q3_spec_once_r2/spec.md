# Desk rules — spec (Phase 1 draft, from histories + unlabeled + tools)

Notation: H = history case. Confidence: H(igh)/M(edium)/L(ow).

1. **Account resolution.** Resolve `mentions.account_text` with `search_accounts` (id, sub-account id, name, short name; prefix fallback). Exactly one hit -> that account. 0 or >1 hits -> REQUEST_INFO. Ambiguity is NOT resolved via the sender's entitlements (H-0000, H-0006 sender entitled to one of the candidates, still REQUEST_INFO). Evidence: 0000, 0006, 0007, 0017, 0021. Conf H.
2. **No account named** ("our fund"). Unclear: H-0024 got REQUEST_AUTHORIZATION; sender's only entitlement is ACC-10254 which is `no_email_confirm`. Either the desk infers the account from the sender's sole entitlement, or missing account -> REQUEST_INFO and 0024 is noise. Conf L. (oracle)
3. **Authorization.** Sender must be a known contact with a non-expired entitlement on the resolved account at level >= 3; else REQUEST_AUTHORIZATION. Evidence: level 2 -> AUTH (0002, 0009), level 1 -> AUTH (0003, 0010, 0015), entitlement on other account -> AUTH (0005, 0014, 0016). Level 3 -> proceeds (0001, 0008, 0011...). Expired -> AUTH assumed (tool docstring stresses expired are included). Conf H (expired: M).
4. **Sender domain.** H-0023: yahoo sender with level-3 entitlement got an answer (NOT_HELD). Hypothesis: domain is not checked when entitlement is valid. Competing: free/foreign domain -> REQUEST_AUTHORIZATION and 0023 is a mistake. Conf L. (oracle)
5. **Profile flags.** `legal_hold` -> ESCALATE (suspected; no clean history). `no_email_confirm` -> REQUEST_AUTHORIZATION? (0024 weak support; 0004 had flag but missing instrument -> REQUEST_INFO). Conf L. (oracle)
6. **Order of checks.** account resolution -> authorization -> profile flags -> instrument -> date -> figures. H-0015 (level 1, no instrument) -> AUTH supports auth before instrument check; H-0004/0019 (level 3, no instrument) -> REQUEST_INFO. H-0022 (not entitled, "last day of last month") -> REQUEST_INFO looks like an operator mistake. Conf M.
7. **Instrument.** Resolve with `search_instruments` (ticker, old ticker, name, ISIN). None given / not found / >1 -> REQUEST_INFO. Conf H.
8. **As-of date.** Parse free text relative to `sent`: ISO, M/D/YYYY (US), D-Mon-YYYY, "Month D, YYYY", "[Dow] D Mon YYYY", "close of business D Month YYYY", "yesterday" (= sent-1 day), "end of last month"/"last day of last month"/"month-end" (= last calendar day of previous month; H-0008 -> 2025-12-31). No date -> sent date, as_of_assumed = true (H-0023). Conf H for parsing; weekend/holiday handling unknown (keep requested date vs roll back to previous business day) Conf L; future date (after sent) -> REQUEST_INFO? Conf L.
9. **Settled figure.** Sum of `get_ledger` across ALL sub-accounts with date <= as_of (inclusive), split-adjusted: a transaction dated before a split whose date <= as_of is multiplied by the ratio. NOT `get_position_summary` (primary sub-account only, previous day). Evidence: 0001 (551,371 = two sub-accounts, incl. as_of), 0018, 0020. Split adjustment Conf M (from docstring). If account_text is a sub-account id: still whole-account figure? Conf L.
10. **NOT_HELD** when settled == 0 (0023). Negative settled -> ESCALATE (suspected). Conf M.
11. **Client figure check.** If the email states the client's figure ("our figure is", "we have N shares", "we show", "our records show") and it differs from settled -> ESCALATE (0012, -7%). Equal -> CONFIRMED. Tolerance unknown (unlabeled diffs cluster at 2%,4%,7%,8%,15%,50%); some client figures equal settled + pending. Conf M (tolerance L).
12. **Pending.** Report matched (not unmatched/cancelled) instructions with settle_date > as_of as pending (sum) with pending_date = settle date. H-0008 reported one (settle 5 bdays after sent); H-0018/0020 did not report far-future ones (settle months later). Window unknown. Conf L.
13. CONFIRMED otherwise, with account_id, instrument_id, as_of, as_of_assumed, settled.


## Phase 2 — oracle log (15/15 used)

| # | case | response asked | verdict / reason | what it settles |
|---|------|----------------|------------------|-----------------|
| 1 | Q3-0025 | CONFIRMED 803,432 (gmail sender, level-3 entitlement) | OK "Looks right." | sender domain is NOT checked (rule 4) |
| 2 | Q3-0084 | CONFIRMED (account no_email_confirm) | NO "doesn't take confirmations by email; it has to go through authorization" | no_email_confirm -> REQUEST_AUTHORIZATION |
| 3 | Q3-0163 | ESCALATE (legal hold, level-2 sender) | NO "entitlement isn't high enough" | entitlement check precedes legal hold |
| 4 | Q3-0127 | CONFIRMED ACC-10180 inferred, as_of Sat 2026-02-28 | NO "date isn't a business day; we ask them which date they want" | non-business as_of -> REQUEST_INFO; account inference not objected to |
| 5 | Q3-0022 (history) | REQUEST_AUTHORIZATION | OK | operator's REQUEST_INFO was a mistake; authorization precedes date check |
| 6 | Q3-0062 | REQUEST_INFO (no account named) | NO "number doesn't match ours closely enough; escalation" | missing account is inferred from the sender's entitlement; 8% gap -> ESCALATE |
| 7 | Q3-0107 | CONFIRMED as_of rolled back to Fri 2026-02-27 ("last day of last month") | NO "date isn't a business day; we ask" | relative dates are not rolled back; weekend -> REQUEST_INFO |
| 8 | Q3-0132 | CONFIRMED, client figure +2% | OK | 2% difference is within tolerance |
| 9 | Q3-0175 | CONFIRMED 1,056,400, client figure +4% | NO "Positions that size always go to escalation" | NEW rule: large positions (>= ~1,000,000; 855,399 and 803,432 confirmed) -> ESCALATE |
| 10 | Q3-0018 (history) | CONFIRMED + pending 684 @ 2026-04-25 | OK | reporting matched pending settling after as_of is acceptable (no window) |
| 11 | Q3-0148 | CONFIRMED 721,200 (as_of 03-04, split 3:1 on 03-05) | OK | split is applied only when split date <= as_of |
| 12 | Q3-0085 | ESCALATE (legal hold, Sat date) | NO "date isn't a business day" | date check precedes legal hold |
| 13 | Q3-0080 | NOT_HELD (zero holding, client claims 1,447) | OK | zero -> NOT_HELD even if client claims a figure |
| 14 | Q3-0051 | REQUEST_INFO (as_of after sent) | OK | future date -> REQUEST_INFO |
| 15 | Q3-0111 | REQUEST_AUTHORIZATION (no_email_confirm + holiday date) | OK | no_email_confirm precedes the date check |

## Final rules (Phase 2 result), in order of application

1. Account: resolve account_text (also an ACC-/SA- id found in the body if the extractor missed it). 0 or >1 hits -> REQUEST_INFO. If no account is named, infer it from the sender's entitlements when they cover exactly one account; otherwise REQUEST_INFO. (H; inference M — Q4, Q6, H-0024)
2. Authorization: sender must be a known contact with a non-expired, level >= 3 entitlement on the account; else REQUEST_AUTHORIZATION. Domain irrelevant. (H — Q1, Q3, Q5)
3. Instrument: none / not found / ambiguous -> REQUEST_INFO. (H; position vs rule 4 from H-0004 only — M)
4. Client profile no_email_confirm -> REQUEST_AUTHORIZATION. (H — Q2, Q15, H-0024)
5. Date: parse; unparseable date text -> REQUEST_INFO; date after `sent` -> REQUEST_INFO; non-business day (weekend/holiday, incl. relative dates such as month-end/yesterday) -> REQUEST_INFO. No date -> sent date (previous business day if sent on a non-business day), as_of_assumed=true. (H — Q4, Q7, Q12, Q14)
6. legal_hold -> ESCALATE. (M — never directly confirmed; only shown to come after auth and date)
7. Settled = all sub-accounts, ledger date <= as_of, split-adjusted only for splits dated <= as_of. Sub-account named -> still whole account (L, untested). (H)
8. settled == 0 -> NOT_HELD (regardless of client's figure). (H — Q13, H-0023)
9. settled < 0 -> ESCALATE (L). settled >= 1,000,000 -> ESCALATE (H that ~1.06m escalates; exact threshold M).
10. Client figure given and |fig - settled| > 5% of settled (and not within 5% of settled+pending) -> ESCALATE. (2% OK, 7%/8% escalate; cutoff between 2% and 7% — 5% chosen, M)
11. CONFIRMED with settled; pending = sum of matched instructions with settle_date > as_of, pending_date = latest such settle date (H for single instruction; aggregation L).
