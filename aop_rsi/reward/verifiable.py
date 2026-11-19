"""Verifiable floor (DESIGN.md §4.1): facts only, checked against the snapshot.

The floor checks what state can establish — that identifiers resolve, that
asserted figures and dates match the snapshot, that the reply is internally
consistent and well-formed. It does not check the business decision (whether
to confirm, escalate, or ask), because operators make mistakes and a floor that
rewarded imitating the historical outcome class would reward imitating the
mistakes. The decision is the judge's domain, scored against the inferred
specification, not the floor's.

A floor failure means reward 0 regardless of anything a judge says.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..cases.schema import OUTCOMES, ReplyFields, Snapshot


@dataclass
class FloorResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)


def floor(fields: ReplyFields, snap: Snapshot, qty_tolerance: float = 0.0) -> FloorResult:
    fail: list[str] = []
    checked: list[str] = []

    # --- schema
    checked.append("schema")
    if fields.outcome not in OUTCOMES:
        fail.append(f"schema: outcome {fields.outcome!r} not in {OUTCOMES}")
        return FloorResult(False, fail, checked)

    # --- entity resolution
    aid = fields.account_id
    iid: str | None = None
    if aid is not None:
        checked.append("entity:account")
        if snap.resolve_account(aid) != [aid]:
            fail.append(f"entity: account {aid!r} does not resolve uniquely in snapshot")
    if fields.instrument is not None:
        checked.append("entity:instrument")
        hits = snap.resolve_instrument(fields.instrument)
        if len(hits) != 1:
            fail.append(f"entity: instrument {fields.instrument!r} resolves to {len(hits)} instruments")
        else:
            iid = hits[0]

    # --- dates
    if fields.as_of is not None:
        checked.append("date:as_of")
        try:
            d = dt.date.fromisoformat(fields.as_of)
        except ValueError:
            fail.append(f"date: as_of {fields.as_of!r} is not a date")
            d = None
        if d is not None and fields.as_of > snap.t_reply:
            fail.append(f"date: as_of {fields.as_of} is after the reply time {snap.t_reply}")
    if fields.pending_date is not None:
        checked.append("date:pending_date")
        try:
            dt.date.fromisoformat(fields.pending_date)
        except ValueError:
            fail.append(f"date: pending_date {fields.pending_date!r} is not a date")

    # --- figures (need account, instrument, as_of to look anything up)
    can_lookup = aid is not None and iid is not None and fields.as_of is not None and not any(
        f.startswith(("entity", "date: as_of")) for f in fail)
    if fields.settled is not None:
        checked.append("figure:settled")
        if not can_lookup:
            fail.append("figure: settled asserted without a resolvable account, instrument and as_of")
        else:
            truth = snap.settled(aid, iid, fields.as_of)
            if not _close(fields.settled, truth, qty_tolerance):
                fail.append(f"figure: settled {fields.settled} ≠ snapshot {truth}")
    if fields.pending is not None:
        checked.append("figure:pending")
        if not can_lookup:
            fail.append("figure: pending asserted without a resolvable account, instrument and as_of")
        else:
            p, pdate = snap.pending(aid, iid, fields.as_of)
            if not _close(fields.pending, p, qty_tolerance):
                fail.append(f"figure: pending {fields.pending} ≠ snapshot {p}")
            if fields.pending_date is not None and fields.pending_date != pdate:
                fail.append(f"figure: pending_date {fields.pending_date} ≠ snapshot {pdate}")

    # --- internal consistency
    checked.append("consistency")
    if fields.outcome == "CONFIRMED":
        if fields.settled is None:
            fail.append("consistency: CONFIRMED without a settled figure")
        elif fields.settled <= 0:
            fail.append("consistency: CONFIRMED with settled ≤ 0")
    if fields.outcome == "NOT_HELD":
        if fields.settled not in (None, 0):
            fail.append("consistency: NOT_HELD with a positive settled figure")
        if can_lookup and snap.settled(aid, iid, fields.as_of) > 0:
            fail.append("consistency: NOT_HELD but snapshot shows a settled position")

    return FloorResult(not fail, fail, checked)


def _close(a: int, b: int, tol: float) -> bool:
    if tol <= 0:
        return a == b
    return abs(a - b) <= tol * max(abs(b), 1)
