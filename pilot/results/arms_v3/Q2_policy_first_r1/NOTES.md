# Notes: Q2 policy-first

## Rules (in order)
1. Account or instrument missing, unknown or ambiguous: REQUEST_INFO. Name prefixes and duplicate short names count as ambiguous. Old tickers and sub-account ids resolve.
2. Sender domain not in the profile's domains, or no unexpired entitlement at level 2 or higher: REQUEST_AUTHORIZATION.
3. legal_hold: ESCALATE. no_email_confirm: ESCALATE (a guess).
4. Date: a non-business day rolls back. No date means as-of = sent date, assumed. A future date is REQUEST_INFO.
5. Settled = all sub-accounts' ledger up to the as-of, split-adjusted. 0 or less: NOT_HELD, even when the client quotes a figure.
6. Pending = matched instructions settling after the as-of. The client figure is compared with settled + pending (or the pre-split count). Mismatch: ESCALATE. Otherwise CONFIRMED.

## Inputs
Rules come from the histories and tool docs, are tested on 175 unlabeled cases, then checked with the oracle.

## Oracle log (15 used)
0006 CONFIRMED: no, mismatch. 0097 figure = settled: no, so comparison is with settled + pending. 0051 figure = total: yes. 0026: yes. 0096 legal hold: yes. 0145 legal hold, level 1, REQUEST_AUTHORIZATION: yes. 0034 as-of sent-1: no. 0103 as-of = sent: yes. 0191 sub-account, account total: yes. 0069 split: yes. 0157 zero, ESCALATE: no, NOT_HELD. 0123: yes. 0125 corporate domain mismatch: yes. 0128 pre-split figure, ESCALATE: no, confirm. 0189 no_email_confirm, ESCALATE: no, the domain check comes first.

## Least sure
no_email_confirm for authorized senders, the mismatch tolerance, future dates, and pending_date when there are several instructions.
