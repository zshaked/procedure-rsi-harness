"""Deterministic baseline policies for E2 (no model calls).

A policy maps a case to a structured reply. Two baselines:

    MajorityBaseline   the most common historical outcome class, facts filled from the snapshot
    RetrievalBaseline  the majority outcome among learning cases with the same decision
                       signature (falling back to coarser signatures), facts from the snapshot

Retrieval over past cases is the control arm every later method must beat
(docs/descent.md §5; pilot RESULTS_v3 "history only" is the LLM version of it).
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Protocol

from .cases.parse import parse_as_of
from .cases.schema import Case, ReplyFields
from .cases.signature import Signature, signature
from .reward.fields import extract


class Policy(Protocol):
    def __call__(self, case: Case) -> ReplyFields: ...


def decision_key(s: Signature) -> tuple:
    """The signature fields that plausibly determine the outcome class."""
    return (s.sender_known, s.account_res, s.instrument_res, s.date_kind != "none", s.date_future, s.date_bday,
            s.entitled_level, s.domain_ok, s.legal_hold, s.opt_out, s.holds, s.qty_gap)


def _effective_date(case: Case, s: Signature) -> tuple[str, bool]:
    as_of, kind = parse_as_of(case.email.body, case.email.sent)
    assumed = as_of is None
    d = dt.date.fromisoformat(as_of or case.email.sent)
    while not case.snapshot.is_business_day(d.isoformat()):
        d -= dt.timedelta(days=1)
    return d.isoformat(), assumed


def _resolved(case: Case) -> tuple[str | None, str | None]:
    snap, e = case.snapshot, case.email
    a = e.mentions.get("account_text")
    hits = snap.resolve_account(a) if a else []
    aid = hits[0] if len(hits) == 1 else None
    if aid is None and a is None:
        c = snap.contact(e.sender)
        live = snap.live_entitled_accounts(c["contact_id"], e.sent) if c else []
        aid = live[0] if len(live) == 1 else None
    i = e.mentions.get("instrument_text")
    ihits = snap.resolve_instrument(i) if i else []
    return aid, (ihits[0] if len(ihits) == 1 else None)


def _fill(case: Case, s: Signature, outcome: str, report_pending: bool) -> ReplyFields:
    f = ReplyFields(outcome=outcome)
    if outcome not in ("CONFIRMED", "NOT_HELD"):
        return f
    aid, iid = _resolved(case)
    if aid is None or iid is None:
        return ReplyFields(outcome="REQUEST_INFO")        # cannot assert facts it cannot look up
    eff, assumed = _effective_date(case, s)
    settled = case.snapshot.settled(aid, iid, eff)
    f.account_id, f.instrument = aid, case.snapshot.instrument(iid)["ticker"]
    f.as_of, f.as_of_assumed = eff, assumed
    if settled <= 0:
        f.outcome = "NOT_HELD"
        return f
    f.outcome, f.settled = "CONFIRMED", settled
    if report_pending:
        p, pdate = case.snapshot.pending(aid, iid, eff)
        if p > 0:
            f.pending, f.pending_date = p, pdate
    return f


class MajorityBaseline:
    def __init__(self, learning: Sequence[Case]):
        refs = [c.reply_fields or extract(c.reply_text) for c in learning]
        self.outcome = Counter(r.outcome for r in refs if r.outcome).most_common(1)[0][0]
        conf = [r for r in refs if r.outcome == "CONFIRMED"]
        self.report_pending = sum(r.pending is not None for r in conf) >= len(conf) / 2 if conf else False

    def __call__(self, case: Case) -> ReplyFields:
        return _fill(case, signature(case), self.outcome, self.report_pending)


class RetrievalBaseline:
    def __init__(self, learning: Sequence[Case]):
        self.by_decision: dict[tuple, Counter] = defaultdict(Counter)
        self.by_coarse: dict[tuple, Counter] = defaultdict(Counter)
        self.pending_votes: dict[tuple, list[bool]] = defaultdict(list)
        glob = Counter()
        for c in learning:
            r = c.reply_fields or extract(c.reply_text)
            if not r.outcome:
                continue
            s = signature(c)
            self.by_decision[decision_key(s)][r.outcome] += 1
            self.by_coarse[s.coarse()][r.outcome] += 1
            glob[r.outcome] += 1
            if r.outcome == "CONFIRMED" and s.pending_pos:
                self.pending_votes[decision_key(s)].append(r.pending is not None)
        self.global_outcome = glob.most_common(1)[0][0]
        allv = [v for vs in self.pending_votes.values() for v in vs]
        self.global_pending = (sum(allv) >= len(allv) / 2) if allv else False

    def __call__(self, case: Case) -> ReplyFields:
        s = signature(case)
        k = decision_key(s)
        votes = self.by_decision.get(k) or self.by_coarse.get(s.coarse())
        outcome = votes.most_common(1)[0][0] if votes else self.global_outcome
        pv = self.pending_votes.get(k)
        report_pending = (sum(pv) >= len(pv) / 2) if pv else self.global_pending
        return _fill(case, s, outcome, report_pending)
