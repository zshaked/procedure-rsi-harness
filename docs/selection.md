# Selection policy — which cases get judged, and which get escalated

After a run, something has to decide which cases are worth the judge's time and, of those, which are worth an operator's. This document specifies that policy. It has a deterministic core (a scoring function) and a narrow agentic role (maintaining the failure-mode taxonomy and explaining selections).

See `DESIGN.md` §4 for the reward, §5 for buckets, §8.1 for the ops budget.

---

## 1. Two runs, two rules

| Run | Set | Selection? | Why |
|---|---|---|---|
| Regression run | Sealed (newest ~150) | **Never.** Judge every case, every candidate. | The gate is a paired comparison. Any selection on the sealed set biases it. ~150 × 2 AOP versions × k_gate candidates is the price of an honest gate. |
| Representative run | Dev (oldest ~250) | Yes | The judge's output here exists to produce *advantage* — a within-group ranking the reflector learns from. Judge where ranking changes what the curator would write. |

Everything below applies to the representative run only.

---

## 2. The funnel

```
all candidates (dev sample × k)
   │
   ▼  verifiable floor (deterministic, free)
floor-pass candidates
   │
   ▼  selection policy (§3–4)                    budget: judge calls per epoch
selected cases × selected candidates → JUDGE
   │
   ▼  uncertainty + disagreement ranking (§6)    budget: B ops questions per week
top-B cases → OPS
```

Each tier is a strict subset of the one before. Every selection is logged with its reason tags.

---

## 3. Signals computed before any judge call

All of these come from the floor, the critic, and string/embedding arithmetic. None require the judge.

| # | Signal | Computation | Effect |
|---|---|---|---|
| 1 | Floor fail | §4.1 checks | Reward is 0 by definition. Skip. Groups where every candidate fails are dropped (zero variance). |
| 2 | Reply divergence within group | Pairwise embedding similarity among floor-pass candidates | Near-identical (sim > τ_dup, default 0.95): judge one representative, propagate its score to the cluster. Divergent: judge all. |
| 3 | Distance from historical reply | Embedding + normalized edit distance between candidate and `historical_reply` | Floor-pass and near-identical to historical: score is predictable; sample 1-in-5. Floor-pass and materially different: either a legitimately different valid reply or a subtle error — exactly what the judge is for. Judge all. |
| 4 | Critic flag | Critic produced a plausible rejection reason | Judge, and record critic/judge agreement. The disagreement log is free calibration data. |
| 5 | Trajectory divergence | Tool-call sequence distance among candidates (edit distance on `(node, tool, canonical_args)` sequences) | Different sequences with similar replies, or same sequence with different replies, are where structural lessons live. Judge all. |
| 6 | Frontier weight | Bucket pass rate `p_b` from the floor | Weight ∝ `p_b (1 − p_b)`; peaks at 0.5, zero at 0 and 1. |
| 7 | Novelty | Distance from the nearest failure-mode cluster centroid (§5) | Outliers get weight; they are either new failure modes or new valid patterns, and the taxonomy needs to know which. |

---

## 4. Scoring and allocation

```
for case c in dev_sample:
    G = [cand for cand in candidates(c) if floor(cand)]
    if len(G) < 2: continue                          # nothing to rank
    s(c) = w2 * reply_divergence(G)
         + w3 * dist_from_historical(G)
         + w4 * critic_flag_rate(G)
         + w5 * trajectory_divergence(G)
         + w6 * frontier(bucket(c))
         + w7 * novelty(c)

ranked = sort(cases, by=s, desc)
selected = top_n(ranked, 0.50 * budget)              # signal-driven
         + frontier_sample(cases, 0.25 * budget)     # ∝ p_b(1 − p_b)
         + coverage_floor(cases, 0.15 * budget)      # ≥ n_min per bucket
         + uniform_random(cases, 0.10 * budget)      # audit slice, never skipped
for c in selected:
    dedupe(G_c, τ_dup)                               # one judge call per reply cluster
emit (case_id, candidate_ids, reason_tags, s(c))
```

Default weights: equal, normalized to [0, 1] per signal. Tune only after E3 shows which signals predicted large advantage gaps (§7).

The coverage floor is not optional: frontier sampling starves buckets at 0% or 100%, and without a minimum per bucket the per-bucket curve goes blind there and regressions in "easy" buckets are invisible until the gate catches them.

The uniform random slice is not optional either: it is the only part of the judged set that is not biased toward the hard tail. Judge calibration (kappa, Brier) is measured here and nowhere else (§8).

---

## 5. What is agentic, and what is not

Selection is a scoring function: deterministic, logged, reproducible. It has to be, because E4 ablates it.

The agent — call it the taxonomy agent — does three things, none of which is choosing cases by judgment:

1. **Maintains the failure-mode taxonomy.** Clusters floor-fail and low-advantage candidates by *why* they failed (wrong entity resolved, as-of date mis-resolved, missed escalation condition, premature confirmation, omitted pending quantity, …). This is a second taxonomy alongside complexity × completeness, and it is the more useful one for the reflector: lessons are per failure mode, not per bucket.
2. **Names new clusters.** When outliers (signal 7) accumulate past a threshold, proposes a new cluster with a label and a one-line description. Proposals are logged; a human can rename or merge.
3. **Writes reason tags.** Each selected case gets a one-line explanation of which signals fired. Tags are for the audit trail and for the ops question (the operator sees why this case was chosen).

Cluster assignments carry provenance (candidate ids) like everything else in memory.

---

## 6. From judged to escalated

After the judge runs on the selected set, rank judged cases by:

```
u(c) = judge_uncertainty(c)        # spread of sub-scores, stated confidence
     + critic_judge_disagreement(c)
     + within_group_advantage_spread(c)   # large gap between best and worst floor-pass
     + frontier(bucket(c))
```

Take the top B (default 5 per week). Each ops question is one concrete case, one candidate reply (the highest-advantage one, or the disputed one when critic and judge disagree), yes/no, and one sentence of reason.

Every answer:
- becomes a rubric delta with provenance (`DESIGN.md` §4.2),
- joins the audit set used for kappa **only if the case came from the uniform random slice** — otherwise it is used for rubric curation but excluded from calibration statistics (§8).

---

## 7. Output schema

```json
{
  "epoch": 12,
  "aop_version": "v0.1.12",
  "split": "dev",
  "selected": [
    {
      "case_id": "c_0417",
      "candidate_ids": ["c_0417.k3", "c_0417.k5", "c_0417.k7"],
      "score": 0.81,
      "reason_tags": ["reply_divergence", "critic_flag", "frontier"],
      "bucket": {"complexity": 2, "completeness": "partial"},
      "failure_cluster": "omitted_pending_quantity",
      "slice": "signal"
    },
    {
      "case_id": "c_0102",
      "candidate_ids": ["c_0102.k1"],
      "score": null,
      "reason_tags": ["uniform_random"],
      "bucket": {"complexity": 1, "completeness": "complete"},
      "failure_cluster": null,
      "slice": "random"
    }
  ],
  "escalated": [
    {"case_id": "c_0417", "candidate_id": "c_0417.k3", "u": 0.74,
     "question": "Is this reply acceptable? One sentence on why or why not.",
     "reason_tags": ["critic_judge_disagreement"]}
  ]
}
```

`slice` is what lets the metrics code separate calibration-eligible cases from the rest.

---

## 8. The calibration trap

The selected set is the hard, ambiguous tail by construction. Measuring judge kappa on it gives a pessimistic number, and curating the rubric only from ops answers on it drifts the rubric toward hard-case rules and miscalibrates the judge on ordinary cases.

Rules:
- Kappa, Brier, and the Goodhart gap (`docs/metrics.md` §2) are computed on the uniform random slice only.
- Rubric curation uses every ops answer, but each rubric line records which slice its evidence came from. A line supported only by tail cases is flagged for review before it is applied to frontier sampling weights.
- The random slice is 10% of judge budget and at least 2 of the B weekly ops questions.
