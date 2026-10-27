# P3 desk spec (phase 1: induced from histories)

Notation: contact = get_contact(from); account = lookup_account(account_ref); instrument = resolve_instrument(instrument_ref).
Checks are applied in order; first matching rule decides.

1. **Authority level.** If the sender's contact record has auth_level < 3 (or no contact), reply REQUEST_AUTHORIZATION.
   Evidence: L1/L2 senders -> AUTH in 52/57 cases (e.g. 0008, 0011, 0035, 0039, 0105, 0118, 0135, 0146; ambiguous-account L2 0005, 0018, 0101 -> AUTH). Exceptions treated as operator error: 0199 (CONFIRMED), 0032, 0056, 0067 (INFO). Confidence: high.
2. **Account must resolve to exactly one account.** If account_ref is missing or matches 0 or >1 accounts -> REQUEST_INFO.
   Evidence: L3 ambiguous -> INFO in 13/15 (0009, 0046, 0047, 0050, 0064, 0089, 0111, 0130, 0133, 0136, 0149, 0175, 0180); 0120, 0166 AUTH = noise. Applies even when contact's account is not among the candidates (0133). Confidence: high.
3. **Sender must belong to the account.** If contact.account_id != resolved account id -> REQUEST_AUTHORIZATION. Sender email domain is irrelevant (contact matched but domain/free-mail mismatch still confirmed: 0022, 0045, 0055, 0066, 0108, 0144, 0184).
   Evidence: L3 mismatch -> AUTH 26/30 (0000, 0002, 0003, 0006, 0015, 0052, 0128, ...); INFO in 0012, 0042, 0147, 0163 = noise. Confidence: high.
4. **Instrument must resolve to exactly one instrument.** Missing / 0 / >1 matches -> REQUEST_INFO.
   Evidence: 0031, 0063, 0065, 0091, 0119, 0152, 0182 (L3, matched). >1 match only seen behind rule 1/3 (0098, 0113) — assumed INFO. Confidence: high (0 matches), medium (>1 matches).
5. **Date.** as_of = fields.as_of; if missing, use request date and set as_of_assumed = true (reply says "As no date was given, we have used the date of your request"). Evidence: 0070, 0177. Confidence: high.
6. **Not held.** get_position is None or settled == 0 -> NOT_HELD (with account, instrument, as_of). Stated qty is irrelevant. Evidence: 0007, 0051, 0070, 0087, 0102, 0143, 0154, 0172; 0004 (INFO) = noise. Confidence: high.
7. **Large position escalation.** settled >= 1,000,000 -> ESCALATE. Evidence: 0001, 0013, 0026, 0041, 0061 (1,006,007), 0084, 0100, 0109, 0127, 0138, 0145, 0150, 0155, 0167, 0185, 0195; largest confirmed = 945,475 (0095). Exceptions 0010, 0069 = noise. Confidence: high (threshold between 945,475 and 1,006,007; 1,000,000 assumed).
8. **Stated-quantity mismatch escalation (UPDATED after oracle).** If stated_qty given and |stated - settled| / settled > 5% -> ESCALATE; within tolerance -> confirm normally. Oracle: 2% (0144), 4% (0126, 0115) acceptable as CONFIRMED; 8% (0037) "doesn't match closely enough; goes to escalation"; 50% (0027) ESCALATE accepted. Observed stated offsets are only 0/2/4/7/8/15/50%, so the cut is somewhere in (4%, 8%); 5% chosen. Confidence: high on existence of a relative tolerance, medium on the exact 5%.
9. **Otherwise CONFIRMED** with settled from get_position(as_of).
10. **Pending reporting.** Report pending/pending_date only when pending (as of as_of) > 0 and large: reported 6,187..44,229 (0034, 0060, 0072, 0088, 0160); omitted 11..884 (0038, 0069, 0110, 0137). Threshold assumed 1,000 units. Oracle: 0137 with pending 541 reported -> "pending amount handling isn't right"; 0060 with pending 8,707 omitted -> same objection; 0088 with 43,817 reported -> acceptable. Ratio-to-settled cannot be the rule (0060 is 1.2% and reported, 0137 is 3.4% and omitted). State pending values are bimodal (10..998 vs 1,090+), so report iff pending >= 1,000. Confidence: medium-high.
11. **Resolved:** 0099's ESCALATE was operator error — oracle accepted CONFIRMED (settled 111, no pending reported).
12. **Open question:** stated_qty equal to settled+pending (only seen in non-L3 cases 0006, 0083). Assumed mismatch -> ESCALATE (compare against settled only). Confidence: low.

## Oracle log (phase 2) — 23 of 25 questions used

| # | case | response asked | verdict | reason / takeaway |
|---|------|----------------|---------|-------------------|
| 1 | 0144 | CONFIRMED but instrument_id=null (my bug) | no | "details are wrong" — wasted question |
| 2 | 0144 | CONFIRMED 359,347 (stated +2%) | yes | 2% within tolerance |
| 3 | 0126 | CONFIRMED 689,663 (stated +4%) | yes | 4% within tolerance |
| 4 | 0115 | CONFIRMED 5,772 (stated +4%; operator escalated) | yes | operator error |
| 5 | 0037 | CONFIRMED 728,724 (stated +8%) | no | "doesn't match closely enough; goes to escalation" |
| 6 | 0099 | CONFIRMED 111 | yes | operator escalation was an error |
| 7 | 0137 | CONFIRMED + pending 541 | no | "pending amount handling isn't right" -> small pending omitted |
| 8 | 0060 | CONFIRMED without pending 8,707 | no | same -> large pending must be reported |
| 9 | 0004 | NOT_HELD (operator: INFO) | yes | operator error |
| 10 | 0010 | ESCALATE (1.29M; operator confirmed) | yes | >=1M escalates |
| 11 | 0027 | ESCALATE (stated +50%; operator confirmed) | yes | mismatch escalates |
| 12 | 0069 | ESCALATE (1.01M, -15%; operator confirmed) | yes | |
| 13 | 0163 | REQUEST_AUTHORIZATION (L3, other account; operator INFO) | yes | rule 3 |
| 14 | 0166 | REQUEST_INFO (L3, ambiguous account; operator AUTH) | yes | rule 2 |
| 15 | 0199 | REQUEST_AUTHORIZATION (L2; operator confirmed) | no | "Not sure, please double-check" (vague) |
| 16 | 0199 | CONFIRMED | no | "isn't authorized to receive confirmations; we ask for authorization first" -> #15 was oracle noise; rule 1 holds |
| 17 | 0056 | REQUEST_AUTHORIZATION (L2, no instrument; operator INFO) | yes | rule 1 before rule 4 |
| 18 | 0067 | REQUEST_AUTHORIZATION (L2, ambiguous account; operator INFO) | yes | rule 1 before rule 2 |
| 19 | 0032 | REQUEST_AUTHORIZATION (L2, not held; operator INFO) | yes | rule 1 |
| 20 | 0070 | NOT_HELD, as_of=request date, as_of_assumed=true | yes | rule 5/6 |
| 21 | 0012 | REQUEST_AUTHORIZATION (L3, other account; operator INFO) | yes | rule 3 |
| 22 | 0120 | REQUEST_INFO (L3, ambiguous account + no instrument; operator AUTH) | yes | rule 2 |
| 23 | 0088 | CONFIRMED + pending 43,817 | yes | large pending reported |

Remaining uncertainty: exact mismatch tolerance (4%-8%), exact pending threshold (885-6,186), the 1M boundary (945,475-1,006,007), whether stated_qty should be compared to settled+pending (rule 12), and >1 instrument matches for an authorized sender (assumed INFO).
