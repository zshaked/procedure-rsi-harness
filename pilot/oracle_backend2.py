"""Oracle backend for v2 sandboxes: verdicts on history or unlabeled requests, budget per sandbox."""
from __future__ import annotations
import json, random, zlib
from pathlib import Path
from bench import grade
from bench2 import load2
from env2 import RULE_REASONS2

HERE = Path(__file__).resolve().parent
FIELD_REASON = {"pending": "The pending amount handling isn't right.", "pending_date": "The pending settlement date isn't right.",
                "as_of_assumed": "The as-of assumption flag isn't right.", "as_of": "Wrong as-of date.",
                "settled": "The settled figure is wrong.", "account_id": "Wrong account.", "instrument_id": "Wrong security."}


def ask(policy: str, sandbox: str, n_hist: int, case_id: str, resp: dict, budget: int) -> dict:
    log = HERE / "results" / "oracle_logs_v3" / f"{sandbox}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    past = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    if len(past) >= budget:
        return {"error": f"budget exhausted ({budget} questions used)"}
    rows = {r["case_id"]: r for r in load2(policy) if r["role"] == "learning"}
    if case_id not in rows:
        return {"error": "unknown case_id (ask about history or unlabeled case_ids only)"}
    if not isinstance(resp, dict) or "outcome" not in resp:
        return {"error": "response must be a JSON object with an 'outcome' (not counted)"}
    h = rows[case_id]["hidden"]
    ok, field = grade(resp, h["gold"])
    rng = random.Random(zlib.crc32(f"{sandbox}|{len(past)}".encode()))
    v = ok if rng.random() >= 0.05 else (not ok)
    if v:
        reason = "Looks right."
    elif ok:
        reason = "Not sure this is right, please double-check."
    elif field == "outcome":
        reason = RULE_REASONS2[h["rule"]]
    else:
        reason = FIELD_REASON.get(field, "The details are wrong.")
    out = {"case_id": case_id, "acceptable": v, "reason": reason}
    with log.open("a") as f:
        f.write(json.dumps({**out, "response": resp}) + "\n")
    out["questions_left"] = budget - len(past) - 1
    return out
