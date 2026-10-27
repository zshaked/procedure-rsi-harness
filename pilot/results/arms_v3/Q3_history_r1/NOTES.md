# Induced desk procedure (history-only arm)

Rules, applied in order:
1. Account: the account mention must resolve to exactly one account. Sub-account ids are accepted. Zero or several matches gives REQUEST_INFO, even when the sender is entitled to one of them. If no account is named, use the sender's only entitlement.
2. Sender must be a known contact with a level-3, unexpired entitlement on that account. Otherwise REQUEST_AUTHORIZATION. This check comes before the missing-instrument check (Q3-0015). The sender's domain is not checked (Q3-0023 came from yahoo).
3. Instrument missing or unresolved gives REQUEST_INFO. So do an unparseable or inconsistent date and a future date.
4. If the profile has no_email_confirm, REQUEST_AUTHORIZATION. If it has legal_hold, ESCALATE.
5. No date given: use the sent date, with as_of_assumed true. A non-business date rolls back to the previous business day.
6. Settled figure: the ledger summed over all sub-accounts up to as_of, with split adjustment. The cached position summary is wrong: it uses the previous business day and the primary sub-account only.
7. ESCALATE when the client's stated figure differs, when the figure is negative, or when as_of is before the 2025-12-15 opening load. A client figure equal to settled plus matched pending is not a break: CONFIRMED, with pending reported (3 unlabeled cases fit this exactly).
8. Zero settled gives NOT_HELD. Otherwise CONFIRMED. Pending = matched instructions settling after as_of and within 14 days of sent.

Inputs: histories (via harness), the tool docstrings and state statistics, and the unlabeled requests for date/figure phrasings and figure checks. Q3-0022 is treated as an operator mistake.

Least sure about: the pending window (Q3-0018 and Q3-0020 left out far-dated matched instructions), rolling weekend dates back, ESCALATE for pre-opening dates, and the order of no_email_confirm and legal_hold.
