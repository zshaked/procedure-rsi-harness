"""Problem-indexed edit library (DESIGN.md §9.1–9.2).

Keyed by the failure an edit addresses: a fixed top-level taxonomy with a
free-text root-cause hypothesis underneath. Every attempt at a problem is kept —
accepted, rejected, regressing — with its rationale, its predictions, the gate
outcome, the realized effect, and provenance. The curator reads the library by
problem ("every attempt at this failure and how each did"), never as a
chronological edit log.

The library travels with the reservoir (§9.2): `inherit()` marks every entry
as inherited from a source mailbox or model so a continuation run treats them
as revisable with provenance rather than as fixed rules.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

TAXONOMY = (
    "wrong_field_extraction",
    "wrong_node_or_tool",
    "wrong_arguments",
    "precondition_missed",
    "unsafe_side_effect",
    "should_have_escalated",
    "over_escalated",
)


@dataclass
class Attempt:
    attempt_id: str
    taxonomy: str
    hypothesis: str                          # free-text root cause, child of the taxonomy bucket
    edit: dict                               # typed edit (DESIGN.md §6.3)
    rationale: str
    predicts_fixed: list[str]                # case ids
    predicts_unaffected: list[str]           # case ids
    provenance: dict                         # {"mailbox", "model", "epoch", ...}
    gate: str | None = None                  # accepted | rejected | None (not yet gated)
    delta: float | None = None               # paired Δ on search validation
    realized_fixed: list[str] | None = None
    realized_changed_unaffected: list[str] | None = None
    status: str = "proposed"                 # proposed | approved | retired | inherited

    @property
    def fix_efficiency(self) -> float | None:
        if self.realized_fixed is None or not self.predicts_fixed:
            return None
        return len(set(self.realized_fixed) & set(self.predicts_fixed)) / len(self.predicts_fixed)

    @property
    def interference(self) -> float | None:
        if self.realized_changed_unaffected is None or not self.predicts_unaffected:
            return None
        return len(self.realized_changed_unaffected) / len(self.predicts_unaffected)


class Library:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._attempts: dict[str, Attempt] = {}
        if self.path and self.path.exists():
            for row in json.loads(self.path.read_text()):
                a = Attempt(**row)
                self._attempts[a.attempt_id] = a

    # ---------------------------------------------------------------- writes
    def add_attempt(self, taxonomy: str, hypothesis: str, edit: dict, rationale: str,
                    predicts_fixed: list[str], predicts_unaffected: list[str], provenance: dict) -> Attempt:
        if taxonomy not in TAXONOMY:
            raise ValueError(f"taxonomy {taxonomy!r} not in {TAXONOMY}")
        a = Attempt(uuid.uuid4().hex[:12], taxonomy, hypothesis.strip(), edit, rationale,
                    list(predicts_fixed), list(predicts_unaffected), dict(provenance))
        self._attempts[a.attempt_id] = a
        self._save()
        return a

    def record_outcome(self, attempt_id: str, gate: str, delta: float | None,
                       realized_fixed: list[str], realized_changed_unaffected: list[str]) -> Attempt:
        a = self._attempts[attempt_id]
        a.gate, a.delta = gate, delta
        a.realized_fixed = list(realized_fixed)
        a.realized_changed_unaffected = list(realized_changed_unaffected)
        if gate == "accepted" and a.status == "proposed":
            a.status = "approved"
        self._save()
        return a

    def set_status(self, attempt_id: str, status: str) -> None:
        self._attempts[attempt_id].status = status
        self._save()

    def inherit(self, target_provenance: dict) -> int:
        """Mark every entry as inherited into a new mailbox/model. Returns count."""
        n = 0
        for a in self._attempts.values():
            a.status = "inherited"
            a.provenance = {**a.provenance, "inherited_into": target_provenance}
            n += 1
        self._save()
        return n

    # ---------------------------------------------------------------- reads
    def by_problem(self, taxonomy: str, hypothesis: str | None = None) -> list[Attempt]:
        return [a for a in self._attempts.values()
                if a.taxonomy == taxonomy and (hypothesis is None or a.hypothesis == hypothesis.strip())]

    def problems(self) -> list[dict]:
        groups: dict[tuple[str, str], list[Attempt]] = defaultdict(list)
        for a in self._attempts.values():
            groups[(a.taxonomy, a.hypothesis)].append(a)
        out = []
        for (tax, hyp), atts in sorted(groups.items()):
            eff = [a.fix_efficiency for a in atts if a.fix_efficiency is not None]
            inter = [a.interference for a in atts if a.interference is not None]
            out.append({
                "taxonomy": tax, "hypothesis": hyp, "attempts": len(atts),
                "accepted": sum(a.gate == "accepted" for a in atts),
                "rejected": sum(a.gate == "rejected" for a in atts),
                "mean_fix_efficiency": sum(eff) / len(eff) if eff else None,
                "mean_interference": sum(inter) / len(inter) if inter else None,
            })
        return out

    def render_for_curator(self, taxonomy: str, hypothesis: str | None = None) -> str:
        """The block the curator reads: every attempt at this failure and how each did."""
        atts = self.by_problem(taxonomy, hypothesis)
        if not atts:
            return f"[{taxonomy}] no prior attempts."
        lines = [f"[{taxonomy}] {len(atts)} prior attempt(s)" + (f" at: {hypothesis}" if hypothesis else "")]
        for a in atts:
            eff = "—" if a.fix_efficiency is None else f"{a.fix_efficiency:.0%}"
            inter = "—" if a.interference is None else f"{a.interference:.0%}"
            lines.append(
                f"  - {a.attempt_id} [{a.status}/{a.gate or 'ungated'}] {a.edit.get('type', '?')}: "
                f"{a.edit.get('text', '')!s:.90} | predicted {len(a.predicts_fixed)} fixed, realized {eff} | "
                f"interference {inter} | Δ={a.delta} | from {a.provenance.get('mailbox', '?')}/{a.provenance.get('model', '?')}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._attempts)

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(a) for a in self._attempts.values()], indent=1))
