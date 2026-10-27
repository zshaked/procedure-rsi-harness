"""Grade a sandbox's procedure.py (and verifier.py, if present) against the hidden executable policy.

Usage: python3 eval_procedure.py <policy> <sandbox_dir>
"""
from __future__ import annotations

import collections
import importlib.util
import json
import random
import sys
from pathlib import Path

from bench import grade, load

HERE = Path(__file__).resolve().parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mutate(resp: dict, rng: random.Random) -> dict:
    """Plausible wrong variants of a response, to test a verifier on negatives too."""
    r = dict(resp)
    choice = rng.choice(["outcome", "pending", "assumed"])
    if choice == "outcome":
        r["outcome"] = rng.choice([o for o in ["CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"] if o != r["outcome"]])
    elif choice == "pending" and r.get("outcome") == "CONFIRMED":
        r["pending"], r["pending_date"] = (None, None) if r.get("pending") else (123, "2026-06-30")
    else:
        r["as_of_assumed"] = not r.get("as_of_assumed")
    return r


def evaluate(policy: str, sandbox: Path) -> dict:
    sys.path.insert(0, str(sandbox))
    tools = _load(sandbox / "tools.py", "tools_" + sandbox.name)
    proc = _load(sandbox / "procedure.py", "proc_" + sandbox.name)
    ver = _load(sandbox / "verifier.py", "ver_" + sandbox.name) if (sandbox / "verifier.py").exists() else None
    rows = load(HERE / "data", policy)
    res = {"policy": policy, "arm": sandbox.name}
    rng = random.Random(0)
    for role in ("search_validation", "final_test"):
        test = [r for r in rows if r["role"] == role]
        ok, errs, by_rule = 0, collections.Counter(), collections.Counter()
        vstats = collections.Counter()
        for r in test:
            try:
                out = proc.respond(r["request"], tools)
            except Exception as e:  # a crash is a wrong answer
                out = {"outcome": "ERROR"}
            g, field = grade(out, r["hidden"]["gold"])
            ok += g
            if not g:
                errs[field] += 1
                by_rule[r["hidden"]["rule"]] += 1
            if ver is not None and role == "final_test":
                for cand in (out, mutate(out, rng) if isinstance(out, dict) and "outcome" in out else out):
                    truth = grade(cand, r["hidden"]["gold"])[0]
                    try:
                        v = ver.verify(r["request"], cand, tools)
                        v = bool(v[0] if isinstance(v, (tuple, list)) else v)
                    except Exception:
                        v = False
                    vstats["n"] += 1
                    vstats["agree"] += v == truth
                    vstats["false_accept"] += v and not truth
                    vstats["false_reject"] += (not v) and truth
                    vstats["true_wrong"] += not truth
        res[role] = {"correct": round(ok / len(test), 3), "n": len(test),
                     "errors_by_field": dict(errs), "errors_by_rule": dict(by_rule)}
        if vstats:
            n = vstats["n"]
            res["verifier"] = {"agreement": round(vstats["agree"] / n, 3), "n": n,
                               "false_accept_rate_on_wrong": round(vstats["false_accept"] / max(1, vstats["true_wrong"]), 3),
                               "false_reject_rate_on_right": round(vstats["false_reject"] / max(1, n - vstats["true_wrong"]), 3)}
    log = HERE / "results" / "oracle_logs" / f"{policy}__{sandbox.name}.jsonl"
    res["oracle_questions_used"] = len(log.read_text().splitlines()) if log.exists() else 0
    return res


if __name__ == "__main__":
    print(json.dumps(evaluate(sys.argv[1], Path(sys.argv[2]).resolve()), indent=2))
