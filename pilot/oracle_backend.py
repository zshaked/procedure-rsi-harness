"""Oracle backend for the sandbox CLI: budget persisted per policy+sandbox in a log file."""
from __future__ import annotations

import json
import os
from pathlib import Path

from bench import Oracle, load

HERE = Path(__file__).resolve().parent


def ask(policy: str, case_id: str, resp: dict, budget: int) -> dict:
    sandbox = Path(os.getcwd()).name
    log = HERE / "results" / "oracle_logs" / f"{policy}__{sandbox}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    past = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    if len(past) >= budget:
        return {"error": f"budget exhausted ({budget} questions used)"}
    rows = [r for r in load(HERE / "data", policy) if r["role"] == "learning"]
    if case_id not in {r["case_id"] for r in rows}:
        return {"error": "unknown case_id (only history cases may be asked about)"}
    o = Oracle(rows, budget_seconds=60 * budget, rho=0.05, seed=len(past) + 17)
    out = o.verdict(case_id, resp)
    with log.open("a") as f:
        f.write(json.dumps({**out, "response": resp}) + "\n")
    out["questions_left"] = budget - len(past) - 1
    return out
