"""Case schema and the closed snapshot interface.

A case is the triple of DESIGN.md §1: inbound email, the operator's historical
reply, and a point-in-time view of the system of record (SOR) at the moment of
that reply. The snapshot is exposed only through the closed tool vocabulary
below, so nothing downstream can depend on how a particular SOR stores things.

Nothing in this module may read hidden or gold fields. Adapters that have them
(the synthetic environment does) keep them off the Case and expose them only
through `Case.meta["_benchmark"]`, which experiments use solely to validate
their own estimators and label as benchmark-only when they do.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol

OUTCOMES = ("CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION")


@dataclass(frozen=True)
class Email:
    sender: str
    sent: str                      # ISO date
    subject: str
    body: str
    mentions: dict[str, str | None] = field(default_factory=dict)
    # Raw spans an upstream extractor returned, not normalized. Keys used here:
    # account_text, instrument_text. Absent key = extractor found nothing.


@dataclass
class ReplyFields:
    """Structured reading of a reply. Every field optional; None = not asserted."""
    outcome: str | None = None
    account_id: str | None = None
    instrument: str | None = None          # ticker or id as written in the reply
    as_of: str | None = None               # ISO date
    as_of_assumed: bool = False
    settled: int | None = None
    pending: int | None = None
    pending_date: str | None = None

    def asserted(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None and v is not False}


class Snapshot(Protocol):
    """Closed tool vocabulary over the SOR as of the reply time.

    Every method answers from state as it was at `t_reply`; `as_of` arguments
    select the position date within that state. A firm adapter implements this
    over recorded tool results; the synthetic adapter implements it over the
    environment's World.
    """

    t_reply: str

    def resolve_account(self, ref: str) -> list[str]: ...
    def resolve_instrument(self, ref: str) -> list[str]: ...
    def instrument(self, instrument_id: str) -> dict | None: ...
    def contact(self, email: str) -> dict | None: ...
    def live_entitled_accounts(self, contact_id: str, on: str) -> list[str]: ...
    def entitlement(self, contact_id: str, account_id: str, on: str) -> int: ...
    def profile(self, account_id: str) -> dict: ...
    def settled(self, account_id: str, instrument_id: str, as_of: str) -> int: ...
    def pending(self, account_id: str, instrument_id: str, as_of: str) -> tuple[int, str | None]: ...
    def is_business_day(self, date: str) -> bool: ...


@dataclass
class Case:
    case_id: str
    t: int                                 # time order within the mailbox; splits are by t
    email: Email
    reply_text: str
    snapshot: Snapshot
    reply_fields: ReplyFields | None = None   # filled by reward.fields.extract when None
    role: str | None = None                   # learning | search_validation | final_test
    bucket: tuple[int, str] | None = None     # (complexity, completeness) from complexity.buckets
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def sent_date(self) -> dt.date:
        return dt.date.fromisoformat(self.email.sent)
