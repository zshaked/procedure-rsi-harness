# Rules (procedure.py)
Order: resolve account (exactly one hit from mention, else REQUEST_INFO; ambiguous names -> INFO even if sender owns one) -> authorization -> instrument -> date -> flags -> figures.
- Auth: sender must be a known contact, email domain in the account profile's domains, and hold an entitlement on that account with level>=3 and expires>=sent. Otherwise REQUEST_AUTHORIZATION (checked before instrument/date problems).
- Instrument unresolved, or date missing / non-business day (weekend, holiday) / after sent -> REQUEST_INFO. No assumed dates (as_of_assumed always false).
- Dates: M/D/Y, ISO, d-Mon-Y, "yesterday", month-end phrases (last day of previous month, relative to sent).
- legal_hold or no_email_confirm -> ESCALATE (after date checks; untested with a valid case).
- settled = sum of ledger qty over all sub-accounts dated <= as_of, entries before a split date x ratio when split date <= as_of. Do not use get_position_summary. Zero or no ledger -> NOT_HELD.
- pending = sum of matched instructions with settle_date > as_of; pending_date = latest.

# Oracle (15 used)
1 Q1-0121 split-adjusted CONFIRMED: yes. 2 Q1-0128 pre-split date + pending: yes. 3 Q1-0134 net zero NOT_HELD: yes. 4 Q1-0025 weekend month-end rolled back: no (ask for date) -> INFO. 5 Q1-0048 no date, assumed previous business day: no -> INFO. 6 Q1-0092 "yesterday": yes. 7-8 Q1-0064, Q1-0111 ESCALATE: no, both had invalid/missing dates -> date checks precede ESCALATE (moved it). 9 Q1-0195 AUTH over a future date (expired entitlement): yes. 10 Q1-0005 AUTH: no ("settled figure wrong", confusing; kept AUTH). 11 Q1-0028 empty ledger NOT_HELD: yes. 12 Q1-0080 INFO for unentitled sender: no, "authorization needed". 13 Q1-0116 CONFIRMED by disambiguating via sender: no -> ambiguous -> INFO. 14 Q1-0112 two pendings: yes. 15 Q1-0019 NOT_HELD: yes (history reply was a mistake).

# Unsure
ESCALATE triggers and whether no_email_confirm also means ESCALATE; histories Q1-0005 and Q1-0022 (INFO where I say AUTH; likely operator errors); as_of_assumed never true; level threshold inferred only from histories.
