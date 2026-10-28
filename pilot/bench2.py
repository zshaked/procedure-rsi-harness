"""v2 histories, sandbox export, oracle backend, and the perfect-feature tree baseline."""
from __future__ import annotations

import collections
import datetime as dt
import json
import random
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from bench import grade
from env2 import (Intent, RULE_REASONS2, World, execute2, is_bday, make_intents, make_world, policies2,
                  render_email, roll_back)

HERE = Path(__file__).resolve().parent
D2 = HERE / "data2"

_T = {
    "CONFIRMED": ["We confirm that {acct} holds {settled:,} {inst} as of {as_of}.",
                  "Confirmed: {settled:,} {inst} settled in {acct} as of {as_of}.",
                  "Confirming {acct} position in {inst}: {settled:,} settled as of {as_of}."],
    "NOT_HELD": ["{acct} does not hold {inst} as of {as_of}.", "We show no settled position in {inst} for {acct} as of {as_of}."],
    "ESCALATE": ["Thanks, we are referring this request for review and will revert.", "This has been passed to our escalations team."],
    "REQUEST_INFO": ["Could you clarify the details of your request so we can locate the position?",
                     "We need a little more information: please confirm the account, security and date you need."],
    "REQUEST_AUTHORIZATION": ["We are unable to share this information without authorization from the client.",
                              "For security reasons please arrange authorization before we can confirm."],
}
_WRONG = {"CONFIRMED": ["ESCALATE"], "ESCALATE": ["CONFIRMED"], "REQUEST_AUTHORIZATION": ["CONFIRMED", "REQUEST_INFO"],
          "REQUEST_INFO": ["CONFIRMED", "REQUEST_AUTHORIZATION"], "NOT_HELD": ["REQUEST_INFO"]}


def mentions(it: Intent) -> dict:
    """Raw spans, as an upstream extraction step would return them: not normalized."""
    return {"account_text": it.account_ref, "instrument_text": it.instrument_ref}


def render_reply(r: dict, w: World, rng: random.Random) -> str:
    inst = w.instruments[r["instrument_id"]]["ticker"] if r.get("instrument_id") else ""
    acct = r.get("account_id") or ""
    txt = rng.choice(_T[r["outcome"]]).format(inst=inst, acct=acct, **{k: v for k, v in r.items() if k not in ("outcome",)})
    if r["outcome"] in ("CONFIRMED", "NOT_HELD") and r.get("as_of_assumed"):
        txt += " As no date was given we have used the date of your email."
    if r["outcome"] == "CONFIRMED" and r.get("pending"):
        txt += f" A further {r['pending']:,} are pending settlement, expected {r['pending_date']}."
    return txt


def perturb(gold: dict, it: Intent, w: World, rng: random.Random) -> tuple[dict, str]:
    r = dict(gold)
    if gold["outcome"] == "CONFIRMED" and gold.get("pending") and rng.random() < 0.5:
        r["pending"], r["pending_date"] = None, None
        return r, "omit_pending"
    r["outcome"] = rng.choice(_WRONG[gold["outcome"]])
    if r["outcome"] == "CONFIRMED":
        if gold.get("account_id") and gold.get("instrument_id"):
            d = gold.get("as_of") or it.as_of or it.sent
            s = w.settled(gold["account_id"], gold["instrument_id"], d)
            if s > 0:
                r.update(as_of=d, as_of_assumed=it.as_of is None, settled=s, pending=None, pending_date=None)
                return r, "wrong_decision"
        r["outcome"] = "REQUEST_INFO"
    return r, "wrong_decision"


def strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "_rule"}


def build(n: int = 400, rho_op: float = 0.2, seed: int = 0) -> None:
    D2.mkdir(exist_ok=True)
    w = make_world(seed)
    for k, P in enumerate(policies2()):
        rng = random.Random(500 + k)
        rows = []
        for t, it in enumerate(make_intents(w, n, seed=300 + k)):
            gold = execute2(it, w, P)
            reply, pert = strip(gold), None
            if rng.random() < rho_op / 3:
                reply, pert = perturb(strip(gold), it, w, rng)
            role = "learning" if t < n // 2 else ("search_validation" if t < 3 * n // 4 else "final_test")
            req = {**render_email(it, w, rng), "mentions": mentions(it)}
            rows.append({"case_id": f"{P.name}-{t:04d}", "t": t, "role": role, "request": req,
                         "reply_text": render_reply(reply, w, rng),
                         "hidden": {"intent": asdict(it), "gold": strip(gold), "rule": gold["_rule"],
                                    "operator_reply": reply, "perturbation": pert}})
        (D2 / f"{P.name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        (D2 / f"{P.name}.policy.txt").write_text(P.render())


def load2(name: str) -> list[dict]:
    return [json.loads(l) for l in (D2 / f"{name}.jsonl").read_text().splitlines()]


# --------------------------------------------------------------------------- perfect-feature tree

def feats(it: Intent, w: World) -> tuple[list[float], dict]:
    c = w.contacts.get(it.from_email)
    cid = c["contact_id"] if c else None
    live = w.live_entitled_accounts(cid, it.sent) if cid else []
    dom = it.from_email.split("@")[1]
    accts = (live if len(live) == 1 else []) if it.account_ref is None else w.resolve_account(it.account_ref)
    aid = accts[0] if len(accts) == 1 else None
    insts = w.resolve_instrument(it.instrument_ref) if it.instrument_ref else []
    iid = insts[0] if len(insts) == 1 else None
    as_of = it.as_of or it.sent
    d = dt.date.fromisoformat(as_of)
    eff = roll_back(d).isoformat()
    s = w.settled(aid, iid, eff) if aid and iid else 0
    pend, pdate = w.pending(aid, iid, eff) if aid and iid else (0, None)
    pre = w.settled_presplit(aid, iid, eff) if aid and iid else None
    lvl = w.entitlement(cid, aid, it.sent) if (cid and aid) else 0
    expired = bool(cid and aid and lvl == 0 and any(e["account_id"] == aid for e in w.entitlements[cid]))
    sq = it.stated_qty
    f = [float(c is not None), len(live), float(any(dom in w.profiles[a]["domains"] for a in live)),
         float(it.account_ref is not None), len(w.resolve_account(it.account_ref)) if it.account_ref else 0, len(accts),
         lvl, float(expired), float(bool(aid and dom in w.profiles[aid]["domains"])),
         float(bool(aid and w.profiles[aid]["no_email_confirm"])), float(it.instrument_ref is not None), len(insts),
         float(it.as_of is not None), float(as_of > it.sent), float(not is_bday(d)),
         float(bool(aid and w.profiles[aid]["legal_hold"])), float(s > 0), s / 1000, pend,
         float(sq is not None), abs(sq - s) / s if (sq is not None and s) else -1,
         abs(sq - s - pend) / (s + pend) if (sq is not None and s + pend) else -1, float(pre is not None and sq == pre)]
    facts = {"account_id": aid, "instrument_id": iid, "as_of": eff, "as_of_assumed": it.as_of is None,
             "settled": s or None, "pending": pend or None, "pending_date": pdate if pend else None}
    return f, facts


def response(outcome: str, facts: dict, rp: bool) -> dict:
    r = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None, "as_of_assumed": False,
         "settled": None, "pending": None, "pending_date": None}
    if outcome in ("CONFIRMED", "NOT_HELD", "ESCALATE"):
        r.update(account_id=facts["account_id"], instrument_id=facts["instrument_id"])
    if outcome in ("CONFIRMED", "NOT_HELD"):
        r.update(as_of=facts["as_of"], as_of_assumed=facts["as_of_assumed"])
    if outcome == "CONFIRMED":
        r["settled"] = facts["settled"]
        if rp and facts["pending"]:
            r.update(pending=facts["pending"], pending_date=facts["pending_date"])
    return r


def tree_run(name: str, n_train: int, w: World, seed: int = 0) -> dict:
    rows = load2(name)
    learn = [r for r in rows if r["role"] == "learning"][:n_train]
    test = [r for r in rows if r["role"] == "final_test"]
    L = [feats(Intent(**r["hidden"]["intent"]), w) for r in learn]
    y = [r["hidden"]["operator_reply"]["outcome"] for r in learn]
    tree = DecisionTreeClassifier(min_samples_leaf=2, random_state=seed).fit(np.array([x for x, _ in L]), y)
    pl = [(x, bool(r["hidden"]["operator_reply"].get("pending"))) for (x, f), r in zip(L, learn)
          if r["hidden"]["operator_reply"]["outcome"] == "CONFIRMED" and f["pending"]]
    pt = DecisionTreeClassifier(min_samples_leaf=2).fit(np.array([x for x, _ in pl]), [b for _, b in pl]) if len({b for _, b in pl}) > 1 else None
    dflt = (sum(b for _, b in pl) / len(pl) >= 0.5) if pl else True
    ok, miss = 0, collections.Counter()
    for r in test:
        x, f = feats(Intent(**r["hidden"]["intent"]), w)
        out = tree.predict(np.array([x]))[0]
        rp = bool(pt.predict(np.array([x]))[0]) if pt else dflt
        g = grade(response(out, f, rp), r["hidden"]["gold"])[0]
        ok += g
        if not g:
            miss[r["hidden"]["rule"]] += 1
    return {"policy": name, "n_train": n_train, "tree": round(ok / len(test), 3), "misses": dict(miss)}


# --------------------------------------------------------------------------- sandbox export

TOOLS2 = r'''"""Tools over the system-of-record snapshot. This is the only interface to state.
Dates are ISO strings YYYY-MM-DD."""
import json
from pathlib import Path

_W = json.loads((Path(__file__).parent / "state.json").read_text())


def search_accounts(query: str) -> list:
    """Accounts whose id, sub-account id, name or short name equals the query (case-insensitive);
    if none, accounts whose name starts with it. Returns [{id, name, short_name}]."""
    r = query.strip().lower()
    acc = _W["accounts"].values()
    hits = [a for a in acc if r == a["id"].lower() or r in (s.lower() for s in a["sub_accounts"])
            or r == a["name"].lower() or r == a["short_name"].lower()]
    if not hits:
        hits = [a for a in acc if a["name"].lower().startswith(r)]
    return [{"id": a["id"], "name": a["name"], "short_name": a["short_name"]} for a in sorted(hits, key=lambda a: a["id"])]


def get_account(account_id: str):
    """{id, name, short_name, sub_accounts[]} or None."""
    a = _W["accounts"].get(account_id)
    return dict(a) if a else None


def get_client_profile(account_id: str):
    """{domains[], legal_hold, no_email_confirm} or None."""
    p = _W["profiles"].get(account_id)
    return dict(p) if p else None


def get_contact(email: str):
    """{contact_id, email, name} or None. Authorization is NOT here; see get_entitlements."""
    c = _W["contacts"].get(email.lower())
    return dict(c) if c else None


def get_entitlements(contact_id: str) -> list:
    """[{account_id, level, expires}] for a contact. Expired entitlements are included."""
    return [dict(e) for e in _W["entitlements"].get(contact_id, [])]


def search_instruments(query: str) -> list:
    """Instruments whose ticker, former ticker, name or id equals the query (case-insensitive)."""
    r = query.strip().lower()
    return [dict(i) for i in _W["instruments"].values()
            if r in (i["ticker"].lower(), (i["old_ticker"] or "").lower(), i["name"].lower(), i["id"].lower())]


def get_instrument(instrument_id: str):
    i = _W["instruments"].get(instrument_id)
    return dict(i) if i else None


def get_corporate_actions(instrument_id: str) -> list:
    """[{type: 'split', date, ratio}] — a split multiplies holdings recorded before its date."""
    s = _W["splits"].get(instrument_id)
    return [{"type": "split", **s}] if s else []


def get_ledger(account_id: str, instrument_id: str) -> list:
    """Raw settled transactions [{sub_account, date, qty}] across all custody sub-accounts.
    Quantities are as recorded at the time (not adjusted for later corporate actions)."""
    return [dict(t) for t in _W["ledger"].get(account_id + "|" + instrument_id, [])]


def get_position_summary(account_id: str, instrument_id: str, as_of: str):
    """Cached position summary from the reporting system: {quantity, as_of_used}. Convenience view."""
    import datetime as dt
    hol = set(_W["holidays"])
    d = dt.date.fromisoformat(as_of) - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= dt.timedelta(days=1)
    acct = _W["accounts"].get(account_id)
    if not acct:
        return None
    primary = acct["sub_accounts"][0]
    q = sum(t["qty"] for t in _W["ledger"].get(account_id + "|" + instrument_id, [])
            if t["sub_account"] == primary and t["date"] <= d.isoformat())
    return {"quantity": q, "as_of_used": d.isoformat()}


def get_instructions(account_id: str, instrument_id: str) -> list:
    """Settlement instructions [{id, qty, settle_date, status}], status in matched|unmatched|cancelled."""
    return [dict(x) for x in _W["instructions"].get(account_id + "|" + instrument_id, [])]


def get_calendar(date: str) -> dict:
    """{date, business_day: bool, previous_business_day} — weekends and market holidays are not business days."""
    import datetime as dt
    hol = set(_W["holidays"])
    d0 = dt.date.fromisoformat(date)
    ok = d0.weekday() < 5 and date not in hol
    d = d0 - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= dt.timedelta(days=1)
    return {"date": date, "business_day": ok, "previous_business_day": d.isoformat()}
'''

README2 = '''# Task: induce the procedure of an operations desk

An operations desk answers emails asking it to confirm a client's holding of a security. The desk
follows a procedure that was never written down. You have:

- `histories.jsonl` — {n} past emails with the reply an operator actually sent, oldest first. Each
  row: `case_id`, `request` (`from`, `sent`, `subject`, `body`, and `mentions` — raw text spans for the
  account and instrument as an upstream extractor returned them, not normalized), `reply_text`, and
  `reply_outcome` (the decision as read from the reply). Operators are not perfectly consistent;
  some past replies are mistakes.
- `tools.py` — the only interface to the system of record (see its docstrings). Several tools
  overlap; not every convenient-looking tool gives the figure the desk uses.
- `harness.py` — `python3 harness.py procedure.py` runs your procedure on every history and reports
  agreement with the operators' decisions and examples of disagreements.
{oracle}
## Deliverable

`procedure.py` defining `respond(request: dict, tools) -> dict`. `request` has the same shape as the
histories' `request`. Dates in the body are free text (e.g. "March 3, 2026", "3/3/2026",
"end of last month", "yesterday", relative to `sent`); quantities may be written "12,500", "12500",
"12.5k" or "1.2mm". Return:

```
{{"outcome": one of CONFIRMED | NOT_HELD | ESCALATE | REQUEST_INFO | REQUEST_AUTHORIZATION,
 "account_id": str|None, "instrument_id": str|None, "as_of": "YYYY-MM-DD"|None,
 "as_of_assumed": bool, "settled": int|None, "pending": int|None, "pending_date": str|None}}
```

Fill account/instrument for CONFIRMED, NOT_HELD and ESCALATE; as_of (the date the figure is
actually given for) and as_of_assumed for CONFIRMED and NOT_HELD; settled for CONFIRMED; pending and
pending_date only when the desk would report them. The procedure will be evaluated on new emails —
including phrasings and situations that may not appear in the histories — by the desk's actual rules.
It must be deterministic, use only the standard library, and read state only via `tools`.
'''

HARNESS2 = '''import collections, importlib.util, json, sys
from pathlib import Path
import tools
H = [json.loads(l) for l in (Path(__file__).parent / "histories.jsonl").read_text().splitlines()]
spec = importlib.util.spec_from_file_location("procedure", sys.argv[1]); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
NEED = {"CONFIRMED": ["account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date"],
        "NOT_HELD": ["account_id", "instrument_id", "as_of", "as_of_assumed"], "ESCALATE": ["account_id", "instrument_id"]}
def fields_agree(r, h):
    f = h["reply_fields"]
    for k in NEED.get(h["reply_outcome"], []):
        a, b = r.get(k), f.get(k)
        if k == "as_of_assumed": a, b = bool(a), bool(b)
        if k in ("pending", "pending_date"): a, b = (a or None), (b or None)
        if a != b: return False, k
    return True, None
agree_out, agree_full, dis, conf = 0, 0, [], collections.Counter()
for h in H:
    try:
        r = mod.respond(h["request"], tools)
    except Exception as e:
        r = {"outcome": "ERROR:" + repr(e)[:80]}
    conf[(h["reply_outcome"], r.get("outcome"))] += 1
    if r.get("outcome") == h["reply_outcome"]:
        agree_out += 1
        ok, k = fields_agree(r, h)
        if ok: agree_full += 1
        else: dis.append((h["case_id"], "outcome agrees; field differs:", k, "yours", r.get(k), "operator", h["reply_fields"].get(k)))
    else:
        dis.append((h["case_id"], "outcome differs:", h["reply_outcome"], "->", r.get(outcome_key := "outcome")))
print(f"outcome agreement: {agree_out}/{len(H)} = {agree_out/len(H):.3f}   full (outcome + fields) agreement: {agree_full}/{len(H)} = {agree_full/len(H):.3f}")
print("confusion (operator -> yours):", {f"{a}->{b}": n for (a, b), n in sorted(conf.items()) if a != b})
for d in dis[:25]:
    print(" -", d)
'''


def export(policy: str, out: Path, n_learn: int, budget: int = 0) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    w = make_world(0)
    state = {"accounts": w.accounts, "profiles": w.profiles, "contacts": w.contacts, "entitlements": w.entitlements,
             "instruments": w.instruments, "splits": w.splits,
             "ledger": {f"{a}|{i}": v for (a, i), v in w.ledger.items()},
             "instructions": {f"{a}|{i}": v for (a, i), v in w.instructions.items()},
             "holidays": sorted(__import__("env2").HOLIDAYS)}
    (out / "state.json").write_text(json.dumps(state))
    (out / "tools.py").write_text(TOOLS2)
    rows = [r for r in load2(policy) if r["role"] == "learning"][:n_learn]
    (out / "histories.jsonl").write_text("\n".join(json.dumps({
        "case_id": r["case_id"], "request": r["request"], "reply_text": r["reply_text"],
        "reply_outcome": r["hidden"]["operator_reply"]["outcome"],
        "reply_fields": {k: r["hidden"]["operator_reply"].get(k) for k in
                         ("account_id", "instrument_id", "as_of", "as_of_assumed", "settled", "pending", "pending_date")}}) for r in rows))
    (out / "harness.py").write_text(HARNESS2)
    pool = [r for r in load2(policy) if r["role"] == "learning"][n_learn:]
    (out / "unlabeled.jsonl").write_text("\n".join(json.dumps({"case_id": r["case_id"], "request": r["request"]}) for r in pool))
    oracle = (f"- `unlabeled.jsonl` — {len(pool)} further requests from the same period, with no reply. Use them as you see fit.\n")
    if budget:
        oracle += (f"- `oracle.py` — an operator you may ask. `python3 oracle.py <case_id> '<response json>'` says whether that "
                   f"response to that request (history or unlabeled) is acceptable, with a one-sentence reason. "
                   f"**Budget: {budget} questions, total.** It is occasionally wrong.\n")
        (out / "oracle.py").write_text(
            "import json, sys\n" f"sys.path.insert(0, {str(HERE)!r})\n" "from oracle_backend2 import ask\n"
            f"print(json.dumps(ask({policy!r}, {out.name!r}, {n_learn}, sys.argv[1], json.loads(sys.argv[2]), {budget})))\n")
    (out / "README.md").write_text(README2.format(n=len(rows), oracle=oracle))
    (out / "scratch").mkdir()


# --------------------------------------------------------------------------- grading a sandbox

def evaluate(policy: str, sandbox: Path, n_fresh: int = 2000) -> dict:
    import importlib.util
    sys.path.insert(0, str(sandbox))
    def load_mod(p, n):
        spec = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    tools = load_mod(sandbox / "tools.py", "t_" + sandbox.name)
    proc = load_mod(sandbox / "procedure.py", "p_" + sandbox.name)
    w = make_world(0)
    P = {p.name: p for p in policies2()}[policy]
    res = {"policy": policy, "arm": sandbox.name}
    rows = load2(policy)
    sets = {"final_test": [(r["request"], r["hidden"]["gold"], r["hidden"]["rule"]) for r in rows if r["role"] == "final_test"]}
    rng = random.Random(77)
    fresh = []
    for it in make_intents(w, n_fresh, seed=7000 + int(policy[1:])):
        g = execute2(it, w, P)
        fresh.append(({**render_email(it, w, rng), "mentions": mentions(it)}, strip(g), g["_rule"]))
    sets["fresh"] = fresh
    for k, items in sets.items():
        ok, miss, fields = 0, collections.Counter(), collections.Counter()
        for req, gold, rule in items:
            try:
                out = proc.respond(req, tools)
            except Exception:
                out = None
            g, f = grade(out, gold)
            ok += g
            if not g:
                miss[rule] += 1
                fields[f] += 1
        res[k] = {"correct": round(ok / len(items), 3), "n": len(items), "misses_by_rule": dict(miss), "misses_by_field": dict(fields)}
    return res


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build()
    elif cmd == "export":
        export(sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]) if len(sys.argv) > 5 else 0)
    elif cmd == "eval":
        print(json.dumps(evaluate(sys.argv[2], Path(sys.argv[3]).resolve()), indent=1))
