**Process.** Tabulated features (auth level, contact-account match, resolution counts, position, stated qty), wrote procedure.py, iterated with harness.py, and asked the oracle only about my own outputs where they disagreed with operators or a threshold was unclear. 12 of 25 questions used.

**Oracle log** (response -> verdict)
1. 0012 AUTH (contact not on account; op INFO) -> OK
2. 0056 AUTH (auth lvl 2, no instrument; op INFO) -> OK
3. 0010 ESCALATE (settled 1.29M; op CONFIRMED) -> OK
4. 0126 ESCALATE (stated 4% off) -> NO, "fine to confirm"
5. 0115 CONFIRMED (stated 4% off; op ESCALATE) -> OK
6. 0099 CONFIRMED, no date, pending 51 omitted (op ESCALATE) -> OK
7. 0038 CONFIRMED reporting pending 884 -> NO, pending handling wrong
8. 0004 NOT_HELD (op INFO) -> OK
9. 0166 INFO (ambiguous account; op AUTH) -> OK
10. 0199 AUTH (lvl 2; op CONFIRMED) -> OK
11. 0027 ESCALATE (stated 50% off; op CONFIRMED) -> OK
12. 0069 ESCALATE (settled 1.01M; op CONFIRMED) -> OK

**Rules (in order).** Unknown contact or auth_level<3 -> REQUEST_AUTHORIZATION. Account ref not unique -> REQUEST_INFO. Contact's account != account -> REQUEST_AUTHORIZATION. Instrument missing/ambiguous -> REQUEST_INFO. No as_of -> use request date, as_of_assumed. No position / settled 0 -> NOT_HELD. Settled >= 1,000,000 or stated qty off by >5% of settled -> ESCALATE. Else CONFIRMED; report pending only if >= 1,000.

**Least sure.** Pending-report threshold (885–6,187; chose 1,000). Mismatch tolerance (4–7.4%; chose 5%). Harness 184/200; remaining disagreements look like operator errors.
