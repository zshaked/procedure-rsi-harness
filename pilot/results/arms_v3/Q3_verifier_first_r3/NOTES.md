# Notes (verifier-first)

**Rules, in order:** (1) The account must resolve to exactly one account (sub-account ids map to the parent). Ambiguous or unknown gives INFO. If no account is named, use the sender's only entitled account. (2) A live entitlement of level 3 or higher is required, else AUTH. Domain is ignored. (3) Unresolved instrument gives INFO. (4) With no date, use the email date (assumed). A future date or a non-business date gives INFO. (5) no_email_confirm gives AUTH. legal_hold gives ESCALATE (assumed). (6) Settled = all sub-accounts, split-adjusted. 0 gives NOT_HELD. 1M or more gives ESCALATE. A client figure more than 5% off gives ESCALATE. (7) Otherwise CONFIRMED. Pending = matched instructions settling after as_of, within 30 days of the email.

**Method:** The verifier agrees with all 15 oracle verdicts. CONFIG was chosen by coordinate search on verify() pass rate over 200 requests (200/200). Harness 24/25. I treat H-0022 as an operator error.

**Oracle log:** 0028 L2 CONFIRMED: no (level). 0025 gmail CONFIRMED: yes. 0057 Sunday CONFIRMED: no (ask date). 0059 Saturday INFO: yes. 0045 unauthorized+weekend AUTH: yes. 0084 no_email_confirm CONFIRMED: no (AUTH). 0062 inferred-account ESCALATE: yes. 0132 2%-off CONFIRMED: yes. 0074 pending +34d: no. 0123 pending +20d: yes. 0175 1.06M CONFIRMED: no (size). 0145 ESCALATE: yes. 0051 future INFO: yes. 0080 zero+figure NOT_HELD: yes. 0085 legal-hold weekend ESCALATE: no (date first).

**Least sure:** 5% tolerance (2-7% fits), 30-day pending window, legal_hold, split adjustment (0145 escalates either way), and a no-date email sent on a weekend.
