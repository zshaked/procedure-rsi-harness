"""Run E0′, E1, E2 on a case set and write results.

    python -m aop_rsi.experiments.run_all --env2 Q2            # synthetic environment
    python -m aop_rsi.experiments.run_all --firm export.jsonl  # firm export (see cases/adapters/firm.py)

Results go to aop_rsi/experiments/results/<name>.json and a summary is printed.
Per DESIGN.md §11: if E1 fails, stop; if E0′'s bound is high, fix the labeling
protocol before building a judge; E2's frontier buckets are where E3 samples.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..cases.split import assign_roles
from ..reward.fields import extract
from . import e0_noise_floor, e1_snapshot, e2_baseline

RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--env2", metavar="POLICY", help="synthetic policy name, e.g. Q2")
    g.add_argument("--firm", metavar="JSONL", help="firm export path")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--rho", type=float, default=0.2, help="operator inconsistency (env2 only)")
    a = ap.parse_args()

    if a.env2:
        from ..cases.adapters.env2 import load_cases
        cases, name = load_cases(a.env2, n=a.n, rho_op=a.rho), f"env2_{a.env2}"
    else:
        from ..cases.adapters.firm import load_cases
        cases, name = load_cases(a.firm), Path(a.firm).stem

    cases = assign_roles(cases)
    for c in cases:
        c.reply_fields = extract(c.reply_text)

    res = {"source": name, "n": len(cases),
           "e0_noise_floor": e0_noise_floor.run(cases),
           "e1_snapshot": e1_snapshot.run(cases),
           "e2_baseline": e2_baseline.run(cases)}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(res, indent=1, default=str))
    print(e0_noise_floor.summarize(res["e0_noise_floor"]))
    print(e1_snapshot.summarize(res["e1_snapshot"]))
    print(e2_baseline.summarize(res["e2_baseline"]))
    print(f"\nwritten: {RESULTS / f'{name}.json'}")


if __name__ == "__main__":
    main()
