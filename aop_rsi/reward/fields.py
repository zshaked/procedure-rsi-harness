"""Field extraction: reply text → ReplyFields.

This is the core of the field-level judge. Comparison happens on structured
fields, never on reply prose: two replies agree if their asserted outcome,
entities, figures and dates agree, whatever the wording.

`RegexFieldExtractor` handles the synthetic environment's reply templates and
the common shapes of real confirmation replies (identifiers, "as of" dates,
quantities followed by a ticker). A firm deployment replaces it with an
LLM-backed `FieldExtractor` of the same interface; the extractor's own accuracy
is then measured on the operator-verified regression set like any other judge
component (DESIGN.md §4.2).
"""
from __future__ import annotations

import re
from typing import Protocol

from ..cases.schema import ReplyFields

_DATE = r"(\d{4}-\d{2}-\d{2})"
_NUM = r"([\d][\d,]*)"
_TICK = r"([A-Z]{3,4})"


class FieldExtractor(Protocol):
    def __call__(self, reply_text: str) -> ReplyFields: ...


class RegexFieldExtractor:
    _OUTCOME_CUES = [
        ("REQUEST_AUTHORIZATION", re.compile(r"\bauthori[sz]ation\b", re.I)),
        ("REQUEST_INFO", re.compile(r"\b(clarify|more information|please confirm the account)\b", re.I)),
        ("ESCALATE", re.compile(r"\b(referring this request|escalation|escalations team|for review)\b", re.I)),
        ("NOT_HELD", re.compile(r"\b(does not hold|no settled position|not held)\b", re.I)),
        ("CONFIRMED", re.compile(r"\b(we confirm|confirmed|confirming)\b", re.I)),
    ]
    _ACCOUNT = re.compile(r"\b(ACC-\d+)\b")
    _AS_OF = re.compile(r"\bas (?:of|at) " + _DATE)
    _ASSUMED = re.compile(r"no date was given|used the date of your email", re.I)
    _PENDING = re.compile(r"further " + _NUM + r" (?:are |units )?pending[^.]*?expected " + _DATE, re.I)
    _SETTLED_PATTERNS = [
        re.compile(r"holds " + _NUM + r" " + _TICK + r" as of"),                 # holds 1,200 ABC as of
        re.compile(r":\s*" + _NUM + r" " + _TICK + r" settled in"),               # Confirmed: 1,200 ABC settled in
        re.compile(r"position in " + _TICK + r":\s*" + _NUM + r" settled"),       # position in ABC: 1,200 settled
        re.compile(r"\b" + _NUM + r" (?:units|shares) of " + _TICK),             # 1,200 units of ABC
    ]
    _INST_PATTERNS = [
        re.compile(r"does not hold " + _TICK + r" as of"),
        re.compile(r"no settled position in " + _TICK + r" for"),
    ]

    def __call__(self, reply_text: str) -> ReplyFields:
        f = ReplyFields()
        txt = " ".join(reply_text.split())
        for name, pat in self._OUTCOME_CUES:
            if pat.search(txt):
                f.outcome = name
                break
        if m := self._ACCOUNT.search(txt):
            f.account_id = m.group(1)
        if m := self._AS_OF.search(txt):
            f.as_of = m.group(1)
        f.as_of_assumed = bool(self._ASSUMED.search(txt))
        for pat in self._SETTLED_PATTERNS:
            if m := pat.search(txt):
                g = m.groups()
                num, tick = (g[0], g[1]) if g[0][0].isdigit() else (g[1], g[0])
                f.settled, f.instrument = int(num.replace(",", "")), tick
                break
        if f.instrument is None:
            for pat in self._INST_PATTERNS:
                if m := pat.search(txt):
                    f.instrument = m.group(1)
                    break
        if m := self._PENDING.search(txt):
            f.pending, f.pending_date = int(m.group(1).replace(",", "")), m.group(2)
        return f


_default = RegexFieldExtractor()


def extract(reply_text: str, extractor: FieldExtractor | None = None) -> ReplyFields:
    return (extractor or _default)(reply_text)


# Which fields a reply of each outcome class is expected to assert. Used by
# field-level agreement: only fields the reference asserts are compared.
REQUIRED = {
    "CONFIRMED": ("outcome", "account_id", "instrument", "as_of", "settled"),
    "NOT_HELD": ("outcome", "account_id", "instrument", "as_of"),
    "ESCALATE": ("outcome",),
    "REQUEST_INFO": ("outcome",),
    "REQUEST_AUTHORIZATION": ("outcome",),
}


def agreement(candidate: ReplyFields, reference: ReplyFields) -> dict[str, bool]:
    """Per-field agreement on the fields the reference's outcome class requires,
    plus `pending` when the reference asserts it. Keys absent = not compared."""
    out: dict[str, bool] = {}
    if reference.outcome is None:
        return out
    for k in REQUIRED.get(reference.outcome, ("outcome",)):
        out[k] = getattr(candidate, k) == getattr(reference, k)
    if reference.pending is not None:
        out["pending"] = candidate.pending == reference.pending and candidate.pending_date == reference.pending_date
    return out
