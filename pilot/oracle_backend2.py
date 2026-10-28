"""Oracle backend for v2 sandboxes (v4 protocol).

- Noise schedule is keyed on (policy, replicate, question index), NOT on the sandbox/arm name,
  so every arm in replicate r faces the same flips. The schedule is published before runs
  (results/v4_noise_schedule.json).
- Noise is symmetric and uninformative: a flipped verdict carries a reason drawn from the same
  pool as a genuine one, so no phrase identifies a flip.
"""
from __future__ import annotations
import json, random, re, zlib
from pathlib import Path
from bench import grade
from bench2 import load2
from env2 import RULE_REASONS2

HERE = Path(__file__).resolve().parent
RHO = 0.05
FIELD_REASON = {"pending": "The pending amount handling isn't right.", "pending_date": "The pending settlement date isn't right.",
                "as_of_assumed": "The as-of assumption flag isn't right.", "as_of": "Wrong as-of date.",
                "settled": "The settled figure is wrong.", "account_id": "Wrong account.", "instrument_id": "Wrong security."}
GENERIC_REJECTS = list(RULE_REASONS2.values()) + list(FIELD_REASON.values())


def flips(policy: str, rep: int, idx: int) -> bool:
    return random.Random(zlib.crc32(f"{policy}|r{rep}|{idx}".encode())).random() < RHO


def ask(policy: str, sandbox: str, n_hist: int, case_id: str, resp: dict, budget: int, log_dir: str = "oracle_logs_v4") -> dict:
    m = re.search(r"_r(\d+)$", sandbox)
    rep = int(m.group(1)) if m else 0
    log = HERE / "results" / log_dir / f"{sandbox}.jsonl"
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
    idx = len(past)
    v = (not ok) if flips(policy, rep, idx) else ok
    if v:
        reason = "Looks right."
    elif ok:  # flipped to a false reject: a plausible-sounding but uninformative reason
        reason = random.Random(zlib.crc32(f"{policy}|r{rep}|{idx}|reason".encode())).choice(GENERIC_REJECTS)
    elif field == "outcome":
        reason = RULE_REASONS2[h["rule"]]
    else:
        reason = FIELD_REASON.get(field, "The details are wrong.")
    out = {"case_id": case_id, "acceptable": v, "reason": reason}
    with log.open("a") as f:
        f.write(json.dumps({**out, "response": resp, "truth": ok}) + "\n")
    out["questions_left"] = budget - idx - 1
    return out
