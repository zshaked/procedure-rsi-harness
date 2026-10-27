# Q4 policy-first notes

**Rules:** unknown contact -> REQ_AUTH. No account named: use the sender's single own-domain entitled account; none -> REQ_AUTH. Sender domain not in the account's domains -> REQ_AUTH. Ambiguous or missing account, instrument or date, or a future date -> REQUEST_INFO. Entitlement must be level >= 2 and unexpired, else REQ_AUTH. Then legal_hold -> ESCALATE. Figure = ledger across all sub-accounts up to and including as_of, split-adjusted. as_of = stated date ("month-end" = end of last month) rolled back to a business day; as_of_assumed is always false. Zero -> NOT_HELD. Client figure more than 10% from settled and from settled + pending -> ESCALATE. Else CONFIRMED. Pending = matched instructions settling after as_of, dated by the latest one.

**Inputs:** histories plus tool diagnostics (harness 25/25). Client-figure ratios in the data cluster at 0.85, 0.93, 1.02-1.08 and 1.5.

**Oracle log (15):** 0077 CONF at 8% off: ok. 0066 CONF matching settled + pending: ok. 0114 legal-hold ESC: ok. 0054 no_email_confirm REQ_AUTH: no, confirm with pending. 0098 month-end assumed=true: flag wrong. 0083 future date CONF: no. 0016 no date, assumed: no, ask. 0121 weekend roll assumed=true: flag wrong. 0156 sub-account, whole-account figure: ok. 0148 same-day ledger included: ok. 0161 NOT_HELD: ok. 0157 zero with a client figure, ESC: no, NOT_HELD. 0168 expired entitlement REQ_AUTH: ok. 0118 legal hold plus level 1, REQ_AUTH: ok. 0055 no account, REQUEST_INFO: "not sure".

**Least sure:** inferring a missing account, ignoring no_email_confirm, the exact tolerance (8-15%), and the outcome for a future date.
