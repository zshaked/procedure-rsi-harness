"""Adapter: cases from the synthetic confirmations environment (`pilot/env2.py`).

Reproduces `pilot/bench2.build` case for case (same world seed, same intent and
operator-noise RNG streams), so numbers here line up with the pilot's `data2/`
files, without importing bench2 (which pulls in sklearn).

Hidden fields — the sender's true intent, the gold outcome, the operator's
structured reply, and whether it was perturbed — go only to
`Case.meta["_benchmark"]`. Experiments may use them to validate an estimator
and must label any number that depends on them as benchmark-only.
"""
from __future__ import annotations

import random
import sys
from dataclasses import asdict
from pathlib import Path

from ..schema import Case, Email, Snapshot

_PILOT = Path(__file__).resolve().parents[3] / "pilot"
if str(_PILOT) not in sys.path:
    sys.path.insert(0, str(_PILOT))

import env2  # noqa: E402  (pilot/env2.py)

# Reply templates and perturbation, copied from pilot/bench2.py so this adapter has no sklearn dependency.
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


def _render_reply(r: dict, w: env2.World, rng: random.Random) -> str:
    inst = w.instruments[r["instrument_id"]]["ticker"] if r.get("instrument_id") else ""
    acct = r.get("account_id") or ""
    txt = rng.choice(_T[r["outcome"]]).format(inst=inst, acct=acct, **{k: v for k, v in r.items() if k != "outcome"})
    if r["outcome"] in ("CONFIRMED", "NOT_HELD") and r.get("as_of_assumed"):
        txt += " As no date was given we have used the date of your email."
    if r["outcome"] == "CONFIRMED" and r.get("pending"):
        txt += f" A further {r['pending']:,} are pending settlement, expected {r['pending_date']}."
    return txt


def _perturb(gold: dict, it: env2.Intent, w: env2.World, rng: random.Random) -> tuple[dict, str]:
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


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "_rule"}


class Env2Snapshot:
    """Closed tool vocabulary over an env2 World. The World is dated, so a single
    World object is point-in-time for every `as_of` ≤ t_reply."""

    def __init__(self, world: env2.World, t_reply: str):
        self._w = world
        self.t_reply = t_reply

    def resolve_account(self, ref: str) -> list[str]:
        return self._w.resolve_account(ref)

    def resolve_instrument(self, ref: str) -> list[str]:
        return self._w.resolve_instrument(ref)

    def instrument(self, instrument_id: str) -> dict | None:
        return self._w.instruments.get(instrument_id)

    def contact(self, email: str) -> dict | None:
        return self._w.contacts.get(email)

    def live_entitled_accounts(self, contact_id: str, on: str) -> list[str]:
        return self._w.live_entitled_accounts(contact_id, on)

    def entitlement(self, contact_id: str, account_id: str, on: str) -> int:
        return self._w.entitlement(contact_id, account_id, on)

    def profile(self, account_id: str) -> dict:
        return self._w.profiles[account_id]

    def settled(self, account_id: str, instrument_id: str, as_of: str) -> int:
        return self._w.settled(account_id, instrument_id, as_of)

    def pending(self, account_id: str, instrument_id: str, as_of: str) -> tuple[int, str | None]:
        return self._w.pending(account_id, instrument_id, as_of)

    def is_business_day(self, date: str) -> bool:
        import datetime as dt
        return env2.is_bday(dt.date.fromisoformat(date))


def policy_index(name: str) -> int:
    names = [p.name for p in env2.policies2()]
    if name not in names:
        raise ValueError(f"unknown policy {name!r}; one of {names}")
    return names.index(name)


def load_cases(policy: str = "Q2", n: int = 400, rho_op: float = 0.2, seed: int = 0) -> list[Case]:
    """Build `n` cases for hidden policy `policy`, matching pilot/bench2.build."""
    k = policy_index(policy)
    w = env2.make_world(seed)
    P = env2.policies2()[k]
    rng = random.Random(500 + k)
    cases: list[Case] = []
    for t, it in enumerate(env2.make_intents(w, n, seed=300 + k)):
        gold = env2.execute2(it, w, P)
        reply, pert = _strip(gold), None
        if rng.random() < rho_op / 3:
            reply, pert = _perturb(_strip(gold), it, w, rng)
        req = env2.render_email(it, w, rng)
        email = Email(sender=req["from"], sent=req["sent"], subject=req["subject"], body=req["body"],
                      mentions={"account_text": it.account_ref, "instrument_text": it.instrument_ref})
        snap: Snapshot = Env2Snapshot(w, t_reply=it.sent)
        cases.append(Case(
            case_id=f"{P.name}-{t:04d}", t=t, email=email, reply_text=_render_reply(reply, w, rng), snapshot=snap,
            meta={"_benchmark": {"intent": asdict(it), "gold": _strip(gold), "rule": gold["_rule"],
                                 "operator_reply": reply, "perturbation": pert, "policy": P.name}},
        ))
    return cases
