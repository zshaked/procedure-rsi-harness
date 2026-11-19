"""Case stratification (DESIGN.md §5): (complexity, completeness) per case.

Complexity counts the resolution problems the case poses — an account or
instrument reference that resolves to zero or several entities or is absent,
a date that is relative or missing, a stated quantity that must be reconciled.
Completeness is how many of the required parameters (account, instrument,
as-of date) the email supplies at all; low completeness is where asking back
is often the right answer.

Both are computed from the email and the snapshot only — never from the reply,
and never from hidden fields — so they are available for fresh cases at
deployment time.
"""
from __future__ import annotations

import re

from ..cases.schema import Case

COMPLETENESS = ("complete", "partial", "missing")

_EXPLICIT_DATE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-[A-Z][a-z]{2}-\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"
    r"|\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}"
    r"|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2} \d{4})\b")
_RELATIVE_DATE = re.compile(r"\b(end of last month|month-end|last day of last month|yesterday)\b", re.I)
_STATED_QTY = re.compile(r"\b(records show|on our books|our figure is|we show)\b", re.I)


def has_explicit_date(body: str) -> bool:
    return bool(_EXPLICIT_DATE.search(body))


def has_relative_date(body: str) -> bool:
    return bool(_RELATIVE_DATE.search(body))


def has_stated_qty(body: str) -> bool:
    return bool(_STATED_QTY.search(body))


def bucket(case: Case) -> tuple[int, str]:
    e, snap = case.email, case.snapshot
    acct = e.mentions.get("account_text")
    inst = e.mentions.get("instrument_text")
    explicit, relative = has_explicit_date(e.body), has_relative_date(e.body)

    points = 0
    if acct is None or len(snap.resolve_account(acct)) != 1:
        points += 1
    if inst is None or len(snap.resolve_instrument(inst)) != 1:
        points += 1
    if not explicit:                       # relative or missing: must be inferred
        points += 1
    if has_stated_qty(e.body):
        points += 1
    complexity = 1 if points == 0 else 2 if points == 1 else 3

    present = sum([acct is not None, inst is not None, explicit or relative])
    completeness = COMPLETENESS[0] if present == 3 else COMPLETENESS[1] if present == 2 else COMPLETENESS[2]
    case.bucket = (complexity, completeness)
    return case.bucket
