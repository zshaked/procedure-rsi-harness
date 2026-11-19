"""E0′ — the human noise floor, from the histories alone (DESIGN.md §11, E0′(a)).

Cluster historical cases by signature; cases in one cluster present the same
observable parameters, so a difference in the operator's outcome class is
either operator inconsistency or a parameter the signature does not see. The
intra-cluster disagreement rate is therefore an *upper bound* on the operators'
own inconsistency ε, and tightens as the signature gets finer. It costs no
one's time.

Reported at three granularities (coarse, decision, fine). On the synthetic
environment the hidden perturbation flags let us check the estimator; that
check is labeled benchmark-only and does not exist on firm data.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from ..baselines import decision_key
from ..cases.schema import Case
from ..cases.signature import signature
from ..reward.fields import extract

LEVELS = ("coarse", "decision", "fine")


def _key(s, level: str) -> tuple:
    return s.coarse() if level == "coarse" else decision_key(s) if level == "decision" else s.fine()


def run(cases: Sequence[Case]) -> dict:
    sigs = {c.case_id: signature(c) for c in cases}
    refs = {c.case_id: (c.reply_fields or extract(c.reply_text)) for c in cases}
    bench = {c.case_id: c.meta.get("_benchmark") for c in cases}
    out: dict = {"n_cases": len(cases), "levels": {}}

    for level in LEVELS:
        clusters: dict[tuple, list[str]] = defaultdict(list)
        for c in cases:
            clusters[_key(sigs[c.case_id], level)].append(c.case_id)
        members = disagree = 0
        field_members = field_disagree = 0
        minority_ids: set[str] = set()
        worst: list[dict] = []
        for key, ids in clusters.items():
            if len(ids) < 2:
                continue
            outcomes = Counter(refs[i].outcome for i in ids)
            maj, maj_n = outcomes.most_common(1)[0]
            members += len(ids)
            disagree += len(ids) - maj_n
            minority_ids.update(i for i in ids if refs[i].outcome != maj)
            # field-level: among members agreeing on CONFIRMED, does "pending asserted" agree?
            conf = [i for i in ids if refs[i].outcome == "CONFIRMED"]
            if len(conf) >= 2:
                pend = Counter(refs[i].pending is not None for i in conf)
                field_members += len(conf)
                field_disagree += len(conf) - pend.most_common(1)[0][1]
            if len(ids) - maj_n:
                worst.append({"size": len(ids), "outcomes": dict(outcomes), "minority_ids": [i for i in ids if refs[i].outcome != maj]})
        worst.sort(key=lambda w: -(w["size"] - max(w["outcomes"].values())))
        lvl = {
            "clusters": len(clusters),
            "singletons": sum(len(v) == 1 for v in clusters.values()),
            "cases_in_clusters_ge2": members,
            "outcome_disagreement": disagree / members if members else None,
            "pending_field_disagreement_among_confirmed": field_disagree / field_members if field_members else None,
            "worst_clusters": worst[:5],
        }
        # benchmark-only validation of the estimator
        if all(bench.values()):
            perturbed = {i for i, b in bench.items() if b["perturbation"]}
            in_clusters = {i for ids in clusters.values() if len(ids) >= 2 for i in ids}
            tp = len(minority_ids & perturbed)
            lvl["_benchmark"] = {
                "true_perturbation_rate": len(perturbed) / len(cases),
                "minority_flag_precision": tp / len(minority_ids) if minority_ids else None,
                "minority_flag_recall_within_clusters": tp / len(perturbed & in_clusters) if perturbed & in_clusters else None,
            }
        out["levels"][level] = lvl
    return out


def summarize(res: dict) -> str:
    lines = [f"E0′ noise floor — {res['n_cases']} cases"]
    for level, l in res["levels"].items():
        d = l["outcome_disagreement"]
        fd = l["pending_field_disagreement_among_confirmed"]
        lines.append(f"  {level:9s} clusters={l['clusters']:4d} singletons={l['singletons']:4d} "
                     f"outcome-disagreement={'—' if d is None else f'{d:.3f}'} "
                     f"pending-field-disagreement={'—' if fd is None else f'{fd:.3f}'}")
        if "_benchmark" in l:
            b = l["_benchmark"]
            p = b["minority_flag_precision"]; r = b["minority_flag_recall_within_clusters"]
            lines.append(f"            [benchmark-only] true ρ={b['true_perturbation_rate']:.3f}  "
                         f"minority-flag precision={'—' if p is None else f'{p:.2f}'} recall={'—' if r is None else f'{r:.2f}'}")
    return "\n".join(lines)
