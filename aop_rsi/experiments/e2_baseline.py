"""E2 — where is the frontier? (DESIGN.md §11, E2)

Run a baseline policy on the search-validation cases and report, per
(complexity, completeness) bucket: floor pass rate, outcome agreement with the
historical reply, and full-field agreement (every field the reference asserts
matches). Frontier buckets are those with full-field agreement between 0.3 and
0.7 — where a group of candidates has variance and the optimizer has signal.

Agreement with the historical reply is agreement with an imperfect reference
(E0′ says how imperfect). On the synthetic environment the gold outcome is also
reported, benchmark-only, so the gap between "agrees with the operator" and
"is correct" is visible.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ..baselines import MajorityBaseline, Policy, RetrievalBaseline
from ..cases.schema import Case
from ..cases.split import by_role
from ..complexity.buckets import bucket
from ..reward.fields import agreement, extract
from ..reward.verifiable import floor

FRONTIER = (0.3, 0.7)


def evaluate(policy: Policy, cases: Sequence[Case]) -> dict:
    per: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "floor": 0, "outcome": 0, "fields": 0, "_gold": 0, "_has_gold": 0})
    for c in cases:
        b = c.bucket or bucket(c)
        ref = c.reply_fields or extract(c.reply_text)
        cand = policy(c)
        agr = agreement(cand, ref)
        row = per[b]
        row["n"] += 1
        row["floor"] += floor(cand, c.snapshot).passed
        row["outcome"] += bool(agr.get("outcome"))
        row["fields"] += bool(agr) and all(agr.values())
        if g := c.meta.get("_benchmark"):
            row["_has_gold"] += 1
            row["_gold"] += cand.outcome == g["gold"]["outcome"]
    buckets = {}
    tot = {"n": 0, "floor": 0, "outcome": 0, "fields": 0, "_gold": 0, "_has_gold": 0}
    for b, r in sorted(per.items()):
        for k in tot:
            tot[k] += r[k]
        buckets[f"{b[0]}/{b[1]}"] = _rates(r)
    return {"n": tot["n"], "overall": _rates(tot), "buckets": buckets,
            "frontier_buckets": [k for k, v in buckets.items() if FRONTIER[0] <= v["fields"] <= FRONTIER[1]]}


def _rates(r: dict) -> dict:
    n = r["n"] or 1
    out = {"n": r["n"], "floor": r["floor"] / n, "outcome": r["outcome"] / n, "fields": r["fields"] / n}
    if r["_has_gold"]:
        out["_benchmark_gold_outcome"] = r["_gold"] / r["_has_gold"]
    return out


def run(cases: Sequence[Case]) -> dict:
    learning, val = by_role(cases, "learning"), by_role(cases, "search_validation")
    for c in cases:
        bucket(c)
    return {
        "n_learning": len(learning), "n_validation": len(val),
        "majority": evaluate(MajorityBaseline(learning), val),
        "retrieval": evaluate(RetrievalBaseline(learning), val),
    }


def summarize(res: dict) -> str:
    lines = [f"E2 baseline frontier — learning {res['n_learning']}, validation {res['n_validation']}"]
    for name in ("majority", "retrieval"):
        r = res[name]; o = r["overall"]
        g = f" gold={o['_benchmark_gold_outcome']:.3f}[benchmark-only]" if "_benchmark_gold_outcome" in o else ""
        lines.append(f"  {name:9s} floor={o['floor']:.3f} outcome={o['outcome']:.3f} fields={o['fields']:.3f}{g}")
        for b, v in r["buckets"].items():
            gg = f" gold={v['_benchmark_gold_outcome']:.2f}" if "_benchmark_gold_outcome" in v else ""
            mark = " ◄ frontier" if b in r["frontier_buckets"] else ""
            lines.append(f"      {b:12s} n={v['n']:3d} floor={v['floor']:.2f} outcome={v['outcome']:.2f} fields={v['fields']:.2f}{gg}{mark}")
    return "\n".join(lines)
