# NOTES

## Rules believed (decision order)
1. Resolve account via mentions (search_accounts). Ambiguous/unknown -> REQUEST_INFO (entitlement does not disambiguate). Missing account ("our fund"): use sender's single unexpired entitlement, else INFO.
2. Auth: sender needs an unexpired entitlement on that account with level>=3 (levels 1-2 fail, other account fails) else REQUEST_AUTHORIZATION. Domain is irrelevant.
3. Instrument missing/ambiguous -> REQUEST_INFO.
4. Date: none -> sent date, assumed (but INFO for no_email_confirm accounts); future or non-business (weekend/holiday, explicit or relative) -> REQUEST_INFO, no roll-back.
5. no_email_confirm -> REQUEST_AUTHORIZATION (guess, after date checks). legal_hold -> ESCALATE (guess, untested).
6. Settled = ledger sum over all sub-accounts, date<=as_of, entries before a split with split date<=as_of multiplied by ratio.
7. Zero -> NOT_HELD (even if client claims a figure). Client figure not equal to settled or settled+matched pending -> ESCALATE. Settled >=1,000,000 -> ESCALATE.
8. Else CONFIRMED; pending = matched instructions with as_of < settle <= sent+28d (earliest date).

## Oracle log (15/15 used)
1 Q22 my AUTH: ok (history INFO was operator error).
2 Q25 CONFIRMED despite domain mismatch: ok.
3 Q87 as_of rolled back from Saturday: rejected -> ask for date (INFO).
4 Q33 relative weekend date INFO: ok.
5 Q80 ESCALATE on zero holding with claim: rejected -> NOT_HELD first.
6 Q74 ESCALATE, tiny claim mismatch: rejected; claim = settled+matched pending, so reconcile; then 7 Q74 CONFIRMED no pending: ok.
8 Q123 pending +20d reported: ok.
9 Q193 pending settle already before sent: ok.
10 Q84 no_email_confirm AUTH: rejected, no date -> INFO.
11 Q43 CONFIRMED with assumed date: ok.
12 Q111 NEC with holiday date INFO: ok.
13 Q145 and 14 Q31 CONFIRMED large: rejected -> size escalation (threshold in (855k,1.2M], used 1M).
15 Q148 split after as_of not applied: ok.

## Least sure
Pending window (between 20 and 34 days, used 28); size threshold; legal_hold handling; NEC with valid date -> AUTH; split multiplication (never directly verified); future dates.
