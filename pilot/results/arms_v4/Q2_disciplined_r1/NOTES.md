# NOTES

**Rules.** Resolve account (name/id/sub-account); missing or ambiguous -> REQUEST_INFO. Authorize: known contact, live entitlement (expires >= sent), level >= 2, sender domain in client domains, else REQUEST_AUTHORIZATION. no_email_confirm -> REQUEST_AUTHORIZATION; legal_hold -> ESCALATE; missing instrument -> REQUEST_INFO. Date: weekend/holiday -> previous business day; none -> sent date, assumed. Settled = all sub-accounts, ledger <= as_of, split-adjusted. Zero -> NOT_HELD. Stated figure != settled + matched pending -> ESCALATE. Else CONFIRMED with pending (matched, settle > as_of; summed, latest date).

**Plan** (pre-registered: S2 unsupported branches, then S3 conventions; S4 skipped confirmed, account_ambiguous, auth_no_entitlement, qty_mismatch).

**Oracle (15 of 15)**
1. Q2-0125 auth_domain: ok.
2. Q2-0187 auth_level: ok.
3. Q2-0037 account_missing: ok.
4. Q2-0070 instrument_missing: ok.
5. Q2-0157 stated figure, zero position, I said ESCALATE: no -> zero check now precedes mismatch (NOT_HELD).
6. Q2-0153 not_held: ok.
7. Q2-0096 legal_hold: ok.
8. Q2-0105 no_email_confirm, I said ESCALATE: no -> REQUEST_AUTHORIZATION, before instrument check.
9. Q2-0121 auth_expired: ok.
10. Q2-0155 auth precedes missing instrument: ok.
11. Q2-0177 auth precedes legal_hold: ok.
12. Q2-0097 stated = settled but pending exists, I said CONFIRMED: no -> compare with settled + pending (Q2-0006 now agrees).
13. Q2-0179 level-2 sender sees pending: ok.
14. Q2-0025 pending settling between as_of and sent: ok.
15. Q2-0089 two pending, I gave earliest date: no -> latest date.

**Least sure.** Tolerance on stated figure (exact equality used; "closely enough" hints at one). Unmatched pending ignored. Future as-of dates (REQUEST_INFO, never tested). Holiday sent date with no date given. Pending settle date equal to as_of. legal_hold with missing instrument. "month-end" meaning.
