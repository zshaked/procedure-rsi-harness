"""Export the method-visible view of one policy instance to a sandbox directory.

Visible: state snapshot + tools, learning histories (request, reply text, the operator's decision
as read from the reply), a terminal-feedback harness, and a budgeted oracle CLI.
Not visible: the policy, gold responses, rules, perturbation flags, search-validation and test cases.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from bench import load
from env import make_state, sample_policies

HERE = Path(__file__).resolve().parent

TOOLS_PY = '''"""Tools over the system-of-record snapshot. This is the only interface to state."""
import json
from pathlib import Path

_S = json.loads((Path(__file__).parent / "state.json").read_text())
_ACC = {a["id"]: a for a in _S["accounts"]}
_CON = {c["email"]: c for c in _S["contacts"]}
_INS = {i["id"]: i for i in _S["instruments"]}
_POS = {(p["account_id"], p["instrument_id"]): p for p in _S["positions"]}


def lookup_account(ref: str) -> list:
    """Accounts matching a reference: exact id, exact name, else name prefix."""
    r = ref.lower().strip()
    if r.upper() in _ACC:
        return [dict(_ACC[r.upper()])]
    hits = [a for a in _ACC.values() if a["name"].lower() == r] or [a for a in _ACC.values() if a["name"].lower().startswith(r)]
    return [dict(a) for a in hits]


def get_contact(email: str):
    """Contact record {email, account_id, auth_level} or None."""
    c = _CON.get(email.lower())
    return dict(c) if c else None


def resolve_instrument(ref: str) -> list:
    """Instruments matching a ticker, name or id exactly (case-insensitive)."""
    r = ref.lower().strip()
    return [dict(i) for i in _INS.values() if r in (i["ticker"].lower(), i["name"].lower(), i["id"].lower())]


def get_position(account_id: str, instrument_id: str, as_of: str):
    """{settled, pending, pending_date} as of a date (YYYY-MM-DD), or None if never held.
    pending is only non-zero if the pending settlement date is after as_of."""
    p = _POS.get((account_id, instrument_id))
    if p is None:
        return None
    settled = p["qty_after"] if as_of >= p["trade_date"] else p["qty_before"]
    pend = p["pending"] if (p["pending_date"] and p["pending_date"] > as_of) else 0
    return {"settled": settled, "pending": pend, "pending_date": p["pending_date"] if pend else None}
'''

README = '''# Task: induce the procedure of an operations desk

An operations desk answers emails asking it to confirm a client's holding of a security. The desk
follows a procedure that was never written down. You have:

- `histories.jsonl` — {n_learn} past requests with the reply an operator actually sent, oldest first.
  Each row: `case_id`, `request` (`from`, `date`, `body`, and parsed `fields`), `reply_text`, and
  `reply_outcome` (the decision as read from the reply). Operators are not perfectly consistent;
  some past replies are mistakes.
- `tools.py` — the only interface to the system of record: `lookup_account`, `get_contact`,
  `resolve_instrument`, `get_position`. The snapshot is replayable.
- `harness.py` — `python3 harness.py procedure.py` runs your procedure on every history and reports
  agreement with the operators' decisions, fact errors, and examples of disagreements.
- `oracle.py` — an operator you may ask. `python3 oracle.py <case_id> '<response json>'` returns
  whether that response to that historical request is acceptable, with a one-sentence reason.
  **Budget: {budget} questions, total.** It can be wrong occasionally. Only history case_ids are valid.

## Deliverable

`procedure.py` defining `respond(request: dict, tools) -> dict`. `request` has the same shape as
`histories.jsonl` rows' `request`. `tools` is the `tools` module. Return:

```
{{"outcome": one of CONFIRMED | NOT_HELD | ESCALATE | REQUEST_INFO | REQUEST_AUTHORIZATION,
 "account_id": str|None, "instrument_id": str|None, "as_of": "YYYY-MM-DD"|None,
 "as_of_assumed": bool, "settled": int|None, "pending": int|None, "pending_date": str|None}}
```

Fill account/instrument for CONFIRMED, NOT_HELD and ESCALATE; as_of/as_of_assumed for CONFIRMED and
NOT_HELD; settled for CONFIRMED; pending and pending_date only when the desk would report them.
The procedure will be evaluated on new requests with no reference reply, by the desk's actual rules.
It must be deterministic and must not read any file other than via `tools`.
'''

HARNESS_PY = '''import collections, importlib.util, json, sys
from pathlib import Path
import tools
H = [json.loads(l) for l in (Path(__file__).parent / "histories.jsonl").read_text().splitlines()]
spec = importlib.util.spec_from_file_location("procedure", sys.argv[1]); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def facts_ok(r):
    if r.get("outcome") != "CONFIRMED":
        return True
    p = tools.get_position(r.get("account_id"), r.get("instrument_id"), r.get("as_of") or "")
    return bool(p) and p["settled"] == r.get("settled") and (not r.get("pending") or (r["pending"] == p["pending"] and r.get("pending_date") == p["pending_date"]))

agree, fact_err, dis = 0, 0, []
conf = collections.Counter()
for h in H:
    try:
        r = mod.respond(h["request"], tools)
    except Exception as e:
        r = {"outcome": "ERROR:" + repr(e)[:80]}
    conf[(h["reply_outcome"], r.get("outcome"))] += 1
    if r.get("outcome") == h["reply_outcome"]:
        agree += 1
    else:
        dis.append((h["case_id"], h["request"]["body"], h["request"]["from"], h["reply_text"], r.get("outcome")))
    fact_err += not facts_ok(r)
print(f"agreement with operator decisions: {agree}/{len(H)} = {agree/len(H):.3f}   fact errors: {fact_err}")
print("confusion (operator -> yours):", {f"{a}->{b}": n for (a, b), n in sorted(conf.items()) if a != b})
for d in dis[:15]:
    print(" -", d)
'''

ORACLE_PY = '''import json, sys
sys.path.insert(0, {hidden!r})
from oracle_backend import ask
print(json.dumps(ask({policy!r}, sys.argv[1], json.loads(sys.argv[2]), {budget})))
'''


def export(policy: str, out: Path, budget: int, n_learn: int = 200) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    s = make_state(0)
    state = {"accounts": [asdict(a) for a in s.accounts.values()],
             "contacts": [asdict(c) for c in s.contacts.values()],
             "instruments": [asdict(i) for i in s.instruments.values()],
             "positions": [asdict(p) for p in s.positions.values()]}
    (out / "state.json").write_text(json.dumps(state))
    (out / "tools.py").write_text(TOOLS_PY)
    rows = [r for r in load(HERE / "data", policy) if r["role"] == "learning"][:n_learn]
    (out / "histories.jsonl").write_text("\n".join(json.dumps({
        "case_id": r["case_id"], "request": r["request"], "reply_text": r["reply_text"],
        "reply_outcome": r["hidden"]["operator_reply"]["outcome"]}) for r in rows))
    (out / "harness.py").write_text(HARNESS_PY)
    (out / "oracle.py").write_text(ORACLE_PY.format(hidden=str(HERE), policy=policy, budget=budget))
    (out / "README.md").write_text(README.format(n_learn=len(rows), budget=budget))


if __name__ == "__main__":
    export(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]))
