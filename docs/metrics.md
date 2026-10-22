# Metrics

What is measured, how it is defined, on which slice, and what decision it drives. Every metric is written as one row per `(epoch, aop_version, split, slice, bucket, metric, value, n)` so that curves can be drawn without re-running anything.

Splits: `dev`, `sealed`, `rolling` (new production cases never trained on). Slices: `signal`, `frontier`, `coverage`, `random` (`docs/selection.md` §4); `all` for the sealed set.

---

## 1. Primary — does the AOP get better?

| Metric | Definition | Split | Drives |
|---|---|---|---|
| **Floor pass rate** `p` | fraction of candidates with `floor = 1` | sealed, per bucket | The headline number. Deterministic, unexploitable. |
| **Quality** `q` | mean judge score J among floor-pass candidates | sealed, per bucket | Secondary; only meaningful when κ is adequate |
| **Mean reward** `r̄` | mean of r over all candidates | sealed, per bucket | The gate's objective |
| **Per-bucket success curve** | `p` by (complexity × completeness) bucket over epochs | sealed | The main figure. Shows where the frontier is and whether it moves. |
| **Best-of-k pass rate** | fraction of cases where ≥1 of k candidates passes the floor | dev | Upper bound on what selection could achieve; gap to `p` is the headroom for a better policy vs a better sampler |

Report `p` at the case level (mean over candidates) and at the group level (best-of-k) side by side. A rising best-of-k with flat `p` means the policy can do it but doesn't reliably — a playbook problem. Flat best-of-k means the policy can't — a structural problem.

---

## 2. Reward-model health — is the judge trustworthy?

All computed on the **uniform random slice only** (`docs/selection.md` §8). Numbers from the signal-driven slice are reported separately and labelled as tail estimates.

| Metric | Definition | Threshold / use |
|---|---|---|
| **Inter-operator κ** (E0) | Cohen's κ between two operators' independent verdicts on the same 30 cases | Ceiling for everything below. < 0.6 → fix the labeling protocol before building. |
| **Judge κ** | Cohen's κ between judge verdict (J ≥ 0.5) and operator verdict | ≥ 0.7 unlocks structural edits; < 0.6 restricts judge to within-group ranking only |
| **Brier score** | mean (J − y)², y ∈ {0,1} operator verdict | Lower is better; tracks calibration, not just agreement |
| **Reliability curve** | operator approval rate binned by J | Visual calibration check; a judge that says 0.9 should be right ~90% |
| **Goodhart gap** `G` | mean(J) − operator approval rate | **The E4 dependent variable.** Rising G over epochs = the policy is exploiting the judge. |
| **Per-bucket Goodhart gap** | G by bucket | Localizes exploitation |
| **Critic–judge agreement** | fraction of critic-flagged candidates the judge scores < 0.5 | Low agreement → one of them is miscalibrated; the operator verdict on that case says which |
| **Rubric coverage** | fraction of operator rationales matched by ≥1 rubric line | Low → rubric is missing concepts operators use |
| **Rationale rate** | fraction of operator verdicts that include a reason | < 0.8 → the question format is wrong; bare verdicts are nearly useless for curation |

---

## 3. Label efficiency — the whiteboard curve

The system's thesis is that improvement is label-bound, not compute-bound. These metrics make that visible.

| Metric | Definition |
|---|---|
| **Verifier cost** `C(t)` | cumulative `judge_tokens × price_judge + ops_verdicts × c_ops` through epoch t |
| **Accuracy vs verifier cost** | `p_sealed` plotted against `C(t)` |
| **Gain per operator verdict** | Δ `p_sealed` / Δ ops verdicts, cumulative |
| **Gain per judge call** | Δ `p_sealed` / Δ judge calls |

`c_ops` is a declared conversion (one operator verdict = N judge calls). It is a policy choice, not a measurement; report curves at three values (e.g. N = 50, 200, 1000) so the reader can see whether the conclusion depends on it.

For E4, plot one curve per ablation arm (± floor, ± group normalization, B ∈ {0, 25, 50, 100}). The arm with the lowest Goodhart gap at matched cost is the result.

---

## 4. Gate statistics

The gate decides accept/reject for candidate AOP' against the current accepted AOP_t. It must be honest about noise with ~150 sealed cases.

### 4.1 Noise floor

Estimated empirically, not assumed:

1. Run AOP_t on the sealed set twice with different seeds, k_gate candidates each.
2. Per case, compute Δ_c = mean reward(run 2) − mean reward(run 1).
3. Bootstrap the mean of Δ_c (10,000 resamples). The 95th percentile of |mean Δ| is the aggregate noise floor `η`.
4. Repeat per bucket for bucket-level floors `η_b` (wider, because n is smaller).

Re-estimate `η` whenever AOP_t changes; the variance of a policy is not constant.

### 4.2 Acceptance

AOP' is accepted iff all of:

| Test | Statistic | Criterion |
|---|---|---|
| Improvement | paired mean Δr over sealed cases, bootstrap 95% CI | lower bound > 0 and point estimate > η |
| Pass-rate change | McNemar on per-case best-of-k_gate pass/fail (discordant pairs) | not significantly worse at α = 0.05 |
| No-regression | per-bucket Δr | ≥ −η_b in every bucket |
| Cost | Δ tokens per case | `Δr / Δtokens ≥ λ`, or Δtokens ≤ 0 |
| Prediction | predicted-fixed cases | report hit rate; does not block acceptance but records a trust penalty if < 0.5 |

Why paired: the same 150 cases are evaluated under both AOPs, so per-case difficulty cancels. An unpaired 3-point gain on 150 cases is well inside noise; a paired comparison on discordant cases is far more sensitive.

### 4.3 Multiple-comparison drift

Every gate check reads the sealed set. Over many epochs this leaks. Mitigations, reported as metrics:

| Metric | Definition | Use |
|---|---|---|
| **Sealed reads** | number of gate evaluations against the current sealed set | Refresh the time split when it exceeds ~50 |
| **Sealed vs rolling gap** | `p_sealed − p_rolling` | Rising gap = overfitting the sealed set through repeated gating |

---

## 5. Edit and memory health

| Metric | Definition | Use |
|---|---|---|
| **Acceptance rate** | accepted / proposed candidate AOPs per epoch | Very low → proposals are noise; very high → gate is too loose |
| **Prediction accuracy** | fraction of accepted edits whose predicted-fixed cases actually flipped to pass, and predicted-unaffected cases did not change | The honesty check on the reflector/curator |
| **Edit half-life** | epochs until an accepted edit is reverted or its playbook line is pruned | Short half-life = churn |
| **Churn** | edits accepted then reverted, per 10 epochs | > 2 → tighten the gate or lower b_t |
| **Playbook size** | number of active lines; tokens | Growth without matching `q` gain → bloat; cost rule should catch it |
| **Line utility** | helpful − harmful counter per playbook/rubric line | Prune when negative over N epochs |
| **Edit-type mix** | share of accepted edits by type | Structural edits should be 0 until κ ≥ 0.7 |
| **Lesson support** | mean number of groups supporting an accepted lesson | Single-group lessons should never reach the gate |

---

## 6. Group and sampling diagnostics

| Metric | Definition | Use |
|---|---|---|
| **Zero-variance rate** | fraction of groups dropped for σ = 0 | High → sample from different buckets or raise T_sample |
| **Within-group spread** | mean `r_max − r_min` | Low everywhere = converged or collapsed |
| **Reply diversity** | mean pairwise embedding distance among candidates | Collapse detector |
| **Dedupe ratio** | judge calls saved / floor-pass candidates | Cost accounting |
| **Bucket occupancy** | cases judged per bucket per epoch | Coverage floor compliance |
| **Frontier drift** | which buckets are in [0.3, 0.7] over epochs | The frontier should move toward harder buckets |

---

## 7. Operational

| Metric | Definition |
|---|---|
| Tokens per case, by component | engine LLM nodes / critic / judge / reflector / curator |
| Wall-clock per epoch | sampling / judging / gating |
| Operator budget utilization | questions asked / B |
| Operator turnaround | median days from question to verdict |
| Escalation precision | fraction of escalated cases where the operator disagreed with the judge (the question was worth asking) |

---

## 8. Reporting layout

Per epoch, one page:

1. Per-bucket success curve (sealed), epochs on x, one line per bucket. Main figure.
2. Goodhart gap and judge κ over epochs, same x-axis, random slice only.
3. Accuracy vs verifier cost, one curve per ablation arm when E4 is running.
4. Gate table for this epoch (§4.2 columns, one row per candidate AOP).
5. Edit log delta: accepted / rejected edits with predictions.
6. Diagnostics strip: zero-variance rate, reply diversity, playbook size, sealed reads.

---

## 9. Targets for v1

These are gates, not predictions.

| Milestone | Criterion |
|---|---|
| Proceed past E0 | inter-operator κ ≥ 0.6 |
| Proceed past E1 | ≥ 95% of historical-reply figures reconcile with the snapshot |
| Proceed past E2 | ≥ 2 buckets with 0.2 ≤ p ≤ 0.8 (a frontier exists) |
| Unlock structural edits | judge κ ≥ 0.7 on the random slice, n ≥ 30 |
| E3 success | `p_sealed` improves by more than η in ≥ 2 buckets with no bucket regression, within 10 epochs |
| E4 result | Goodhart gap at matched verifier cost is lower with floor + group normalization than without, with non-overlapping bootstrap CIs |
