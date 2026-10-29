# NOTES

## Rules
Resolve account (mentions via search_accounts; none/ambiguous -> REQUEST_INFO), then sender checks: contact, entitlement for that account, unexpired, level>=2, sender domain in profile -> else REQUEST_AUTHORIZATION. Then instrument (missing/ambiguous -> REQUEST_INFO), legal_hold/no_email_confirm -> ESCALATE. Date: parsed (M/D/Y), none -> sent date with as_of_assumed; weekend/holiday -> previous business day. Settled = all-subaccount ledger <= as_of, pre-split rows x ratio. Zero -> NOT_HELD. Stated figure not equal to settled, settled+pending or raw unadjusted -> ESCALATE. Pending = matched, settle_date > as_of (sum, earliest date).

## Plan (written before asking; S2 then S3)
S2: Q106 domain_mismatch, Q187 auth_level, Q70 instrument_missing, Q47 account_missing, Q123 zero_position, Q96 legal_hold, Q121 entitlement_expired. S3: Q34 no date, Q108 holiday, Q76 same-day ledger row, Q29 month-end, Q157 stated vs zero, Q128 pre-split stated, Q51 stated=settled+pending, Q112 pending threshold.

## Oracle log (15/15)
Q106, Q187, Q70, Q47, Q123, Q96, Q121, Q108, Q76, Q29, Q112: acceptable, no change.
Q34: rejected, "Wrong account" (TEII short name, no date). One answer, short-name resolution supported by 4 histories, so R2 forbids change; unexplained, left as is.
Q157: rejected, should be NOT_HELD; zero position now checked before figure mismatch.
Q128: rejected, "fine to confirm with settled position" (stated = pre-split qty).
Q51: rejected, confirm and report pending (stated = settled+pending). Two contradicting cases, so figure rule relaxed as above.

## Least sure
Q34 anomaly; Q0006 (history ESCALATE, stated = settled, matched pending) disagrees with my procedure; future dates; unmatched pending; order of instrument check vs authorization; no_email_confirm outcome (guessed ESCALATE); month-end meaning.
