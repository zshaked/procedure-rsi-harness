"""Where does the expert-question gain come from? Per rule: frequency in the 25 histories,
frequency on 2,000 fresh emails, misses for history-only vs oracle arms (v3 runs), questions
spent on cases governed by that rule. Output: results/v3_gain_by_rule.json"""
import json, collections
from pathlib import Path
from bench2 import load2
from env2 import make_world, policies2, make_intents, execute2
w = make_world(0); POL = {p.name: p for p in policies2()}
runs = json.load(open("results/v3_runs.json")); logs = Path("results/oracle_logs_v3"); out = {}
for pol in ("Q2", "Q3", "Q4"):
    rows = load2(pol); learn25 = [r for r in rows if r["role"] == "learning"][:25]
    hist = collections.Counter(r["hidden"]["rule"] for r in learn25)
    rule_of = {r["case_id"]: r["hidden"]["rule"] for r in rows}
    fresh = collections.Counter(execute2(it, w, POL[pol])["_rule"] for it in make_intents(w, 2000, seed=7000 + int(pol[1:])))
    def miss(arms):
        rs = [r for r in runs if r["policy"] == pol and r["arm"] in arms]; c = collections.Counter()
        for r in rs:
            for k, v in r["misses_by_rule"].items(): c[k] += v / len(rs)
        return c
    h, o = miss({"history"}), miss({"policy_first", "spec_once", "verifier_first"})
    q = collections.Counter()
    for f in logs.glob(f"{pol}_*.jsonl"):
        for l in f.read_text().splitlines(): q[rule_of.get(json.loads(l)["case_id"], "?")] += 1
    out[pol] = {r: {"hist25": hist[r], "fresh2k": fresh[r], "miss_history": round(h[r], 1), "miss_oracle": round(o[r], 1),
                    "gain": round(h[r] - o[r], 1), "questions": q[r]} for r in fresh}
json.dump(out, open("results/v3_gain_by_rule.json", "w"), indent=1)
