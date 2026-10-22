# How the RL pieces work

The harness is RL-shaped: environment, policy, reward, reward model, advantage, update, trust region, active learning. None of it touches model weights in v1. This document says exactly what each piece is, what it buys, and where the analogy stops.

The one-line version: it is GRPO where the group-relative signal survives, the gradient step is replaced by contrastive reflection into typed, auditable edits, and the KL penalty is replaced by an edit budget plus a sealed held-out gate.

---

## 1. Mapping

| RL piece | GRPO | Here | What it buys |
|---|---|---|---|
| Environment | Prompt → episode | `(email, sor_snapshot)` → execution | Replayable: the same case can be rolled out k times against identical state |
| Policy π_θ | LLM weights | AOP_t = (graph G, prompts P, playbook B, template T) | Parameters are text and structure; every change is a readable diff |
| Rollout τ | Token sequence | Trajectory: `[(node, tool, args, result, llm_output)…]` → reply + outcome class | Inspectable; the reflector reads it |
| Reward r | Verifier / RM score | Lexicographic: floor → judge (§3) | Unexploitable floor, graded top |
| Reward model | Trained RM | Judge = prompted model + evolving rubric | Trainable from ~tens of labels, auditable |
| Advantage A | (r − μ_group) / σ_group | Same | Cancels per-case difficulty and per-case judge bias |
| Update | ∇ log π weighted by A | Reflector contrast → Curator typed edit | A "textual gradient": the direction is read off the contrast, the step is a bounded edit |
| Trust region | KL(π_θ ‖ π_ref) ≤ δ | Edit budget b_t + sealed gate + no-regression per bucket + cost rule | Bounded steps; rejected steps leave the policy unchanged |
| Reference policy | π_ref | AOP_0 and AOP_t | Every gate decision is paired against the current accepted version |
| RM training | Pairwise preference loss | Rubric curation from ops verdicts + rationales | Comparative labels (vs historical reply), not absolute scores |
| Active learning | — | Escalation policy under budget B | Spends human labels where the RM is uncertain, not where the policy is |

Where the analogy stops: there is no unbiased gradient estimator. The reflector/curator step is a heuristic proposal; the outer loop is accept/reject hill-climbing on a held-out fitness (as in Procedural Graphs and RRSI). Monotonic improvement on the sealed set is guaranteed by the gate, not by the proposal mechanism.

---

## 2. Environment and policy

**Case.** `c = (email, historical_reply, sor_snapshot, t_reply)`. The snapshot is the SOR state at `t_reply`. E1 verifies this; if the snapshot is current-state rather than point-in-time, the environment is invalid and nothing downstream holds.

**Episode.** The fixed engine executes AOP_t on `c`. LLM nodes are sampled at temperature `T_sample` (default 0.7); tool calls hit the frozen snapshot through the MCP adapter. An episode ends with a reply and an outcome class ∈ {confirmed, not confirmed, escalate, request info}.

**Group.** k episodes of the same AOP_t on the same case (default k = 8). Fan-out via the engine's Send API; candidates are independent. If all k replies are near-identical the group carries no signal — raise `T_sample` for that bucket or treat it as converged.

**Policy parameters.** Four editable surfaces, each with its own edit grammar (`DESIGN.md` §6.3). The engine itself is not a parameter.

---

## 3. Reward

```
floor(τ) ∈ {0, 1}       deterministic checks against snapshot + historical reply
J(τ)     ∈ [0, 1]       judge aggregate over rubric sub-scores
r(τ)     = 0                         if floor(τ) = 0
         = ε + (1 − ε) · J(τ)        otherwise        (ε = 0.05)
```

ε keeps every floor-pass candidate strictly above every floor-fail candidate, so the ordering is lexicographic even when the judge scores a floor-pass reply at 0.

**Why lexicographic.** The judge is learnable and therefore exploitable. The floor is not: it is code that checks identifiers, figures, dates, and outcome class against ground truth. A policy that learns to charm the judge still scores 0 if it gets a figure wrong. This is the single most important regularizer in the system.

**Why graded.** A binary reward makes most groups all-pass or all-fail, which gives zero variance and no advantage. Rubric sub-scores (default: entity completeness, figure completeness, outcome correctness, required caveats, tone/format) give the within-group ordering the reflector needs.

**Judge inputs.** Email, snapshot, historical reply, candidate reply, critic output. The judge always sees the historical reply: it is asked "is the candidate an acceptable alternative to this?", not "rate this reply." Comparative judgments are more stable.

---

## 4. Advantage

Within a group of k candidates with rewards r_1…r_k:

```
μ = mean(r),  σ = std(r)
A_i = (r_i − μ) / (σ + 1e-6)
```

**What normalization does and does not do here.**

- *Within* a group, A is a monotone transform of r. Selecting top-m / bottom-m candidates for the reflector does not depend on normalization at all.
- *Across* groups, normalization matters. It makes "this candidate was the best of its group" comparable between an easy case and a hard case, and it cancels per-case judge bias: a judge that is harsh on one case is harsh on all k candidates of that case, and the ranking survives.
- Dr. GRPO's objection applies: dividing by σ up-weights low-variance groups. We use σ-normalized A only for cross-case comparisons of *which lessons to prioritize*; for the curator's evidence weighting we use the raw spread `r_max − r_min` of the group, because a group with large spread is one where the edit matters more.

**Dynamic sampling (DAPO).** Groups with σ = 0 are dropped before reflection. Cases are drawn preferentially from buckets where the floor pass rate is near 0.5, because that is where groups have variance (`docs/selection.md` §3, signal 6).

---

## 5. The update: reflection → curation

In GRPO the update is `θ ← θ + η · Σ_i A_i ∇_θ log π_θ(τ_i)`: probability mass moves toward high-advantage trajectories. The textual analogue has two halves.

### 5.1 Reflector — reading the direction

For each group, the reflector sees two contrasts, and they teach different things:

| Contrast | Teaches | Typical edit type |
|---|---|---|
| Floor-pass top-m vs floor-pass bottom-m | Business-rule and communication quality: what the better replies included, checked, or phrased | `playbook.*`, `template.edit`, `prompt.edit` |
| Floor-pass vs floor-fail | Grounding and traversal errors: wrong entity, wrong as-of date, missed escalation condition | `prompt.edit` on the offending node; `graph.rebind_arg`, `graph.*` (locked until κ ≥ 0.7) |

The reflector's output is a *lesson*, not an edit: a one-line claim about what distinguished winners from losers, the trajectory evidence (candidate ids, the specific node or step where they diverged), and a confidence.

### 5.2 Curator — taking the step

The curator aggregates lessons across groups within an epoch. This is the analogue of summing the gradient over a batch:

- The same lesson appearing in several groups with consistent sign and large spread is high-confidence. Advantage-weighted vote count is the evidence score.
- A lesson that appears once is held in `questions/` as a hypothesis, not applied.
- The curator consults the edit library: a lesson that led to a previously rejected edit is not redrawn in the same form (RRSI's "proposer conditioned on edit history").

Each accepted lesson becomes a typed edit with a prediction: which case ids it should fix, which it should leave unchanged. The prediction is what makes the edit falsifiable at the gate and verifiable in later epochs.

### 5.3 Step size

The edit budget `b_t` is the learning rate. Default: `b_0 = 2` edits per candidate AOP, annealed toward 1 over the first ~10 accepted epochs. Early, the AOP is far from good and big steps are cheap to evaluate; later, the accepted AOP is valuable and a two-edit candidate that regresses tells you less about which edit was at fault.

Candidates are composed (Harness² "compose"): several single-edit candidates are gated independently; those that pass are combined into one composed candidate and gated again, because edits that help alone can conflict together.

---

## 6. Trust region: the gate

GRPO's KL term keeps π_θ near π_ref. Here the constraint is enforced by rejection rather than penalty:

1. **Paired evaluation on the sealed set.** AOP' and AOP_t are both run on every sealed case with k_gate candidates (default 4). Per case, the comparison is mean reward over candidates. No selection on the sealed set, ever.
2. **Noise floor.** The null distribution of the paired difference is estimated by running AOP_t against itself with different seeds (`docs/metrics.md` §4). Acceptance requires the observed mean Δ to exceed the 95th percentile of the null.
3. **No-regression per bucket.** No (complexity × completeness) bucket may fall by more than the bucket-level noise floor.
4. **Cost rule.** Added tokens per case must be paid for: `Δ reward / Δ tokens ≥ λ` (λ set from the current accepted AOP's efficiency).
5. **Prediction check.** The edit's predicted-fixed cases are checked. An edit that passes on aggregate but fixes none of what it claimed to fix is accepted with a trust penalty recorded against its lesson source.

Rejected candidates leave AOP_t unchanged and are logged with the reason. The outer loop is therefore a (1+λ)-style evolutionary strategy with a held-out fitness: proposals come from a learned direction, selection is by the gate.

---

## 7. Reward model: the judge

The judge is the reward model. Its "weights" are the rubric; its "training" is curation from operator verdicts.

**Objective.** Predict `P(ops approves candidate | email, snapshot, historical reply)` and the reason. The target is the operator's yes/no plus one sentence.

**Training signal.** Each operator answer becomes a rubric delta (ACE-style): add a line, strengthen or weaken an existing line's weight, retire a line. Lines carry helpful/harmful counters updated by whether their application agreed with later operator verdicts. Provenance is the verdict id.

**Calibration.** Cohen's κ against operator verdicts on the uniform random audit slice (`docs/selection.md` §8), plus Brier score of J against yes/no. `κ ≥ 0.7` unlocks structural edits. Below ~0.6 the judge should not be used for anything but ranking within groups.

**Ceiling.** The judge cannot agree with operators more than operators agree with each other. E0 measures inter-operator κ first. If it is low, the fix is the labeling protocol (reasons, not bare verdicts), not the judge.

**The critic.** An asymmetric adversary: its only job is to find the reason an operator would reject the candidate, with SOR access so it fact-checks rather than style-checks. It runs before the judge and its output is a judge input. This is not a symmetric game — the judge's objective stays "agree with ops", never "catch the proposer" — because a symmetric game has no external anchor and a judge rewarded for rejecting rejects everything. Use different model families for critic and judge where possible; shared priors mean shared blind spots.

---

## 8. Goodhart: what the policy will try, and what stops it

Any learned reward gets exploited. Expected signatures and the mechanism that catches each:

| Exploit | Signature | Caught by |
|---|---|---|
| Charm the judge while being wrong | Judge score ↑, floor pass rate flat or ↓ | Lexicographic floor: reward is 0 regardless |
| Echo rubric language in replies | Replies contain rubric phrasing; length ↑ | Operator audit on random slice; Goodhart gap widens; cost rule on tokens |
| Exploit a judge blind spot on one case type | Judge score ↑ in one bucket, operator audit flat there | Per-bucket Goodhart gap; rubric refresh from those audits |
| Over-hedge (always escalate) | Outcome class mismatch on confirmed cases | Floor: outcome class is a deterministic check |
| Overfit the dev set | Dev ↑, sealed flat | Gate; rolling production held-out |
| Overfit the sealed set via repeated gating | Sealed ↑ while rolling held-out flat | Rolling held-out from new production cases; time split refreshed periodically |

The Goodhart gap — `mean(J) − operator approval rate` on the random audit slice, over epochs — is the single metric that says whether the reward model is being gamed. It is the dependent variable of E4.

---

## 9. Active learning

The escalation policy (`docs/selection.md` §6) spends the weekly operator budget to improve the *reward model*, not the policy. This is the inverse of the usual RL emphasis and it is deliberate: with a calibrated judge, policy improvement is cheap and automatic; with a miscalibrated judge, every policy step is optimizing noise. The operator budget is the scarcest resource in the system and it goes to the judge first.

---

## 10. What is in weights, and when

| Version | Judge | Proposer / policy | Why |
|---|---|---|---|
| v1 | Prompted + rubric | Text + structure edits | ~400 cases, tens of operator labels. Nothing else is trainable at this scale. Auditable by construction. |
| v2 | Supervised fine-tune on accumulated verdicts + rationales | Unchanged | Once there are ~1k+ verdicts, a small fine-tuned judge is cheaper per call and stabler than a long rubric. Still supervised, still auditable via held-out verdicts. |
| v3 | As v2 | Possibly policy-gradient on LLM nodes | Only with a calibrated judge and thousands of labeled episodes. Weight-level self-improvement is explicitly out of scope until then; on 400 cases with a noisy judge it would overfit the judge in a few epochs. |

---

## 11. Worked example

One case, one group, one epoch. Figures are illustrative.

**Case c_0417.** Email asks to confirm the holding in instrument X for account Y as of date D. Snapshot at `t_reply`: 10,000 units settled, 2,000 units pending settlement, expected D+2. Historical reply: "Confirmed: 10,000 settled as of D. 2,000 further units pending, expected to settle D+2." Outcome class: confirmed. Bucket: complexity 2 (two entities, one lookup each), completeness: complete.

**Eight candidates.**

| id | Reply (abbreviated) | Floor | J | r | A |
|---|---|---|---|---|---|
| k1 | Confirmed 12,000 as of D | ✗ figure | — | 0.00 | −1.20 |
| k2 | Confirmed 10,000 as of D | ✓ | 0.55 | 0.57 | +0.34 |
| k3 | Confirmed 10,000 settled; 2,000 pending, exp. D+2 | ✓ | 0.92 | 0.92 | +1.29 |
| k4 | Confirmed 10,000 settled as of D; 2,000 pending (D+2) | ✓ | 0.90 | 0.91 | +1.24 |
| k5 | Unable to confirm — please provide the account number | ✗ outcome | — | 0.00 | −1.20 |
| k6 | Confirmed 10,000 settled; 2,000 pending; "no further action expected" | ✓, critic flag (unverified claim) | 0.70 | 0.72 | +0.73 |
| k7 | Confirmed 10,000 as of email date | ✗ date | — | 0.00 | −1.20 |
| k8 | Confirmed 10,000 as of D | ✓ | 0.50 | 0.53 | +0.21 |

μ ≈ 0.46, σ ≈ 0.37. Group has variance; it is kept.

**Reflector, contrast 1** (floor-pass top-2 {k3, k4} vs floor-pass bottom-2 {k8, k2}):
> Lesson L1: winners reported settled and pending quantities separately with the expected settlement date; losers reported settled only. Evidence: k3, k4 vs k2, k8; historical reply includes pending. Confidence: high.

**Reflector, contrast 2** (floor-pass vs floor-fail):
> Lesson L2: k7 resolved the as-of date from the email's send timestamp rather than the date requested in the body. Evidence: trajectory k7, node `resolve_as_of_date`, arg `as_of = email.sent_at`. Confidence: high.
> Lesson L3: k5 failed to resolve account Y from the sender's signature block. Evidence: trajectory k5, node `resolve_account`. Confidence: medium (single candidate).
> Lesson L6: k6 added a forward-looking claim not supported by the snapshot. Evidence: critic output. Confidence: medium.

**Curator.** L1 appeared in 6 other groups this epoch with consistent sign and mean spread 0.38 → high evidence. L2 appeared in 3 groups → high. L3 once → held in `questions/`. L6 twice → medium, combined with a similar lesson from c_0388.

Edits emitted (b_t = 2, so two candidate AOPs, one edit each, plus a composed candidate):

```yaml
- id: e_0112
  type: playbook.add
  text: "When confirming a position, report settled and pending quantities separately. If pending > 0, state the expected settlement date."
  rationale: L1
  predicts_fixed: [c_0417, c_0388, c_0291, c_0355, c_0402, c_0219, c_0433]   # cases where historical reply mentions pending and ≥1 candidate omitted it
  predicts_unaffected: [cases with pending = 0 in snapshot]
  evidence: {lessons: [L1], candidates: [c_0417.k3, c_0417.k4, ...]}

- id: e_0113
  type: prompt.edit
  node: resolve_as_of_date
  text: "The as-of date is the date the sender asks about, stated in the email body. Use the send timestamp only if no date is stated, and say so in the reply."
  rationale: L2
  predicts_fixed: [c_0417, c_0130, c_0301]
  predicts_unaffected: [cases where body date == send date]
  evidence: {lessons: [L2], candidates: [c_0417.k7, c_0130.k2, c_0301.k6]}
```

L2 could also be expressed as `graph.rebind_arg` on `resolve_as_of_date` (bind `as_of` to the body-extracted date rather than `email.sent_at`). That is a structural edit and is locked until κ ≥ 0.7; the prompt edit is the v1 form.

**Gate.** Each candidate AOP is run on the sealed set with k_gate = 4, paired against AOP_t.

| Candidate | Mean Δr | Null 95th pct | Bucket regressions | Δ tokens/case | Predicted-fixed hit rate | Decision |
|---|---|---|---|---|---|---|
| AOP_t + e_0112 | +0.041 | 0.018 | none | +3% | 6/7 | accept |
| AOP_t + e_0113 | +0.022 | 0.018 | none | +1% | 3/3 | accept |
| AOP_t + both | +0.058 | 0.018 | none | +4% | — | accept → AOP_{t+1} |

Both edits are logged with their predictions. Next epoch, the predicted-unaffected sets are checked; if e_0112 changed replies on pending = 0 cases, its lesson source gets a trust penalty.

---

## 12. Hyperparameters

| Name | Default | Notes |
|---|---|---|
| k | 8 | Candidates per case in the representative run |
| k_gate | 4 | Candidates per case at the gate |
| T_sample | 0.7 | Raise per bucket if groups converge |
| m | 2 | Top/bottom candidates per contrast |
| ε | 0.05 | Floor-pass offset in r |
| b_0 → b_T | 2 → 1 | Edit budget, annealed over ~10 accepted epochs |
| τ_dup | 0.95 | Reply similarity for dedupe |
| Frontier window | p_b ∈ [0.3, 0.7] | Preferred sampling range |
| Noise floor | 95th pct of null Δ | From AOP_t vs AOP_t with different seeds |
| λ (cost rule) | efficiency of AOP_t | Δr / Δtokens must not fall below it |
| κ_struct | 0.7 | Unlocks structural edits |
| B | 5 / week | Operator questions; ≥ 2 from the random slice |
| Judge budget | 40% of floor-pass candidates | Per epoch, representative run |
