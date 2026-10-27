"""Stress test: grade every arm's procedure on 2,000 fresh requests per policy (new seed),
far beyond the 100 final-test cases, to find rule boundaries the histories never exercised."""
import collections, importlib.util, json, sys
from pathlib import Path
from env import make_state, make_requests, sample_policies, execute_policy
from bench import grade
from eval_procedure import evaluate
S = make_state(0); POL = {p.name: p for p in sample_policies()}
out = []
for sb in sorted(Path("/home/claude/sandboxes").iterdir()):
    pol = sb.name[:2]
    base = evaluate(pol, sb)
    sys.path.insert(0, str(sb))
    spec = importlib.util.spec_from_file_location("t"+sb.name, sb/"tools.py"); tools = importlib.util.module_from_spec(spec); spec.loader.exec_module(tools)
    spec = importlib.util.spec_from_file_location("p"+sb.name, sb/"procedure.py"); proc = importlib.util.module_from_spec(spec); spec.loader.exec_module(proc)
    reqs = make_requests(S, 2000, seed=9000 + int(pol[1]), prefix="F-")
    ok, miss = 0, collections.Counter()
    for q in reqs:
        gold = execute_policy(q, S, POL[pol]); rule = gold.pop("_rule")
        req = {"from": q.from_email, "date": q.request_date, "body": q.body,
               "fields": {"account_ref": q.account_ref, "instrument_ref": q.instrument_ref, "as_of": q.as_of, "stated_qty": q.stated_qty}}
        try: r = proc.respond(req, tools)
        except Exception: r = None
        g, f = grade(r, gold); ok += g
        if not g: miss[rule] += 1
    row = {"arm": sb.name, "final_test": base["final_test"]["correct"], "search_val": base["search_validation"]["correct"],
           "fresh_2000": round(ok/2000, 4), "fresh_misses_by_rule": dict(miss), "oracle_q": base["oracle_questions_used"],
           "verifier": base.get("verifier")}
    out.append(row); print(json.dumps(row))
Path("results/phase2_smoke.json").write_text(json.dumps(out, indent=2))
