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
CONF = "Q1"
ARMS = ["random", "default", "default_robust", "disciplined"]
PRIOR_HANDLED = {"legal_hold", "asof_future"}
CACHE = HERE / "results" / "v4_runs.json"


def grade_all() -> list[dict]:
    cache = {r["run"]: r for r in json.loads(CACHE.read_text())} if CACHE.exists() else {}
    rule_of = {p: {r["case_id"]: r["hidden"]["rule"] for r in load2(p)} for p in POLS + [CONF]}
    for d in sorted(SB.iterdir()):
        if d.name in cache or not (d / "procedure.py").exists() or not (d / "NOTES.md").exists():
            continue
        pol, rest = d.name.split("_", 1)
        arm, rep = rest.rsplit("_r", 1)
        r = evaluate(pol, d)
        log = HERE / "results" / "oracle_logs_v4" / f"{d.name}.jsonl"
        qs = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        cache[d.name] = {"run": d.name, "policy": pol, "arm": arm, "rep": int(rep),
                         "fresh": r["fresh"]["correct"], "final_test": r["final_test"]["correct"], "questions": len(qs),
                         "flips_seen": sum(q.get("truth") != q["acceptable"] for q in qs), "model": "sonnet (Agent model=sonnet)",
                         "misses_by_rule": r["fresh"]["misses_by_rule"]}
        print("graded", d.name, cache[d.name]["fresh"], "q", len(qs))
    CACHE.write_text(json.dumps(sorted(cache.values(), key=lambda r: r["run"]), indent=1))
    return list(cache.values())


def boot(runs, a, b, n=10000, seed=0):
    rng = random.Random(seed)
    by = {(p, x): [r["fresh"] for r in runs if r["policy"] == p and r["arm"] == x] for p in POLS for x in (a, b)}
    ds = sorted(st.mean(st.mean(rng.choices(by[(p, a)], k=len(by[(p, a)]))) for p in POLS)
                - st.mean(st.mean(rng.choices(by[(p, b)], k=len(by[(p, b)]))) for p in POLS) for _ in range(n))
    return round(st.mean(ds), 4), round(ds[int(0.025 * n)], 4), round(ds[int(0.975 * n)], 4)


def perm_p(runs, a, b, n=10000, seed=1):
    """One-sided permutation test (a > b), permuting arm labels within each policy."""
    rng = random.Random(seed)
    by = {p: [(r["fresh"], r["arm"]) for r in runs if r["policy"] == p and r["arm"] in (a, b)] for p in POLS}
    def stat(groups):
        return st.mean(st.mean(v for v, x in g if x == a) - st.mean(v for v, x in g if x == b) for g in groups)
    obs = stat(by.values()); cnt = 0
    for _ in range(n):
        groups = []
        for g in by.values():
            labels = [x for _, x in g]; rng.shuffle(labels)
            groups.append([(v, l) for (v, _), l in zip(g, labels)])
        cnt += stat(groups) >= obs
    return round(obs, 4), round((cnt + 1) / (n + 1), 4)


def analyze(runs):
    cell = {(p, a): [r for r in runs if r["policy"] == p and r["arm"] == a] for p in POLS for a in ARMS}
    need = {"default": 6, "disciplined": 6, "random": 3, "default_robust": 3}
    out = {"complete": all(len(cell[(p, a)]) >= need[a] for p in POLS for a in ARMS),
           "n_runs": {a: {p: len(cell[(p, a)]) for p in POLS} for a in ARMS}}
    out["per_policy"] = {a: {p: round(st.mean(r["fresh"] for r in cell[(p, a)]), 4) for p in POLS if cell[(p, a)]} for a in ARMS}
    out["pooled_mean"] = {a: round(st.mean(out["per_policy"][a].values()), 4) for a in ARMS if len(out["per_policy"][a]) == 3}
    conf = {a: [r["fresh"] for r in runs if r["policy"] == CONF and r["arm"] == a] for a in ("default", "disciplined")}
    out["Q1_confirmatory"] = {a: (round(st.mean(v), 4) if v else None) for a, v in conf.items()}
    out["voided"] = [r["run"] for r in runs if r.get("voided")]
    if not out["complete"]:
        return out
    wins = lambda a, b: sum(out["per_policy"][a][p] > out["per_policy"][b][p] for p in POLS)
    d_r, p_r = perm_p(runs, "default", "random"); d_d, p_d = perm_p(runs, "disciplined", "default")
    out["S1_selection_matters"] = {"default_minus_random": d_r, "p": p_r, "ci": boot(runs, "default", "random"),
                                   "YES": d_r >= 0.03 and p_r < 0.05, "random_ge_default": d_r <= 0}
    s2 = d_d >= 0.03 and p_d < 0.05 and wins("disciplined", "default") >= 2
    q1_contra = all(conf.values()) and (st.mean(conf["disciplined"]) <= st.mean(conf["default"]) - 0.03)
    out["S2_disciplined_beats_default"] = {"diff": d_d, "p": p_d, "ci": boot(runs, "disciplined", "default"),
                                            "wins": wins("disciplined", "default"), "YES": s2, "Q1_contradicts": q1_contra}
    out["S3_attribution_exploratory"] = {"robust_minus_default": boot(runs, "default_robust", "default"),
                                         "disciplined_minus_robust": boot(runs, "disciplined", "default_robust")}
    out["VERDICT"] = ("IN_SAMPLE_ONLY" if (s2 and q1_contra) else "YES") if s2 else "NO"
    if out["S1_selection_matters"]["random_ge_default"]:
        out["VERDICT"] += " (S1: random >= default; selection irrelevant at this budget)"
    return out


if __name__ == "__main__":
    runs = grade_all()
    a = analyze(runs)
    (HERE / "results" / "v4_analysis.json").write_text(json.dumps(a, indent=1))
    print(json.dumps(a, indent=1))
