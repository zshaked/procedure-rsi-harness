"""Grade every finished v3 run and apply the pre-registered decision rules (PREREG.md)."""
from __future__ import annotations

import json
import random
import statistics as st
from pathlib import Path

from bench2 import evaluate

SB = Path("/home/claude/sandboxes3")
HERE = Path(__file__).resolve().parent
ARMS = ["history", "policy_first", "spec_once", "verifier_first"]
POLS = ["Q2", "Q3", "Q4"]
CACHE = HERE / "results" / "v3_runs.json"


def grade_all() -> list[dict]:
    cache = {r["run"]: r for r in json.loads(CACHE.read_text())} if CACHE.exists() else {}
    for d in sorted(SB.iterdir()):
        if d.name in cache or not (d / "procedure.py").exists() or not (d / "NOTES.md").exists():
            continue
        pol, rest = d.name.split("_", 1)
        arm, rep = rest.rsplit("_r", 1)
        r = evaluate(pol, d)
        log = HERE / "results" / "oracle_logs_v3" / f"{d.name}.jsonl"
        cache[d.name] = {"run": d.name, "policy": pol, "arm": arm, "rep": int(rep),
                         "fresh": r["fresh"]["correct"], "final_test": r["final_test"]["correct"],
                         "questions": len(log.read_text().splitlines()) if log.exists() else 0,
                         "misses_by_rule": r["fresh"]["misses_by_rule"]}
        print("graded", d.name, cache[d.name]["fresh"], "q", cache[d.name]["questions"])
    CACHE.write_text(json.dumps(sorted(cache.values(), key=lambda r: r["run"]), indent=1))
    return list(cache.values())


def boot_diff(runs, a, b, n=10000, seed=0):
    """Bootstrap the pooled mean difference a-b, resampling runs within each policy."""
    rng = random.Random(seed)
    by = {(p, arm): [r["fresh"] for r in runs if r["policy"] == p and r["arm"] == arm] for p in POLS for arm in (a, b)}
    diffs = []
    for _ in range(n):
        da = [st.mean(rng.choices(by[(p, a)], k=len(by[(p, a)]))) for p in POLS]
        db = [st.mean(rng.choices(by[(p, b)], k=len(by[(p, b)]))) for p in POLS]
        diffs.append(st.mean(da) - st.mean(db))
    diffs.sort()
    return st.mean(diffs), diffs[int(0.025 * n)], diffs[int(0.975 * n)]


def analyze(runs: list[dict]) -> dict:
    cell = {(p, a): [r for r in runs if r["policy"] == p and r["arm"] == a] for p in POLS for a in ARMS}
    complete = all(len(v) == 3 for v in cell.values())
    mean = {a: st.mean(st.mean(r["fresh"] for r in cell[(p, a)]) for p in POLS) for a in ARMS if all(cell[(p, a)] for p in POLS)}
    q = {a: st.mean(r["questions"] for p in POLS for r in cell[(p, a)]) for a in ARMS if all(cell[(p, a)] for p in POLS)}
    per_pol = {a: {p: round(st.mean(r["fresh"] for r in cell[(p, a)]), 4) for p in POLS if cell[(p, a)]} for a in ARMS}
    out = {"complete": complete, "pooled_mean": {k: round(v, 4) for k, v in mean.items()},
           "mean_questions": {k: round(v, 1) for k, v in q.items()}, "per_policy": per_pol}
    if not complete:
        return out
    # Q1
    best = max(["policy_first", "spec_once", "verifier_first"], key=lambda a: mean[a])
    q1 = (mean[best] - mean["history"] >= 0.03) and all(per_pol[best][p] > per_pol["history"][p] for p in POLS)
    out["Q1_questions_help"] = {"best_oracle_arm": best, "gain_vs_history": round(mean[best] - mean["history"], 4), "YES": q1}
    # Q2
    res = {}
    for other in ("policy_first", "spec_once"):
        m, lo, hi = boot_diff(runs, "verifier_first", other)
        wins = sum(per_pol["verifier_first"][p] > per_pol[other][p] for p in POLS)
        res[other] = {"diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)], "policy_wins": wins}
    beat_both = all(r["diff"] >= 0.02 and r["ci95"][0] > 0 and r["policy_wins"] >= 2 for r in res.values())
    best_other = max(("policy_first", "spec_once"), key=lambda a: mean[a])
    efficient = (mean["verifier_first"] >= mean[best_other] - 0.01) and (q["verifier_first"] <= 0.7 * q[best_other])
    no = (mean["verifier_first"] <= mean[best_other] + 0.02) and not efficient
    verdict = "YES" if (beat_both or efficient) else ("NO" if no else "INCONCLUSIVE")
    out["Q2_verifier_first"] = {"vs": res, "beat_both": beat_both, "question_efficient": efficient, "VERDICT": verdict}
    return out


if __name__ == "__main__":
    runs = grade_all()
    a = analyze(runs)
    (HERE / "results" / "v3_analysis.json").write_text(json.dumps(a, indent=1))
    print(json.dumps(a, indent=1))
