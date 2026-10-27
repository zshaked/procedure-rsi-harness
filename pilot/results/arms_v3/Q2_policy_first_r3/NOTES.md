# Notes

**Rules (in order):** account/instrument missing, unknown or ambiguous (incl. "Falcon Capital" prefix hits, duplicate short names) -> REQUEST_INFO. Sender domain must be in the client profile, contact entitled to that account at level >= 2, unexpired at `sent`; else REQUEST_AUTHORIZATION. legal_hold (and, unverified, no_email_confirm) -> ESCALATE. Date: explicit/relative ("yesterday", "end of last month"), rolled back to the prior business day; none given -> sent date, as_of_assumed=true; future -> REQUEST_INFO. Settled = ledger summed over ALL sub-accounts (even when a sub-account is named), split-adjusted; not get_position_summary. Settled <= 0 -> NOT_HELD (even if client quotes a figure). Pending = matched instructions settling after as_of with qty >= 1000 (sum, earliest date). Client figure must equal settled+pending (or the pre-split unadjusted equivalent), else ESCALATE.

**Inputs:** histories/state for the skeleton (25/25); unlabeled + oracle for rare cases.

**Oracle log (15):** 0006 CONF -> no (escalate; pending counts). 0075 weekend CONF -> yes. 0051 fig=settled+pending CONF -> yes. 0034 as_of=sent-1 -> no (wrong date). 0076 as_of=sent, pending 601 -> no (pending). 0140 as_of=sent, pending 38954 -> yes. 0076 pending 1803 -> no. 0076 pending null -> yes. 0050 pending 303 omitted -> yes. 0190 pending 348 omitted -> yes. 0142 legal hold+unentitled ESCALATE -> no (auth first). 0169 zero+figure ESCALATE -> no (NOT_HELD). 0191 sub-account, whole-account total -> yes. 0096 legal hold ESCALATE -> yes. 0128 unadjusted figure ESCALATE -> no (confirm).

**Least sure:** pending threshold (1000 absolute?), no_email_confirm, multi-instruction aggregation, future dates.
(oracle.py printed once by accident; unused.)
