# Induced desk procedure (history-only arm)

Rules, in order:
1. Account and instrument must each resolve to exactly one record (search_accounts / search_instruments on the extracted mentions; old tickers, ISINs, names, short names and sub-account ids are allowed). Missing or ambiguous: REQUEST_INFO. Sender entitlements are not used to disambiguate (Q2-0002).
2. A date later than the sent date: REQUEST_INFO. No date: assume the previous business day before the sent date (as_of_assumed=true).
3. Authorization: the sender must be a known contact whose email domain is one of the client profile's domains and who holds an unexpired entitlement of level 2 or higher on that account. Otherwise REQUEST_AUTHORIZATION.
4. legal_hold or no_email_confirm on the profile: ESCALATE.
5. Settled figure: raw ledger summed over all sub-accounts up to and including as_of. A date that is not a business day rolls back to the previous business day. Entries dated before a split are multiplied by its ratio once as_of is on or after the split date. The cached position summary is not used: it covers the primary sub-account only and is lagged one day.
6. Zero: NOT_HELD. The client's stated figure differs: ESCALATE. Otherwise CONFIRMED, with matched instructions that settle after as_of reported as pending (summed, latest date).

Inputs: 25 histories (24/25 agree); unlabeled requests used for phrasing coverage (dates, quantities, missing mentions, short-name collisions).

Least sure: Q2-0006 (escalated although the figure matches; treated as an operator mistake, possible weekend rule). Stated figure vs zero holding (I chose NOT_HELD). no_email_confirm handling. How multiple pending instructions are reported. Whether a mentioned sub-account limits the figure to that sub-account.
