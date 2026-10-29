# Desk rules (induced)
Account missing/ambiguous -> REQUEST_INFO. Then sender must be known, on a client-registered domain, level>=2, unexpired at sent date, and client not no_email_confirm, else REQUEST_AUTHORIZATION. Then security (former tickers ok; missing -> REQUEST_INFO), legal_hold -> ESCALATE. as_of = stated/relative date (none: sent date, assumed), moved back to a business day. settled = ledger over all sub-accounts to as_of inclusive, split-restated if split already effective; 0 -> NOT_HELD. pending = matched instructions with settle_date > as_of (sum, latest date). Quoted figure must equal settled+pending (or pre-split figure+pending) else ESCALATE; otherwise CONFIRMED.

# Oracle questions (15)
1 Q0161 AUTH (entitled, wrong domain): yes.
2 Q0105 INFO: no; no_email_confirm -> AUTH, before security check.
3 Q0174 AUTH (legal hold, unentitled): yes; auth first.
4 Q0041 AUTH (level 1, no security): yes.
5 Q0179 CONFIRMED: no ("no security named", contradicts email); treated as oracle error.
6 Q0089 pending earliest date: no -> latest date.
7 Q0069 sum/latest: yes.
8 Q0025 pending settling before sent: yes; test is settle_date > as_of.
9 Q0006 CONFIRMED: no (figure mismatch) -> compare quote with settled+pending.
10 Q0051 CONFIRMED settled+pending: yes.
11 Q0128 ESCALATE (pre-split quote): no -> accept pre-split quote.
12 Q0197 ESCALATE (zero, quote): no -> NOT_HELD before comparison.
13 Q0053 old ticker, weekend month-end: yes.
14 Q0070 INFO: no ("positions that size escalate"); suspected decoy.
15 Q0070 ESCALATE: no (no security named); INFO kept, no size rule.

# Least sure
Possible size-threshold escalation; tolerance on quoted figures (exact, except k/mm rounding); settled 0 with pending; future dates; quote equal to settled while pending exists (Q0006 only); stale-split and NOT_HELD rest on single answers; SA- mentions treated at parent level.
