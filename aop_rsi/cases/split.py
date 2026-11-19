"""Four data roles (DESIGN.md §7), assigned by time order.

Historical cases take three of the four roles. The fourth, calibration, is not
a slice of history: it is operator answers on the *current* policy's fresh
outputs, re-drawn after every accepted change, and lives with the judge.

    learning            oldest fraction      curation, policy updates, selection
    search_validation   middle fraction      the gate only; reported as validation, never test
    final_test          newest fraction      touched once, after the system is frozen

Time-ordering is kept so that drift is visible rather than averaged away.
"""
from __future__ import annotations

from collections.abc import Sequence

from .schema import Case

ROLES = ("learning", "search_validation", "final_test")
DEFAULT_FRACTIONS = (0.5, 0.25, 0.25)


def assign_roles(cases: Sequence[Case], fractions: tuple[float, float, float] = DEFAULT_FRACTIONS) -> list[Case]:
    """Assign roles in place by `t`; returns the cases sorted by `t`."""
    if abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("fractions must sum to 1")
    ordered = sorted(cases, key=lambda c: c.t)
    n = len(ordered)
    cut1 = int(n * fractions[0])
    cut2 = cut1 + int(n * fractions[1])
    for i, c in enumerate(ordered):
        c.role = ROLES[0] if i < cut1 else ROLES[1] if i < cut2 else ROLES[2]
    return ordered


def by_role(cases: Sequence[Case], role: str) -> list[Case]:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; one of {ROLES}")
    return [c for c in cases if c.role == role]
