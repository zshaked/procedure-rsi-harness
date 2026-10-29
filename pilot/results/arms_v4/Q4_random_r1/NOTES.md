# Rules (inferred)
1. Account text via search_accounts; unique match required. Ambiguous/missing account: REQUEST_INFO, unless sender's domain matches none of its entitled accounts' profile domains (then REQUEST_AUTHORIZATION).
2. Authorization (before anything else): contact exists, entitlement for that account, level >= 2, not expired at sent date, sender domain in profile domains. Otherwise REQUEST_AUTHORIZATION.
3. Instrument via ticker/old ticker/name/id; unresolved -> REQUEST_INFO.
4. legal_hold -> ESCALATE. no_email_confirm -> ESCALATE (guess, untested).
5. Date: strip forwarded headers; explicit formats (M/D/Y), yesterday, month-end = last day of previous month. Missing or future date -> REQUEST_INFO. Non-business day rolls back to the previous business day (as_of_assumed stays False).
6. Settled = sum of all sub-account ledger rows dated <= as_of, multiplied by split ratio if split date <= as_of and row predates it. Not get_position_summary (primary sub-account only).
7. Pending = matched instructions settling after as_of (sum, latest date); unmatched/cancelled ignored.
8. Client's stated figure differing from settled+pending by more than 10% -> ESCALATE (also when it equals the pre-split number). Zero/no rows -> NOT_HELD.

# Oracle (15 asked, in fixed order); all 15 acceptable, so no change was made because of any answer
Q4-0191 (ambiguous Calloway Capital -> REQUEST_INFO), 0165 (month-end CONFIRMED), 0162 (CONFIRMED with pending), 0107 (NOT_HELD), 0063 (2% figure gap CONFIRMED), 0116 (undated, unauthorized sender -> REQUEST_AUTHORIZATION), 0195 (REQUEST_AUTHORIZATION), 0083 (future date -> REQUEST_INFO), 0132 (undated -> REQUEST_INFO), 0095 (ambiguous -> REQUEST_INFO), 0174 (REQUEST_AUTHORIZATION), 0104 (8% gap CONFIRMED), 0183 (figure = settled+pending, CONFIRMED), 0168 (expired entitlement -> REQUEST_AUTHORIZATION), 0114 (legal hold -> ESCALATE).

# Least sure
Exact mismatch tolerance (between 8% and 15%; history Q4-0000 at 4% confirmed). no_email_confirm handling. as_of_assumed never true in the histories, so never set. NOT_HELD when settled is 0 but pending exists. Whether a negative or zero stated figure is handled sensibly.
