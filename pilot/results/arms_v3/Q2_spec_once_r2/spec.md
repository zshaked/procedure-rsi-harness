# Desk procedure spec (updated after oracle, Phase 2)

Evidence references are history case ids (Q2-00xx). Confidence: H/M/L.

1. **Resolve account** with `search_accounts(mentions.account_text)` (matches id, sub-account id, name, short name, else name prefix). No mention or 0 hits -> REQUEST_INFO. More than one hit (e.g. "Falcon Capital" -> I/II/III, colliding short names) -> REQUEST_INFO, even if the sender is entitled to exactly one of them. Evidence: 0002, 0003, 0005, 0023 (0002/0023: sender entitled to one candidate, still REQUEST_INFO). Conf H.
2. **Resolve instrument** with `search_instruments(mentions.instrument_text)` (ticker, former ticker, name, ISIN). No mention / 0 hits / >1 hits -> REQUEST_INFO. Former tickers are accepted (0004 KRXN; 0002 EIFM was info for account reasons). Conf M-H.
3. REQUEST_INFO checks come before authorization checks (0023: ambiguous + level-1 sender -> REQUEST_INFO). Conf M.
4. **Authorization** (sender = `from`): need a contact (`get_contact`), an entitlement on the resolved account with level >= 2 that is not expired (expires >= sent). Otherwise REQUEST_AUTHORIZATION. Evidence: 0000/0007/0019/0024 (entitled to other account), 0009 (expired, level 1), 0018 (level 1 valid), 0001/0017 (level 2 confirmed). Conf H for level 1 / wrong account; M for expiry alone.
5. **Sender domain** must be one of the account profile's `domains`; else REQUEST_AUTHORIZATION. Evidence: 0014 (proton.me, entitled level 3). Conf H for free-mail; L for corporate domain not in profile (unseen; competing hypothesis: only free-mail fails).
6. Authorization is checked before holdings (0007/0014/0019: zero holdings but REQUEST_AUTHORIZATION). Conf H.
7. **Legal hold** on profile -> ESCALATE (unseen). Conf L. Alternative: REQUEST_AUTHORIZATION.
8. **no_email_confirm** on profile -> REQUEST_AUTHORIZATION (cannot confirm by email) (unseen). Conf L. Alternative: ESCALATE.
9. **Date**: parse from body (ISO, M/D/YYYY US order, D-Mon-YYYY, "Month D, YYYY", "[Dow] D Month YYYY", "close of business ...", "yesterday" = sent-1, "end of last month"/"month-end"/"last day of last month" = last calendar day of the previous month). Ignore forwarded-header "Date:" lines. Conf H.
10. If the date is not a business day (`get_calendar`), use previous business day; as_of is the date actually used (0017: 31 Jan Sat -> 2026-01-30). as_of_assumed False. Conf H.
11. **No date** given -> do not ask; assume a date, as_of_assumed True (0012 was escalated on a discrepancy, not REQUEST_INFO). Which date: previous business day before `sent` (L) vs `sent` itself.
12. **Settled figure** = sum of `get_ledger` qty over ALL sub-accounts with date <= as_of (inclusive), each pre-split row multiplied by split ratio if the split date is after the row date and on/before as_of. Not `get_position_summary` (primary sub-account only, previous day). Evidence: 0004 (582,180 = both subs), 0020, 0021, 0022 (split after as_of ignored), 0008 (inclusive). Conf H for all-subs; M for split handling. Sub-account mention: still whole account (L).
13. **Client figure** in the email ("our figure is", "We show", "records show", "We have N shares"), quantities "12,500", "12.5k", "1.2mm". If present and != settled -> ESCALATE. Evidence: 0008, 0011, 0012, 0013, 0015, 0016, 0020; 0004 (match -> CONFIRMED). Conf H. Exact equality (no tolerance) M.
14. settled == 0 (and no contradicting client figure) -> NOT_HELD with as_of. If client figure > 0 and settled 0 -> ESCALATE (L).
15. settled > 0 -> CONFIRMED with settled, as_of.
16. **Pending**: matched settlement instructions (`get_instructions`, status matched) with settle_date after as_of are reported: pending = qty (sum if several), pending_date = settle_date (earliest? L). Unmatched/cancelled ignored. Evidence: 0021. Conf M.
17. Future date (after sent) -> REQUEST_INFO (unseen). L.
18. Q2-0006 (ESCALATE with matching figure, Sunday date, matched pending) suspected operator mistake. L.

## Phase 2: oracle questions (15/15 used)

| # | Case | Response asked | Answer | Consequence |
|---|------|----------------|--------|-------------|
| 1 | Q2-0006 | CONFIRMED 9,509 @2025-12-26, pending 16,628 | NO: "Their number doesn't match ours closely enough; escalation" | client 9,509 == settled, so desk figure is not settled alone |
| 2 | Q2-0097 | CONFIRMED 489,250 (= client) + pending 13,615 | NO: same reason | desk compares client figure with settled + matched pending |
| 3 | Q2-0051 | CONFIRMED 24,504 + pending 44,309 (client 68,813 = sum) | YES | rule 13 revised: compare with settled + pending |
| 4 | Q2-0059 | CONFIRMED, client 2% off | NO: not close enough | tolerance < 2% |
| 5 | Q2-0125 | CONFIRMED, corporate domain not in profile, entitled L3 | NO: "sender address isn't one of the client's registered domains" | rule 5 confirmed (profile domains, H) |
| 6 | Q2-0096 | ESCALATE (legal hold, authorised sender) | YES | rule 7 confirmed |
| 7 | Q2-0142 | ESCALATE (legal hold, level-1 sender) | NO: "entitlement isn't high enough" | authorization checked before legal hold |
| 8 | Q2-0095 | ESCALATE (no_email_confirm, outlook.com sender) | NO: domain reason | domain check precedes no_email_confirm; no_email outcome still unknown |
| 9 | Q2-0076 | no date -> as_of prev business day before sent | NO: "Wrong as-of date" | |
| 10 | Q2-0076 | no date -> as_of = sent, assumed, pending 601 | NO: "pending amount handling isn't right" (date accepted) | rule 11: as_of = sent date (rolled back if non-business), assumed True |
| 11 | Q2-0050 | CONFIRMED with pending 303 (no split, explicit date) | NO: pending handling | small matched instructions are not reported |
| 12 | Q2-0157 | NOT_HELD (settled 0, client claims 15,569; "yesterday") | YES | zero holding -> NOT_HELD even with client figure; yesterday = sent-1, assumed False |
| 13 | Q2-0191 | CONFIRMED whole-account total for a sub-account mention | YES | sub-account mention -> whole account (H) |
| 14 | Q2-0128 | ESCALATE (client 339,563 = pre-split figure; split-adjusted 1,018,689) | NO: "Fine to confirm with the settled position" | client figure equal to the unadjusted (pre-split) figure counts as a match |
| 15 | Q2-0190 | CONFIRMED with pending 348 (1.2% of settled) omitted | YES | materiality is absolute (~1,000), not 1% relative |

## Final rules (as implemented)

1. Account: search_accounts(mention) after light cleanup (also ACC-/SA- ids found in the body if no mention). 0 or >1 hits -> REQUEST_INFO. H
2. Instrument: search_instruments(mention) (ticker/old ticker/name/ISIN). 0 or >1 -> REQUEST_INFO. H
3. Date: explicit/relative date parsed from body; non-business day -> previous business day; as_of_assumed False. No date -> sent date (rolled back if non-business), as_of_assumed True. H. Date after sent -> REQUEST_INFO (L, unseen).
4. Authorization: known contact, sender domain in profile domains, unexpired entitlement level >= 2 on that account; else REQUEST_AUTHORIZATION. H
5. no_email_confirm -> REQUEST_AUTHORIZATION. L (never testable cleanly).
6. legal_hold -> ESCALATE (after authorization). H
7. Settled = sum over all sub-accounts of ledger rows dated <= as_of, split-adjusted for splits dated after the row and on/before as_of. H
8. Pending = matched instructions with settle_date > as_of and qty >= 1,000 (sum; pending_date = latest such date). Smaller ones ignored. M (threshold exact value L).
9. Settled <= 0 -> NOT_HELD (regardless of client figure). H
10. Client figure present: compare with settled + pending (also accept the split-unadjusted equivalent); mismatch beyond 0.5% -> ESCALATE. H for direction, L for exact tolerance.
11. Else CONFIRMED with settled, pending/pending_date when material pending exists.
