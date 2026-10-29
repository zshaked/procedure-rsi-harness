# NOTES

## Rules (gate order)
1. Ambiguous account text -> INFO.
2. Sender needs live level-3 entitlement on the named account; none/lower/no account named -> AUTH.
3. Instrument missing/ambiguous -> INFO.
4. no_email_confirm -> AUTH.
5. As-of: missing -> sent date (assumed); non-business day or future -> INFO.
6. legal_hold -> ESCALATE.
7. Settled = ledger, all sub-accounts, up to as-of, split-adjusted. Zero -> NOT_HELD even if client quoted a figure.
8. Settled >= 1,000,000 or client figure >5% off -> ESCALATE; else CONFIRMED.
9. Pending = matched instructions settling after as-of, no horizon, ignored if < 1,000.

## Oracle (15)
1 Q3-0057 rolled-back weekend: no, "not a business day, ask" -> INFO.
2 Q3-0028 AUTH at level 2: yes.
3 Q3-0123 no pending: no -> report pending.
4 Q3-0031 confirm 1.2M: no, size escalates.
5 Q3-0046 pending 68 days out: yes -> no horizon.
6 Q3-0132 ESCALATE at 2% gap: no -> tolerance.
7 Q3-0080 ESCALATE, figure quoted, zero held: no -> NOT_HELD.
8 Q3-0084 ESCALATE no-email client: no -> AUTH.
9 Q3-0085 ESCALATE legal hold on Saturday: no -> date check first.
10 Q3-0063 AUTH unentitled+Sunday: no, odd reason -> noise.
11 Q3-0037 same shape: yes -> AUTH before date.
12 Q3-0146 ESCALATE 7% gap: no ("wrong account") -> noise.
13 Q3-0074 pending 656: no -> minimum size.
14 Q3-0083 NOT_HELD, "as at Month D, YYYY": yes -> date parses; 10, 12 were noise.
15 Q3-0090 INFO, no-email + future date: no -> no-email precedes date.

## Least sure
Pending materiality (absolute vs ~1%); tolerance edge (2-7%, set 5%); size threshold (set 1M); legal hold outcome; future-date and holiday-sent INFO; negative positions; expiry vs sent date; split boundaries. History Q3-0022 treated as operator mistake.
