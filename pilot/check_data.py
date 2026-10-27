import collections, sys
from pathlib import Path
from bench import build, load, grade, floor, to_request
from env import make_state, execute_policy, sample_policies
D = Path("data")
meta = build(D)
s = make_state(0)
for P in sample_policies(7):
    rows = load(D, P.name)
    oc = collections.Counter(r["hidden"]["gold"]["outcome"] for r in rows)
    ru = collections.Counter(r["hidden"]["rule"] for r in rows)
    pert = collections.Counter(r["hidden"]["perturbation"] for r in rows)
    assert all(grade(r["hidden"]["gold"], r["hidden"]["gold"])[0] for r in rows)
    fl = [floor(r["hidden"]["gold"], s) for r in rows]
    bad = [f for f in fl if not f[0]]
    # operator replies that differ from gold
    differ = sum(not grade(r["hidden"]["operator_reply"], r["hidden"]["gold"])[0] for r in rows)
    print(P.name, {k: v for k, v in vars(P).items() if k != "name"})
    print("   outcomes", dict(oc))
    print("   rules", dict(ru))
    print("   perturb", dict(pert), "replies != gold:", differ, " gold floor failures:", len(bad), bad[:3])
print(open(D/"P0.jsonl").readline()[:900])
