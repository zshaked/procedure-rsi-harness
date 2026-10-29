# Desk rules (procedure.py)

1. Account must resolve uniquely, else REQUEST_INFO (first, even for weak senders).
2. REQUEST_AUTHORIZATION unless sender is a known contact with an unexpired (vs sent) entitlement, level >= 2, on that account, from a registered client domain; also if no_email_confirm.
3. legal_hold: ESCALATE (after auth checks).
4. Instrument unique (ticker, former ticker, name, ISIN) else REQUEST_INFO. Future date: REQUEST_INFO (guess).
5. as_of: stated date (relative phrases from sent; month-end = prior month's last day), rolled back to previous business day; none given: sent date, assumed.
6. settled = ledger over all sub-accounts to as_of, split-multiplied when split date <= as_of. Zero: NOT_HELD.
7. Client figure must equal settled + matched pending (settle_date > as_of), else ESCALATE.
8. CONFIRMED: pending = sum of matched, date = latest.

# Oracle (15/15)

1. Q2-0060 free-mail, entitled, AUTH: yes.
2. Q2-0125 corporate domain mismatch, entitled, AUTH: yes.
3. Q2-0096 legal hold, ESCALATE: yes.
4. Q2-0145 legal hold + level 1, AUTH: yes.
5. Q2-0041 missing instrument + level 1, INFO: no (entitlement too low). Auth before instrument.
6. Q2-0061 free-mail + ambiguous account, INFO: yes.
7. Q2-0105 no_email_confirm + missing instrument, INFO: no (needs authorization). Added rule.
8. Q2-0006 CONFIRMED: no, number mismatch.
9. Q2-0097 CONFIRMED (figure = settled, pending exists): no.
10. Q2-0051 CONFIRMED (figure = settled + pending): yes. Compare with settled+pending.
11. Q2-0157 NOT_HELD with client figure: yes. Zero check first.
12. Q2-0025 pending settling before sent: yes (relative to as_of).
13. Q2-0089 two pending, earliest date: no. Use latest.
14. Q2-0053 old ticker + month-end: yes.
15. Q2-0069 sum, latest, "yesterday": yes.

# Least sure

Future dates; missing instrument alone; holiday sent date; zero settled with pending; legal hold vs missing instrument order; k/mm tolerance; pre-split client figure (ESCALATE assumed).
