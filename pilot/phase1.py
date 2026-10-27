"""Phase 1: LLM-free calibration runs.

- majority:  most common outcome in the learning histories (outcome accuracy only)
- operator:  the historical operator replies themselves, graded against the hidden policy
- tree:      decision tree on *perfect* hand-built features (what to look up is given to it),
             trained on the operator decisions in the learning histories. This is the kill test
             for the benchmark: if it recovers the policy, the decision logic is too easy and any
             LLM result would be uninformative.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text

from bench import grade, load, to_request
from env import make_state, sample_policies

D = Path("data")
S = make_state(0)
FEATS = ["auth", "dom_match", "n_acct", "owns", "inst_given", "n_inst", "asof_given", "held",
         "settled_k", "pending", "stated_given", "rel_settled", "rel_total"]


def features(row: dict) -> tuple[list[float], dict]:
    q = to_request(row)
    c = S.get_contact(q.from_email)
    accts = S.lookup_account(q.account_ref)
    acct = accts[0] if len(accts) == 1 else None
    dom = q.from_email.split("@")[1]
    ref_acct = acct or (S.accounts[c["account_id"]].__dict__ if c else None)
    insts = S.resolve_instrument(q.instrument_ref) if q.instrument_ref else []
    inst = insts[0] if len(insts) == 1 else None
    as_of = q.as_of or q.request_date
    pos = S.get_position(acct["id"], inst["id"], as_of) if (acct and inst) else None
    settled = pos["settled"] if pos else 0
    pending = pos["pending"] if pos else 0
    rel_s = abs(q.stated_qty - settled) / settled if (q.stated_qty is not None and settled) else -1
    tot = settled + pending
    rel_t = abs(q.stated_qty - tot) / tot if (q.stated_qty is not None and tot) else -1
    f = [c["auth_level"] if c else 0, float(ref_acct is not None and dom == ref_acct["domain"]),
         len(accts), float(bool(c and acct and c["account_id"] == acct["id"])),
         float(q.instrument_ref is not None), len(insts), float(q.as_of is not None), float(settled > 0),
         settled / 1000, pending, float(q.stated_qty is not None), rel_s, rel_t]
    facts = {"account_id": acct["id"] if acct else None, "instrument_id": inst["id"] if inst else None,
             "as_of": as_of, "as_of_assumed": q.as_of is None, "settled": settled or None,
             "pending": pending or None, "pending_date": pos["pending_date"] if pos and pending else None}
    return f, facts


def build_response(outcome: str, facts: dict, report_pending: bool) -> dict:
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None, "as_of_assumed": False,
         "settled": None, "pending": None, "pending_date": None}
    if outcome in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        r.update(account_id=facts["account_id"], instrument_id=facts["instrument_id"])
    if outcome in ("CONFIRMED", "NOT_HELD"):
        r.update(as_of=facts["as_of"], as_of_assumed=facts["as_of_assumed"])
    if outcome == "CONFIRMED":
        r["settled"] = facts["settled"]
        if report_pending and facts["pending"]:
            r.update(pending=facts["pending"], pending_date=facts["pending_date"])
    return r


def run(n_train: int, name: str, seed: int = 0) -> dict:
    rows = load(D, name)
    learn = [r for r in rows if r["role"] == "learning"][:n_train]
    test = [r for r in rows if r["role"] == "final_test"]
    Xl, Fl = zip(*(features(r) for r in learn))
    yl = [r["hidden"]["operator_reply"]["outcome"] for r in learn]
    tree = DecisionTreeClassifier(min_samples_leaf=2, random_state=seed).fit(np.array(Xl), yl)
    # pending-reporting decision, learned from confirmed operator replies that had pending available
    pl = [(x, bool(r["hidden"]["operator_reply"].get("pending"))) for x, r, f in zip(Xl, learn, Fl)
          if r["hidden"]["operator_reply"]["outcome"] == "CONFIRMED" and f["pending"]]
    ptree = None
    if pl and len({y for _, y in pl}) > 1:
        ptree = DecisionTreeClassifier(min_samples_leaf=2, random_state=seed).fit(np.array([x for x, _ in pl]), [y for _, y in pl])
    default_p = (sum(y for _, y in pl) / len(pl) >= 0.5) if pl else True
    maj = collections.Counter(yl).most_common(1)[0][0]
    res = collections.Counter()
    errs = collections.Counter()
    for r in test:
        x, facts = features(r)
        gold = r["hidden"]["gold"]
        out = tree.predict(np.array([x]))[0]
        rp = bool(ptree.predict(np.array([x]))[0]) if ptree else default_p
        ok, field = grade(build_response(out, facts, rp), gold)
        res["tree"] += ok
        res["tree_outcome"] += out == gold["outcome"]
        if not ok:
            errs[r["hidden"]["rule"]] += 1
        res["majority_outcome"] += maj == gold["outcome"]
        res["operator"] += grade(r["hidden"]["operator_reply"], gold)[0]
    n = len(test)
    return {"policy": name, "n_train": n_train, **{k: round(v / n, 3) for k, v in res.items()},
            "tree_errors_by_rule": dict(errs), "tree_depth": int(tree.get_depth()), "tree_leaves": int(tree.get_n_leaves())}


if __name__ == "__main__":
    out = []
    for P in sample_policies():
        for n in (25, 50, 100, 200):
            r = run(n, P.name)
            out.append(r)
            print(json.dumps(r))
    Path("results").mkdir(exist_ok=True)
    Path("results/phase1.json").write_text(json.dumps(out, indent=2))
