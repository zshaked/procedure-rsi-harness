# Desk rules — spec

Evidence: H = history, O = oracle answer (log below). Confidence H/M/L. Rules apply in this order.

1. **Account.** `search_accounts(account_text)` (id, sub-account id, name, short name). 0 or >1 hits -> REQUEST_INFO, even if the sender is entitled to one candidate (H0000, 0006, 0007, 0017, 0021). Conf H.
   - Sub-account id given -> parent account, whole-account figure (no discriminating case available). Conf L.
2. **Account not mentioned** -> infer from the sender's sole unexpired entitlement (O7 accepted; H0024 inferred account has no_email_confirm -> RA). No entitlement -> RA; several -> RI. Conf M.
3. **Authorization.** Known contact with unexpired entitlement, level >= 3, on that account; else REQUEST_AUTHORIZATION (H0002, 0003, 0005, 0009, 0010, 0014, 0015, 0016). Before instrument/date completeness (H0015). Sender e-mail domain is NOT checked (O1, H0023). H0022 (RI) treated as operator mistake. Conf H.
4. **Instrument** missing/unresolved/ambiguous -> REQUEST_INFO (H0004, 0007, 0019). Conf H.
5. **legal_hold** -> ESCALATE (O5); **no_email_confirm** -> REQUEST_AUTHORIZATION (O6, H0024). Both are checked before the date check (O5/O6 cases had non-business dates) but after instrument (H0004). Conf M-H.
6. **Date.** ISO, M/D/Y, D-Mon-Y, Month D, Y, weekday forms, close of business, yesterday, end of last month / last day of last month / month-end (= last day of previous month). No date -> email sent date, as_of_assumed=true (H0023). Conf M.
   - Date after sent date -> REQUEST_INFO (O15). Conf M.
   - **Non-business day** (weekend or calendar holiday, incl. relative dates like "yesterday") -> REQUEST_INFO (O9, O10, O11; O7 disagreed — judged oracle error). Conf M-H.
7. **Figure** = settled ledger summed over ALL sub-accounts with date <= as_of (H0001, 0018, 0020); lots before a split dated <= as_of multiplied by the ratio. get_position_summary is not used (primary sub only, previous business day). Conf H (sum), M (split).
8. **Size**: settled >= 1,000,000 -> ESCALATE (O4, O12; max confirmed in H is 855,399). Exact threshold Conf M.
9. **Client-stated figure** differing from ours by more than tolerance -> ESCALATE (H0012 7%, O2 15%); 2% accepted (O3). Tolerance set at 5% (4% untested); also accept if it matches settled + pending. Conf M.
10. Negative -> ESCALATE (guess, L). Zero -> NOT_HELD (H0023).
11. **Pending**: matched instructions with settle_date > as_of and <= sent + 60 days, summed; date = latest. Reported: H0008 (sent+7), O8 (sent+20), O14 (sent+34). Not: H0018 (+81), H0020 (+122), O13 (+68, vague rejection). Window 34–68 days; 60 chosen. Conf L-M.

## Oracle log (15/15 used)
| # | case | response | result |
|---|---|---|---|
| 1 | Q3-0025 | CONFIRMED (gmail sender, lvl3) | OK |
| 2 | Q3-0172 | CONFIRMED, stated 15% off | NO: "doesn't match ours closely enough; escalation" |
| 3 | Q3-0132 | CONFIRMED, stated 2% off | OK |
| 4 | Q3-0175 | CONFIRMED 1,056,400, no date, 4% off | NO: "Positions that size always go to escalation" |
| 5 | Q3-0085 | ESCALATE (legal hold, lvl3) | OK |
| 6 | Q3-0111 | REQUEST_AUTHORIZATION (no_email_confirm, lvl3) | OK |
| 7 | Q3-0127 | CONFIRMED, account inferred, as_of Sat 28 Feb | OK (weekend part contradicted by 9-11) |
| 8 | Q3-0123 | CONFIRMED + pending sent+20 | OK |
| 9 | Q3-0185 | CONFIRMED as_of 2/28/2026 (Sat) + pending sent+85 | NO: "not a business day; we ask them which date" |
| 10 | Q3-0034 | REQUEST_INFO (Sunday date) | OK |
| 11 | Q3-0126 | REQUEST_INFO ("yesterday" = Sunday) | OK |
| 12 | Q3-0145 | ESCALATE (2.79m after split) | OK |
| 13 | Q3-0046 | CONFIRMED + pending sent+68 | NO: "Not sure this is right" |
| 14 | Q3-0074 | CONFIRMED + pending sent+34 (stated = settled+pending) | OK |
| 15 | Q3-0051 | REQUEST_INFO (future date) | OK |
