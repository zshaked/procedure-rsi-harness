"""E1 — is the snapshot point-in-time? (DESIGN.md §11, E1)

Two checks, both from the historical reply and the snapshot only:

1. Reconciliation. For every reply that asserts facts (identifiers, figures,
   dates), run the verifiable floor against the snapshot. A point-in-time
   snapshot reconciles with what the operator wrote at the time; a current-state
   snapshot does not, because positions moved after the reply.
2. Movement. For replies that assert a position as of a date, compare the
   snapshot's figure as of that date with its figure as of the reply time. If
   the two are *never* different, the snapshot almost certainly is not
   point-in-time and is just repeating current state under every date.

If reconciliation is low, nothing downstream is valid (the floor would score
correct replies as wrong). The environment should reconcile at ~100%.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ..cases.schema import Case
from ..reward.fields import extract
from ..reward.verifiable import floor


def run(cases: Sequence[Case]) -> dict:
    asserting = passed = 0
    fail_kinds: Counter = Counter()
    failures: list[dict] = []
    moved = dated = 0
    for c in cases:
        f = c.reply_fields or extract(c.reply_text)
        if not f.asserted() or f.outcome not in ("CONFIRMED", "NOT_HELD"):
            continue
        asserting += 1
        r = floor(f, c.snapshot)
        if r.passed:
            passed += 1
        else:
            for x in r.failures:
                fail_kinds[x.split(":")[0]] += 1
            failures.append({"case_id": c.case_id, "failures": r.failures})
        if f.account_id and f.instrument and f.as_of:
            hits = c.snapshot.resolve_instrument(f.instrument)
            if len(hits) == 1 and c.snapshot.resolve_account(f.account_id) == [f.account_id]:
                dated += 1
                if c.snapshot.settled(f.account_id, hits[0], f.as_of) != c.snapshot.settled(f.account_id, hits[0], c.snapshot.t_reply):
                    moved += 1
    return {
        "n_cases": len(cases),
        "fact_asserting_replies": asserting,
        "reconciled": passed,
        "reconciliation_rate": passed / asserting if asserting else None,
        "failure_kinds": dict(fail_kinds),
        "failures": failures[:10],
        "dated_position_replies": dated,
        "position_moved_between_as_of_and_reply": moved,
        "movement_rate": moved / dated if dated else None,
        "verdict": _verdict(passed / asserting if asserting else None, moved / dated if dated else None),
    }


def _verdict(recon: float | None, moved: float | None) -> str:
    if recon is None:
        return "no fact-asserting replies; cannot assess"
    if recon < 0.9:
        return "FAIL: snapshot does not reconcile with historical replies; fix the export before anything else"
    if moved is not None and moved == 0.0:
        return "SUSPECT: positions never differ between as-of and reply time; snapshot may be current-state, not point-in-time"
    return "PASS: snapshot reconciles and shows movement between as-of and reply time"


def summarize(res: dict) -> str:
    rr = res["reconciliation_rate"]; mv = res["movement_rate"]
    return (f"E1 snapshot validity — {res['fact_asserting_replies']} fact-asserting replies of {res['n_cases']}\n"
            f"  reconciliation {'—' if rr is None else f'{rr:.3f}'} ({res['reconciled']}/{res['fact_asserting_replies']}); "
            f"failure kinds {res['failure_kinds'] or '{}'}\n"
            f"  position moved between as-of and reply time in {'—' if mv is None else f'{mv:.3f}'} of {res['dated_position_replies']} dated replies\n"
            f"  → {res['verdict']}")
