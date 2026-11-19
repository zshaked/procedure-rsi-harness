"""Case signature: the observable parameters a procedure could condition on.

Computed from the email and the snapshot only. Two granularities:

    coarse  — what the email supplies and whether it resolves
    fine    — coarse plus the state facts a procedure would look up
              (entitlement, domain, holds, position, stated-quantity gap)

E0′ clusters historical cases by signature and reads disagreement within a
cluster as the noise floor's upper bound: identical observables, different
operator decisions. The gap between coarse and fine disagreement is how much
of that disagreement the unobserved-parameter story explains.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict

from .parse import parse_as_of, parse_stated_qty
from .schema import Case


def _roll_back(snap, d: str) -> str:
    x = dt.date.fromisoformat(d)
    while not snap.is_business_day(x.isoformat()):
        x -= dt.timedelta(days=1)
    return x.isoformat()


@dataclass(frozen=True)
class Signature:
    # coarse
    sender_known: bool
    account_res: str          # none | 0 | 1 | many
    instrument_res: str       # none | 0 | 1 | many
    date_kind: str            # explicit | relative | none
    stated_qty: bool
    # fine
    n_live: str = "?"         # 0 | 1 | 2+
    entitled_level: int | None = None
    domain_ok: bool | None = None
    legal_hold: bool | None = None
    opt_out: bool | None = None
    date_future: bool | None = None
    date_bday: bool | None = None
    holds: bool | None = None
    pending_pos: bool | None = None
    qty_gap: str | None = None   # exact | ≤5% | ≤10% | >10% | n/a

    def coarse(self) -> tuple:
        return (self.sender_known, self.account_res, self.instrument_res, self.date_kind, self.stated_qty)

    def fine(self) -> tuple:
        return tuple(asdict(self).values())


def _res(snap, ref: str | None, fn) -> tuple[str, str | None]:
    if ref is None:
        return "none", None
    hits = fn(ref)
    return ("0" if not hits else "1" if len(hits) == 1 else "many"), (hits[0] if len(hits) == 1 else None)


def signature(case: Case) -> Signature:
    e, snap = case.email, case.snapshot
    c = snap.contact(e.sender)
    cid = c["contact_id"] if c else None
    live = snap.live_entitled_accounts(cid, e.sent) if cid else []
    acct_res, aid = _res(snap, e.mentions.get("account_text"), snap.resolve_account)
    if acct_res == "none" and len(live) == 1:
        aid = live[0]                           # the implicit-account candidate; a policy may or may not use it
    inst_res, iid = _res(snap, e.mentions.get("instrument_text"), snap.resolve_instrument)
    as_of, kind = parse_as_of(e.body, e.sent)
    q = parse_stated_qty(e.body)

    lvl = snap.entitlement(cid, aid, e.sent) if (cid and aid) else None
    dom = e.sender.split("@")[-1]
    prof = snap.profile(aid) if aid else None
    future = bday = None
    if as_of:
        future = as_of > e.sent
        bday = snap.is_business_day(as_of)
    holds = pend = None
    gap = None
    if aid and iid:
        eff = _roll_back(snap, as_of) if as_of and not future else (as_of or e.sent)
        s = snap.settled(aid, iid, eff)
        p, _ = snap.pending(aid, iid, eff)
        holds, pend = s > 0, p > 0
        if q is not None:
            gap = "n/a" if s <= 0 else "exact" if q == s else "≤5%" if abs(q - s) / s <= 0.05 else "≤10%" if abs(q - s) / s <= 0.10 else ">10%"
    return Signature(
        sender_known=c is not None, account_res=acct_res, instrument_res=inst_res, date_kind=kind, stated_qty=q is not None,
        n_live="0" if not live else "1" if len(live) == 1 else "2+", entitled_level=lvl,
        domain_ok=(dom in prof["domains"]) if prof else None,
        legal_hold=prof["legal_hold"] if prof else None, opt_out=prof["no_email_confirm"] if prof else None,
        date_future=future, date_bday=bday, holds=holds, pending_pos=pend, qty_gap=gap,
    )
