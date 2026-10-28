"""Grade v4 runs and apply PREREG_v4.md decision rules. Reuses v3 policy_first runs as 'default'."""
from __future__ import annotations

import collections
import json
import random
import statistics as st
from pathlib import Path

from bench2 import evaluate, load2

HERE = Path(__file__).resolve().parent
SB = Path("/home/claude/sandboxes4")
POLS = ["Q2", "Q3", "Q4"]
ARMS = ["random", "default", "default_robust", "disciplined"]
PRIOR_HANDLED = {"legal_hold", "asof_future"}
CACHE = HERE / "results" / "v4_runs.json"


def grade_all() -> list[dict]:
    cache = {r["run"]: r for r in json.loads(CACHE.read_text())} if CACHE.exists() else {}
    for r in json.loads((HERE / "results" / "v3_runs.json").read_text()):
        if r["arm"] == "policy_first":
            cache[r["run"]] = {**r, "arm": "default"}
    rule_of = {p: {r["case_id"]: r["hidden"]["rule"] for r in load2(p)} for p in POLS}
    for d in sorted(SB.iterdir()):
        if d.name in cache or not (d / "procedure.py").exists() or not (d / "NOTES.md").exists():
            continue
        pol, rest = d.name.split("_", 1)
        arm, rep = rest.rsplit("_r", 1)
        r = evaluate(pol, d)
        log = HERE / "results" / "oracle_logs_v3" / f"{d.name}.jsonl"
        qs = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        cache[d.name] = {"run": d.name, "policy": pol, "arm": arm, "rep": int(rep),
                         "fresh": r["fresh"]["correct"], "final_test": r["final_test"]["correct"], "questions": len(qs),
                         "q_prior_handled": sum(rule_of[pol].get(q["case_id"]) in PRIOR_HANDLED for q in qs),
                         "misses_by_rule": r["fresh"]["misses_by_rule"]}
        print("graded", d.name, cache[d.name]["fresh"], "q", len(qs))
    CACHE.write_text(json.dumps(sorted(cache.values(), key=lambda r: r["run"]), indent=1))
    return list(cache.values())


def boot(runs, a, b, n=10000, seed=0):
    rng = random.Random(seed)
    by = {(p, x): [r["fresh"] for r in runs if r["policy"] == p and r["arm"] == x] for p in POLS for x in (a, b)}
    ds = sorted(st.mean(st.mean(rng.choices(by[(p, a)], k=3)) for p in POLS) - st.mean(st.mean(rng.choices(by[(p, b)], k=3)) for p in POLS) for _ in range(n))
    return round(st.mean(ds), 4), round(ds[int(0.025 * n)], 4), round(ds[int(0.975 * n)], 4)


def analyze(runs):
    cell = {(p, a): [r for r in runs if r["policy"] == p and r["arm"] == a] for p in POLS for a in ARMS}
    out = {"complete": all(len(v) == 3 for v in cell.values())}
    out["per_policy"] = {a: {p: round(st.mean(r["fresh"] for r in cell[(p, a)]), 4) for p in POLS if cell[(p, a)]} for a in ARMS}
    out["pooled_mean"] = {a: round(st.mean(out["per_policy"][a].values()), 4) for a in ARMS if len(out["per_policy"][a]) == 3}
    out["mean_q_prior_handled"] = {a: round(st.mean(r.get("q_prior_handled", 0) for p in POLS for r in cell[(p, a)]), 1) for a in ARMS if all(cell[(p, a)] for p in POLS)}
    if not out["complete"]:
        return out
    wins = lambda a, b: sum(out["per_policy"][a][p] > out["per_policy"][b][p] for p in POLS)
    d_r = boot(runs, "default", "random"); d_d = boot(runs, "disciplined", "default")
    r_d = boot(runs, "default_robust", "default"); d_rb = boot(runs, "disciplined", "default_robust")
    out["S1_selection_matters"] = {"default_minus_random": d_r, "YES": d_r[0] >= 0.03 and d_r[1] > 0, "random_ge_default": d_r[0] <= 0}
    s2 = d_d[0] >= 0.03 and d_d[1] > 0 and wins("disciplined", "default") >= 2
    out["S2_disciplined_beats_default"] = {"diff_ci": d_d, "wins": wins("disciplined", "default"), "YES": s2}
    fallback = (not s2) and r_d[0] >= 0.02 and r_d[1] > 0
    out["S3_attribution"] = {"robust_minus_default": r_d, "disciplined_minus_robust": d_rb, "noise_handling_alone": fallback}
    out["VERDICT"] = "YES" if s2 else ("NOISE_HANDLING_ONLY" if fallback else "NO")
    return out


if __name__ == "__main__":
    runs = grade_all()
    a = analyze(runs)
    (HERE / "results" / "v4_analysis.json").write_text(json.dumps(a, indent=1))
    print(json.dumps(a, indent=1))
