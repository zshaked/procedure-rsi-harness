# NOTES
Plan (S2 then S3, written before asking): S2 = qty_mismatch Q172, no_account Q62, claim_match Q132, confirm_pending Q123, no_email_confirm Q84, zero_vs_claim Q80, not_held Q32, claim_incl_pending Q76, future_date Q51, legal_hold Q85; S3 = expiry Q53, tolerance below Q175 / above Q146, weekend handling Q64, as_of-day ledger inclusive Q165. S4-exempt: confirmed, account_ambiguous, instrument_missing.

Rules: ambiguous/unknown account -> INFO; no account text -> AUTH; sender needs unexpired level>=3 entitlement on the account else AUTH (before date checks); missing/unknown instrument -> INFO; non-business-day or future date -> INFO; legal_hold -> ESCALATE; no_email_confirm -> AUTH; no date -> sent date, assumed; settled = ledger sum <= as_of (inclusive), splits applied only if split date <= as_of; zero -> NOT_HELD (claim ignored); settled >= 1,000,000 -> ESCALATE; client figure differing >5% from settled (or settled+matched pending) -> ESCALATE; else CONFIRMED, pending = matched instructions settling after as_of within 30 days of sent, date rolled to next business day.

Oracle (15 used; ok = acceptable as sent):
1 Q172 ok. 2 Q62 ok. 3 Q132 ok. 4 Q123 wrong pending date (13615 on Sunday 03-29): pending date now rolls to next business day. 5 Q84 no-email client: ESCALATE wrong, now AUTH. 6 Q80 zero position with claim: now NOT_HELD. 7 Q32 ok. 8 Q76 Saturday month-end: roll wrong, now INFO (also Q22 hist reading). 9 Q51 ok. 10 Q85 legal hold on Saturday: date check precedes hold. 11 Q53 ok. 12 Q175 (1,056,400): size escalates, added 1M threshold. 13 Q146 ok. 14 Q64 ok. 15 Q165 ok.
Harness: Q22 is a single disagreement (contradicted by Q10/Q14, left as operator error).

Least sure: 1M threshold (between 855k and 1.056M; settled vs settled+pending); pending window/lower bound and date roll direction; 5% tolerance (only 4% and 7% seen); order of date check vs no_email_confirm; split convention.
