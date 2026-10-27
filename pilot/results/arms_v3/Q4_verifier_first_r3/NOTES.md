# Notes (verifier-first)

**Rules (in order):** freemail/unknown sender -> RA; account must resolve uniquely (else REQUEST_INFO); sender domain registered for the account plus unexpired entitlement level >= 2 (else RA); instrument and position date needed (else REQUEST_INFO); date after `sent` -> REQUEST_INFO; legal_hold -> ESCALATE. Date rolls to previous business day. Settled = raw ledger summed over all sub-accounts (not get_position_summary), split-adjusted, entries <= as_of. Negative -> ESCALATE; zero -> NOT_HELD. Client figure >10% from both settled and settled+pending -> ESCALATE; else CONFIRMED. Pending = matched instructions settling after as_of, summed, dated at the latest. as_of_assumed is always False. no_email_confirm and former tickers do not block.

**Inputs:** The verifier comes from the histories, the unlabeled cases (client-figure ratios cluster at 0.93–1.08 vs 0.85/1.5/pre-split) and tools.py. procedure.py won a coordinate search scored by verifier pass rate over all 200 (200/200; other variants 164–197). Harness 25/25.

**Oracle (15/15):** 0094 0.93 C ok | 0077 1.08 C, flag wrong | 0104 month-end assumed=T wrong | 0028 no date -> ask | 0129 missing instr INFO ok | 0054 no_email_confirm: confirm, include pending | 0114 hold ESC ok | 0083 future INFO ok | 0157 zero+claim NOT_HELD, flag wrong | 0032 foreign domain -> RA | 0049 old ticker C ok | 0046 assumed=F ok | 0156 weekend entry excluded ok | 0118 lvl1+hold RA ok | 0086 lvl1+no date RA ok.

**Least sure:** where the tolerance edge sits between 8% and 15%; whether as_of_assumed is ever True; negative positions; dates equal to `sent`.
