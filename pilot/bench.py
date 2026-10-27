"""Histories, data roles, grader, fact floor, and the budgeted oracle."""
from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any

from env import (OUTCOMES, RULE_REASONS, Policy, Request, State, execute_policy, make_requests,
                 make_state, sample_policies)

FIELDS = ["outcome", "account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date"]

# --------------------------------------------------------------------------- reply text

_T = {
    "CONFIRMED": ["We confirm that account {account_id} holds {settled:,} units of {inst} as of {as_of}.",
                  "Confirmed: {settled:,} {inst} settled in {account_id} as of {as_of}.",
                  "Hi, confirming {account_id} position in {inst}: {settled:,} settled as of {as_of}."],
    "NOT_HELD": ["Account {account_id} does not hold {inst} as of {as_of}.",
                 "We show no settled position in {inst} for {account_id} as of {as_of}."],
    "ESCALATE": ["Thanks, we are escalating this request for review and will revert.",
                 "This has been referred to our escalations team; we'll be in touch."],
    "REQUEST_INFO": ["Could you clarify the details of your request so we can locate the position?",
                     "We need a bit more information to process this: please confirm the account, security and date."],
    "REQUEST_AUTHORIZATION": ["We are unable to share this information without authorization. Please have an authorized signatory contact us.",
                              "For security reasons, please arrange authorization before we can confirm."],
}


def render_reply(r: dict, s: State, rng: random.Random) -> str:
    inst = s.instruments[r["instrument_id"]].ticker if r.get("instrument_id") else ""
    txt = rng.choice(_T[r["outcome"]]).format(inst=inst, **{k: v for k, v in r.items() if k != "outcome"})
    if r["outcome"] in ("CONFIRMED", "NOT_HELD") and r.get("as_of_assumed"):
        txt += " As no date was given, we have used the date of your request."
    if r["outcome"] == "CONFIRMED" and r.get("pending"):
        txt += f" A further {r['pending']:,} units are pending settlement, expected {r['pending_date']}."
    return txt


_WRONG = {"CONFIRMED": ["ESCALATE"], "ESCALATE": ["CONFIRMED"], "REQUEST_AUTHORIZATION": ["CONFIRMED", "REQUEST_INFO"],
          "REQUEST_INFO": ["CONFIRMED", "REQUEST_AUTHORIZATION"], "NOT_HELD": ["REQUEST_INFO"]}


def perturb(gold: dict, q: Request, s: State, P: Policy, rng: random.Random) -> tuple[dict, str | None]:
    """A harmful operator error: wrong decision, or omitted pending. Returns (reply_struct, kind)."""
    r = dict(gold)
    if gold["outcome"] == "CONFIRMED" and gold.get("pending") and rng.random() < 0.5:
        r["pending"], r["pending_date"] = None, None
        return r, "omit_pending"
    new = rng.choice(_WRONG[gold["outcome"]])
    r["outcome"] = new
    if new == "CONFIRMED":
        # an operator who confirms anyway would state facts they looked up
        accts = s.lookup_account(q.account_ref)
        insts = s.resolve_instrument(q.instrument_ref) if q.instrument_ref else []
        if len(accts) == 1 and len(insts) == 1:
            as_of = q.as_of or q.request_date
            pos = s.get_position(accts[0]["id"], insts[0]["id"], as_of)
            if pos and pos["settled"]:
                r.update(account_id=accts[0]["id"], instrument_id=insts[0]["id"], as_of=as_of,
                         as_of_assumed=q.as_of is None, settled=pos["settled"], pending=None, pending_date=None)
                return r, "wrong_decision"
        r["outcome"] = "REQUEST_INFO"
    return r, "wrong_decision"


# --------------------------------------------------------------------------- dataset

def build(out_dir: Path, n_cases: int = 400, rho_op: float = 0.2, seed: int = 0) -> dict:
    """Write one environment with all policy instances. rho_op is total operator inconsistency;
    one third of it is harmful (decision changed), two thirds harmless (phrasing only)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    s = make_state(seed)
    policies = sample_policies(seed + 7)
    meta = {"rho_op": rho_op, "harmful_rate": rho_op / 3, "n_cases": n_cases,
            "held_out_policies": [p.name for p in policies[3:]], "policies": {}}
    for k, P in enumerate(policies):
        rng = random.Random(1000 * (seed + 1) + k)
        reqs = make_requests(s, n_cases, seed=100 + k, prefix=f"{P.name}-")
        rows = []
        for q in reqs:
            gold = execute_policy(q, s, P)
            reply, pert = gold, None
            if rng.random() < rho_op / 3:
                reply, pert = perturb({k2: v for k2, v in gold.items() if k2 != "_rule"}, q, s, P, rng)
            reply_text = render_reply(reply, s, rng)
            role = "learning" if q.t < n_cases // 2 else ("search_validation" if q.t < 3 * n_cases // 4 else "final_test")
            rows.append({
                "case_id": q.case_id, "t": q.t, "role": role,
                "request": {"from": q.from_email, "date": q.request_date, "body": q.body,
                            "fields": {"account_ref": q.account_ref, "instrument_ref": q.instrument_ref,
                                       "as_of": q.as_of, "stated_qty": q.stated_qty}},
                "reply_text": reply_text,
                "hidden": {"gold": {k2: v for k2, v in gold.items() if k2 != "_rule"}, "rule": gold["_rule"],
                           "operator_reply": {k2: v for k2, v in reply.items() if k2 != "_rule"},
                           "perturbation": pert},
            })
        (out_dir / f"{P.name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        meta["policies"][P.name] = asdict(P)
        (out_dir / f"{P.name}.policy.txt").write_text(P.render())
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def load(out_dir: Path, name: str) -> list[dict]:
    return [json.loads(l) for l in (out_dir / f"{name}.jsonl").read_text().splitlines()]


def to_request(row: dict) -> Request:
    f = row["request"]["fields"]
    return Request(row["case_id"], row["t"], row["request"]["from"], row["request"]["date"],
                   f["account_ref"], f["instrument_ref"], f["as_of"], f["stated_qty"], row["request"]["body"])


# --------------------------------------------------------------------------- grading

def grade(resp: dict | None, gold: dict) -> tuple[bool, str | None]:
    """Executable correctness. Returns (correct, first mismatching field)."""
    if not isinstance(resp, dict) or resp.get("outcome") not in OUTCOMES:
        return False, "malformed"
    if resp["outcome"] != gold["outcome"]:
        return False, "outcome"
    o = gold["outcome"]
    need = {"CONFIRMED": FIELDS[1:], "NOT_HELD": ["account_id", "instrument_id", "as_of", "as_of_assumed"],
            "ESCALATE": ["account_id", "instrument_id"]}.get(o, [])
    for f in need:
        g, r = gold.get(f), resp.get(f)
        if f == "as_of_assumed":
            g, r = bool(g), bool(r)
        if f in ("pending", "pending_date"):
            g, r = (g or None), (r or None)
        if g != r:
            return False, f
    return True, None


def floor(resp: dict, s: State) -> tuple[bool, str | None]:
    """Fact checks only: what state can establish. Never checks the business decision."""
    if not isinstance(resp, dict) or resp.get("outcome") not in OUTCOMES:
        return False, "malformed"
    aid, iid, as_of = resp.get("account_id"), resp.get("instrument_id"), resp.get("as_of")
    if aid is not None and aid not in s.accounts:
        return False, "unknown_account"
    if iid is not None and iid not in s.instruments:
        return False, "unknown_instrument"
    if resp["outcome"] == "CONFIRMED":
        if not (aid and iid and as_of):
            return False, "confirm_missing_ids"
        pos = s.get_position(aid, iid, as_of)
        if pos is None or pos["settled"] == 0:
            return False, "confirm_not_held"
        if resp.get("settled") != pos["settled"]:
            return False, "settled_mismatch"
        if resp.get("pending") and (resp["pending"] != pos["pending"] or resp.get("pending_date") != pos["pending_date"]):
            return False, "pending_mismatch"
    if resp["outcome"] == "NOT_HELD" and aid and iid and as_of:
        pos = s.get_position(aid, iid, as_of)
        if pos and pos["settled"]:
            return False, "not_held_but_held"
    return True, None


# --------------------------------------------------------------------------- oracle

class Oracle:
    """Budgeted, noisy operator. Verdict on (case, candidate response) + one-sentence reason.
    Correctness is computed by the executable policy; the verdict is flipped with prob rho."""
    SECONDS_PER_VERDICT = 60

    def __init__(self, rows: list[dict], budget_seconds: int, rho: float = 0.05, seed: int = 0):
        self.gold = {r["case_id"]: r["hidden"] for r in rows}
        self.budget = budget_seconds
        self.spent = 0
        self.rho = rho
        self.rng = random.Random(seed)
        self.log: list[dict] = []

    def remaining(self) -> int:
        return (self.budget - self.spent) // self.SECONDS_PER_VERDICT

    def verdict(self, case_id: str, resp: dict) -> dict:
        if self.spent + self.SECONDS_PER_VERDICT > self.budget:
            raise RuntimeError("oracle budget exhausted")
        self.spent += self.SECONDS_PER_VERDICT
        h = self.gold[case_id]
        ok, field = grade(resp, h["gold"])
        v = ok if self.rng.random() >= self.rho else (not ok)
        if v:
            reason = "Looks right."
        elif ok:  # noise flip: operator wrongly rejects
            reason = "Not sure this is right, please double-check."
        elif field == "outcome":
            reason = RULE_REASONS[h["rule"]]
        else:
            reason = {"pending": "The pending amount handling isn't right.",
                      "pending_date": "The pending settlement date handling isn't right.",
                      "as_of_assumed": "If you assumed the date, say so.",
                      "as_of": "Wrong as-of date.", "settled": "The settled figure is wrong."}.get(field, "The details are wrong.")
        out = {"case_id": case_id, "acceptable": v, "reason": reason}
        self.log.append(out)
        return out
