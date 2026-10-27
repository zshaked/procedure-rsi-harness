# Desk procedure spec (Phase 1 draft, from histories + unlabeled + tools)

Order of evaluation: identify -> authorize -> date -> compute -> compare.

1. **Account identification.** Resolve `mentions.account_text` with `search_accounts` (matches id, sub-account id, name, short name; else name prefix). Missing text, 0 hits, or >1 hits -> REQUEST_INFO. No disambiguation by sender domain/entitlement.
   Evidence: 0003 (no account) RI; 0002, 0005, 0023 (3 prefix hits) RI even though sender entitled to only one (0005, 0023). Confidence: high.
2. **Instrument identification.** `search_instruments` (ticker, old ticker, name, ISIN). Missing, 0 or >1 hits -> REQUEST_INFO (e.g. "confirm the positions held" with no security). Old tickers resolve (0002 EIFM->SAJ, 0020 HXFZ). Confidence: high for resolution, medium for "no instrument -> RI" (not in histories).
3. **Sub-account mention** resolves to the parent account; figure is the whole account (all sub-accounts). Evidence: 0015; unlabeled 0171/0177 client figures are noise multiples of the whole-account total. Confidence: medium-high.
4. **Authorization.** Sender must be a known contact (`get_contact`) with an entitlement on the resolved account with level >= 2 and `expires` >= sent date, AND the sender's email domain must be in the account profile's `domains`. Otherwise REQUEST_AUTHORIZATION.
   Evidence: 0000/0007/0019/0024 no entitlement; 0018 level 1; 0009 level 1 + expired; 0014 proton.me with level 3 -> RA; 0001/0017 level 2 confirmed. Confidence: high for entitlement/level; medium for domain rule (only one free-mail case; corporate-domain mismatches untested); medium for expiry alone.
5. **Profile flags.** `legal_hold` -> ESCALATE (suspected). `no_email_confirm` -> REQUEST_AUTHORIZATION or ESCALATE (unknown). Not in histories. Confidence: low.
6. **Date.** Parse body date (ISO, M/D/YYYY, D-Mon-YYYY, "Mon D, YYYY", "D Month YYYY", weekday prefixes, "close of business"); relative: "yesterday" = sent-1, "end of last month"/"last day of last month"/"month-end" = last calendar day of previous month. If the date is not a business day, report as of the previous business day (`get_calendar`). Evidence: 0017 (Sat 31 Jan -> 2026-01-30). Confidence: high.
7. **Missing date** -> assume a date (as_of_assumed = true) rather than ask; candidate: previous business day before sent (latest closed day) vs sent date. Evidence: 0012 no date + mismatch -> ESCALATE (not RI). Confidence: medium on rule, low on which date.
8. **Future date** (>= sent) -> REQUEST_INFO (suspected; only appears with unresolved accounts). Confidence: low.
9. **Settled figure** = sum of `get_ledger` across all sub-accounts with date <= as_of, each transaction multiplied by split ratio when txn date < split date <= as_of. Do not use `get_position_summary` (primary sub-account only, previous day). Evidence: 0004 (582,180 = both sub-accounts), 0021, 0022. Confidence: high (split adjustment: medium, untested).
10. **Zero / no position** -> NOT_HELD with as_of. Confidence: medium. With a client figure > 0: ESCALATE vs NOT_HELD unknown.
11. **Client figure comparison.** If the email states a figure (formats 12,500 / 12500 / 12.5k / 1.2mm) and it differs from the settled figure -> ESCALATE. Equal -> CONFIRMED. Evidence: 0008, 0011, 0013, 0015, 0016, 0020 mismatches escalate; 0004 match confirmed. Open: client figure = settled + pending (unl. 0051) or = pre-split figure (unl. 0128). Confidence: high (exact match).
12. **Pending.** Report pending (sum of `matched` instructions with settle_date > as_of) and pending_date on CONFIRMED; unmatched/cancelled excluded. Evidence: 0021 (one matched instr). Confidence: medium; multi-instruction aggregation unknown.
13. **0006** (match, level 2, Sunday date, large matched pending) was escalated; suspected operator mistake. Confidence: low.
14. **as_of_assumed** true only when no date was given. Confidence: medium-low.

## Oracle log (15/15 used)
| # | case | response sent | verdict / reason | effect |
|---|------|---------------|------------------|--------|
| 1 | 0055 (no date, lvl3) | CONFIRMED as_of 2026-02-13 (prev biz day before sent), assumed=true | acceptable | rule 7 confirmed |
| 2 | 0006 | CONFIRMED 9509 as_of 2025-12-26 + pending 16628 | NOT ok: "their number doesn't match ours closely enough; escalation" | 0006 not a mistake; desk figure != settled |
| 3 | 0097 (client = settled, matched pending exists) | CONFIRMED settled + pending (instrument_id typo in my response) | NOT ok: number doesn't match -> escalation | client figure compared to settled+pending |
| 4 | 0051 (client = settled + matched pending) | CONFIRMED settled 24504, pending 44309 @04-14, as_of 02-06 (Sun->Fri) | acceptable | rule 11 revised |
| 5 | 0135 (only unmatched instr) | CONFIRMED, no pending | acceptable | unmatched excluded |
| 6 | 0089 (two matched) | pending = sum 56948, pending_date = latest 06-15 | acceptable | aggregation |
| 7 | 0025 (matched settles between as_of and sent) | pending 14453 @01-16 | acceptable | pending = matched & settle_date > as_of |
| 8 | 0125 (corporate domain of another client, entitled lvl3; holiday date) | CONFIRMED as_of 01-16 | acceptable | corporate domain mismatch OK; holiday roll-back |
| 9 | 0193 (outlook.com, entitled lvl3) | CONFIRMED | NOT ok: "sender address isn't one of the client's registered domains" | free-mail -> RA |
| 10 | 0096 (legal_hold, lvl2, no date) | ESCALATE | acceptable | legal hold -> ESCALATE |
| 11 | 0095 (no_email_confirm + outlook) | ESCALATE | NOT ok: domain reason | auth check precedes |
| 12 | 0105 (no_email_confirm, valid sender, no instrument) | REQUEST_INFO | NOT ok: "doesn't take confirmations by email; has to go through authorization" | no_email -> RA, before instrument check |
| 13 | 0157 (zero holding, client claims 15,569) | NOT_HELD | acceptable | zero -> NOT_HELD even with figure |
| 14 | 0198 (split before as_of, end of last month) | CONFIRMED 1,404,266 as_of 03-31, assumed=false | acceptable | split adjustment; relative date not 'assumed' |
| 15 | 0128 (client figure = pre-split total) | ESCALATE | NOT ok: "Fine to confirm with the settled position" | pre-split figure counts as a match |

## Revised rules (post-oracle) — supersede the above where they differ
- R4': Domain rule: sender domain must be one of the account's registered domains, OR a registered domain of another client account the contact holds an entitlement on (the sender is a known corporate user, e.g. an administrator). Free-mail / unregistered domains -> REQUEST_AUTHORIZATION even with a valid entitlement (0014, Q9, Q11). Corporate cross-client (Q8) OK. Confidence: medium-high (the Q8/Q9 pair could also be one oracle error).
- R5': no_email_confirm -> REQUEST_AUTHORIZATION (Q12), checked after sender authorization and before instrument resolution. legal_hold -> ESCALATE (Q10), checked after authorization. Confidence: high / medium (order vs instrument for legal hold is a guess).
- R7': no date -> as_of = previous business day before sent, as_of_assumed = true (Q1). Relative dates are not "assumed" (Q14). Confidence: high.
- R10': settled <= 0 -> NOT_HELD regardless of client figure (Q13). Confidence: high.
- R11': desk's comparison figure = settled + pending (matched, settle_date > as_of). Client figure matching it -> CONFIRMED; client figure equal to the same total computed without split adjustment also matches (Q15). Otherwise ESCALATE (0006, Q2, Q3). Tolerance: exact for plain numbers (smallest escalated gap in data ~2%); for abbreviated figures (12.5k, 1.2mm) match at the stated precision. Confidence: high (tolerance: low).
- R12': pending = sum of matched instructions with settle_date > as_of; pending_date = latest such settle date (Q5-Q7). Confidence: high (latest vs earliest: medium).
- Order: account -> sender auth -> no_email -> legal_hold -> instrument -> date -> figure.
