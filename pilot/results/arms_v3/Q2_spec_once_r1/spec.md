# Desk rules — spec (v2, after oracle)

Evidence: history ids (Q2-00xx) and oracle questions (O1..O15, log below). Confidence H/M/L.
Rules are applied in this order; the first that fires decides.

1. **Identify account** from `mentions.account_text` (fallback: an `ACC-`/`SA-` id in the body) via `search_accounts`
   (id, sub-account, name, short name; else name prefix). Missing / 0 hits / >1 hits -> REQUEST_INFO.
   Ev: 0003, 0002, 0005, 0023 (prefix hits 3 accounts -> REQUEST_INFO even though sender is entitled to one). H.
2. **Identify instrument** via `search_instruments` (ticker, old ticker, name, ISIN). Missing/0/>1 -> REQUEST_INFO. H/M.
3. Identification precedes authorization (0002). H.
4. **Authorization** -> REQUEST_AUTHORIZATION unless: sender is a known contact; sender's email domain is in the
   account profile's `domains` (O12, O14, 0014); and the contact has an entitlement on that account with level >= 2
   and `expires` >= sent (0018 level 1, 0009 expired, 0001/0017 level 2 ok). H.
5. **legal_hold** on the profile -> ESCALATE (O13). Order relative to rule 4 unknown; placed after it. H outcome / L order.
6. **no_email_confirm** -> REQUEST_AUTHORIZATION (guess; O14 only shows domain check comes first). L.
7. **Date** parsed from the body (forward headers stripped), relative to `sent`: ISO, M/D/YYYY, "January 8, 2026",
   "Thu 25 Dec 2025", "27-Jan-2026", "close of business ...", "yesterday", "end of last month"/"month-end"/
   "last day of last month". Relative dates count as given (`as_of_assumed=false`, O8). H.
   **No date** -> as of the `sent` date, `as_of_assumed=true` (O5 rejected prev business day; O6/O7 sent date ok). H.
   Future date (after sent) -> REQUEST_INFO (guess). L.
8. **Non-business day** -> previous business day per `get_calendar` (0017; O3 Sun 8 Feb -> 6 Feb accepted). H.
   2026-01-01 is not a listed holiday, used as-is (0022). `get_position_summary` is NOT used (wrong day, primary sub only).
9. **Settled** = sum of ledger rows over ALL sub-accounts with date <= as_of; a row dated before a split whose date is
   <= as_of is multiplied by the ratio (O8 accepted split-adjusted figure). H.
10. **Pending** = sum of `matched` instructions with settle_date > as_of (unmatched/cancelled ignored), excluding any
    instruction with a split dated in (as_of, settle_date] (O9/O10: pending across a split must be omitted, neither raw
    nor multiplied). pending_date = latest settle date among them (single-instruction cases only verified). No
    materiality threshold (O11: 303 vs 800k reported). H (multi-instruction date L).
11. **Client figure** ("We show", "our figure is", "Our records show", "We have N shares", k/mm suffixes) is compared
    with settled + pending; mismatch beyond tolerance -> ESCALATE (O1 0006 and O2 0097: figure == settled only but
    matched pending exists -> escalate; O3 0051 figure == settled+pending -> CONFIRMED). 2% off is a mismatch (O4);
    tolerance set at 1% (only exact matches observed). H rule / L tolerance.
12. settled == 0 and no pending (no ledger or sold out), figure absent or 0 -> NOT_HELD with as_of. M (O15 was wasted
    on a wrong account id; reason did not object to the outcome).
13. Otherwise CONFIRMED with settled, pending/pending_date when rule 10 yields any.
14. Histories that disagree with these rules: none after rule 11 (0006 is explained by pending).

## Oracle log (15/15 used)
| # | case | response sent | verdict / reason | learned |
|---|---|---|---|---|
| O1 | Q2-0006 | CONFIRMED 9509 @2025-12-26, pending 16628 | no: number doesn't match closely enough -> escalation | figure compared with something other than settled |
| O2 | Q2-0097 | CONFIRMED 489250 (fig == settled), pending 13615 (I mistakenly sent wrong acct/instr ids) | no: number doesn't match | same |
| O3 | Q2-0051 | CONFIRMED 24504 @2026-02-06 (Sun->Fri), pending 44309 @2026-04-14 (fig = settled+pending) | yes | compare fig to settled+pending; weekend roll; pending format |
| O4 | Q2-0059 | CONFIRMED 710642 vs fig 724855 (2%) | no: doesn't match closely enough | tolerance < 2% |
| O5 | Q2-0076 | no date: CONFIRMED as_of prev bus. day 2026-02-19, assumed | no: wrong as-of date | |
| O6 | Q2-0076 | as_of = sent 2026-02-20, assumed, pending 601 | no: pending handling isn't right | date ok = sent date |
| O7 | Q2-0140 | no date, as_of sent, pending 38954 | yes | missing date -> sent date, assumed=true |
| O8 | Q2-0198 | "end of last month" -> 2026-03-31, assumed=false, split-adjusted 1404266 | yes | split adjustment, relative date not assumed |
| O9 | Q2-0076 | pending 1803 (601 x split 3) | no: pending handling | |
| O10 | Q2-0076 | pending null | yes | pending crossing a later split is omitted |
| O11 | Q2-0050 | tiny pending 303 reported | yes | no materiality threshold |
| O12 | Q2-0161 | CONFIRMED, sender entitled but corporate domain not registered | no: sender not on registered domain | domain check (REQUEST_AUTHORIZATION) |
| O13 | Q2-0096 | ESCALATE (legal_hold, auth ok) | yes | legal_hold -> ESCALATE |
| O14 | Q2-0095 | ESCALATE (no_email_confirm + outlook.com) | no: sender not on registered domain | domain check precedes no_email_confirm |
| O15 | Q2-0123 | NOT_HELD with wrong account id (my error) | no: wrong account | outcome probably fine |
