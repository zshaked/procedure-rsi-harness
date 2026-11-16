# Why the loop descends without a gradient

`docs/rl.md` maps the harness onto GRPO and says where the analogy stops: there is no unbiased gradient estimator, and monotone improvement comes from the gate, not from the proposal mechanism. This document takes that one sentence seriously, because it is the question a reviewer asks first:

> In gradient descent the gradient always points downhill, so you know how to move the weights. Here a text proposer plays the role of the gradient, and nothing says its proposals point downhill. How do you guarantee the loop reduces the loss, and what is the memory that carries the descent from one step to the next?

The short answer: the proposer is not the gradient and was never going to be. It is a mutation operator. Descent is enforced by the accept/reject gate, which gives a guarantee on the gate's own set; a separate, weaker guarantee covers the distribution the set was drawn from; and "maximal descent" is not well-defined over harness edits, but several relative guarantees are available and one of them — a boosting-shaped bound under a target-then-fix schedule — is strong enough to be worth building around.

Notation follows `DESIGN.md` and `docs/rl.md`: AOP_t is the accepted policy after t gate decisions; r(τ) is the lexicographic reward; S_val is the search-validation set (the gate's set, called "sealed" in older sections); η is the empirical noise floor from `docs/metrics.md` §4.1.

---

## 1. What kind of optimizer this is

Gradient descent needs three things the harness does not have: a continuous parameter space, a differentiable objective, and a metric on parameter perturbations that makes "direction" and "steepest" meaningful. The policy here is (graph, prompts, playbook, template): discrete, structured text. The objective is a black-box evaluation. There is no inner product between "add a playbook line" and "tighten a node's instruction."

So the loop is derivative-free optimization. Specifically, it is a (1+λ) evolution strategy with a held-out fitness: λ candidate policies are generated from the current one, each is evaluated against the parent on the same cases, and the best survivor that clears the gate replaces the parent. The reflector/curator pair is the mutation distribution; the gate is selection.

Two consequences follow immediately and should be stated to anyone who asks the gradient question.

1. **The direction is heuristic; the acceptance is exact.** In gradient descent the direction is informed and the step is taken unconditionally. Here the direction is a guess and the step is taken only after measurement. The guarantee has moved from the proposal to the gate.
2. **Proposer quality sets the convergence rate, not correctness.** A random proposer is random search: it still descends under the gate, slowly. An informed proposer — one conditioned on within-group contrast and on the edit history — descends faster. Whether it is informed is measurable (§6), not assumed.

ProTeGi, TextGrad, and OPRO all call the proposal a "textual gradient." The metaphor is useful for intuition and should not be used in a guarantee. Trace / OPTO is the one framing in the literature that treats feedback as a generalization of a first-order oracle with care about what is and is not inherited.

---

## 2. What the gate guarantees

### 2.1 Monotone descent on the gate's set

Define the measured loss of a policy on S_val as

```
L̂(π) = (1/|S_val|) · Σ_{c ∈ S_val} (1 − r̄_π(c))
```

where r̄_π(c) is the mean reward over k_gate candidates on case c.

**Proposition 1.** If AOP' replaces AOP_t only when the paired improvement on S_val exceeds the noise floor η (`docs/metrics.md` §4.2), then L̂(AOP_t) is non-increasing in t, and every accepted step decreases it by more than η in measurement.

This is immediate from the acceptance rule and is in one respect stronger than gradient descent, where a finite step can overshoot and increase the loss. It is also the whole content of "we know we are going downhill": the gate measures the hill.

What it does not say: that the *true* loss on S_val decreased. The measurement has sampling noise from k_gate rollouts and judge noise. The noise floor is calibrated so a false accept has probability about α per gate decision; over T accepted epochs roughly αT of them are noise. `docs/metrics.md` §4.3's sealed-vs-rolling gap is the metric that shows those accumulating.

### 2.2 Descent on the distribution, not just the set

The loss that matters is on the case distribution D, not on S_val. Non-adaptively — k candidate policies fixed in advance, compared once each on n cases — uniform convergence gives an error of order √(log k / n). The loop is not non-adaptive: every proposal depends on previous gate results, because the curator conditions on the edit library. Under adaptive querying the worst-case error grows like √(k / n), as though each query needed fresh data. After enough gate reads on the same S_val, the loop can be descending L̂ while ascending L_D.

This is the known failure of tuning on a validation set through model selection (Dwork et al.'s adaptive-data-analysis setting; Recht et al.'s ImageNet replication). The design already carries the mitigations:

| Mechanism | Where | What it buys |
|---|---|---|
| Noise-floor threshold on the paired Δ | `metrics.md` §4.2 | A crude Thresholdout: answers below the threshold reveal nothing about S_val |
| Sealed-reads counter, refresh at ~50 | `metrics.md` §4.3 | The budget accounting Thresholdout needs |
| Four disjoint data roles; final test touched once | `DESIGN.md` §7 | An estimate of L_D the loop cannot have fit |
| Rolling held-out from new production cases | `rl.md` §8 | A fresh sample every period; the gap against S_val is the overfitting signal |
| Edit budget b_t annealed toward 1 | `rl.md` §5.3 | Small steps: fewer degrees of freedom per accepted edit |

The honest statement for a reviewer: descent on S_val is guaranteed by construction; descent on D is guaranteed only as far as the rolling held-out confirms it, which is the same position every supervised model is in.

### 2.3 The loss is an estimate from a learned judge

One place the harness is weaker than gradient descent, not just different: in supervised learning the loss is exact. Here the graded component of r is a judge that is itself learned, so Δ has bias as well as variance. A biased oracle lets the loop descend the proxy and ascend the objective. The lexicographic floor (`rl.md` §3), the frozen-during-epoch judge, the Goodhart gap on the random audit slice (`rl.md` §8), and the judge-free floor pass rate as a parallel metric exist for exactly this reason. None of §2.1 holds if the judge drifts while the gate is reading it.

---

## 3. Memory

The question's second half — "what memory carries the descent?" — has two answers, and the loop needs both.

**State.** AOP_t itself: accepted edits persist in the graph, prompts, playbook, and template, and playbook lines carry helpful/harmful counters. This is the analogue of the weights.

**Optimizer memory.** The edit library (`DESIGN.md` §9): every proposed edit with its rationale, prediction, gate outcome, and realized effect. The curator conditions on it. Without it the proposer re-proposes rejected edits and the search is a memoryless random walk. With it:

- rejected edits are not redrawn in the same form — a tabu list;
- lessons that recur across epochs with consistent sign accumulate evidence — the analogue of momentum, a direction that has held up over several steps gets weight;
- predictions that failed lower the curator's trust in similar edits (`DESIGN.md` §7, decision observability) — a crude second-order correction.

OPRO keeps its optimization trajectory in the optimizer's context for the same reason. RRSI conditions the proposer on edit history for the same reason. This is not an optional logging feature; it is the second of the two things that make the loop an optimizer rather than a sampler.

---

## 4. "Maximal descent" and what can replace it

The natural follow-up is whether the loop can be made to take not just a descending step but the *most* descending step available. It cannot, in the sense the question intends, and the reason is structural rather than a design gap.

Steepest descent is defined relative to a norm on the tangent space. Harness edits have no tangent space and no canonical norm. There is no fact of the matter about whether "add a precondition to node X" is a smaller or larger perturbation than "retire playbook line Y," so "the direction of maximal decrease" is not a well-posed object. Separately, for a black-box objective over a discrete space, certifying that a step is the best in a neighborhood requires evaluating every neighbor; nothing cheaper is available without structure.

What can be guaranteed is always relative to something. Four options, in order of strength:

**4.1 Best of the sampled neighborhood.** Generate N candidate edits, evaluate all, take the best. This guarantees maximal descent *over the N sampled*. It is what the per-epoch candidate set and the compose step already do (`rl.md` §5.3). Cost is N gate evaluations; racing reduces it — evaluate all N on the target bucket's cases first, drop the bottom half, repeat, and only survivors reach the full gate. Successive halving gives the best of N with probability 1 − δ at a fraction of the evaluations.

**4.2 Exhaustive neighborhood.** Define the neighborhood finitely — every `playbook.add` from the current lesson pool, every `playbook.retire` of a line with negative counters — and evaluate every member. This is discrete steepest descent and a true guarantee within the neighborhood. It is feasible when the pool is small and rollouts are cached, which is the v1 regime (typed edits, playbook-first), and infeasible once structural edits unlock.

**4.3 Surrogate with regret bounds.** Fit a cheap model from edit features to predicted Δ and optimize over it, as DSPy's MIPROv2 does over instruction candidates. Bayesian-optimization regret bounds exist but assume kernel smoothness that text edits do not satisfy cleanly. Useful in practice; weak as a theorem. The edit library's prediction records are the training data for such a surrogate, which is another reason to keep them.

**4.4 Submodularity.** The one real theorem available. Treat the playbook as a set of lines and the objective as floor-pass coverage: the number of cases a policy handles correctly as a function of which lines are present. Coverage functions are the canonical monotone submodular objective, and for monotone submodular maximization greedy — always add the element with the largest marginal gain — is within (1 − 1/e) ≈ 0.63 of the optimal set (Nemhauser, Wolsey, Fisher 1978). Under a precision constraint the problem becomes constrained submodular maximization, which still admits constant-factor greedy guarantees.

That is a bound on the *trajectory*, not on one step, and the greedy algorithm it certifies is the one the loop runs anyway. The assumption is diminishing marginal returns, which fails when lines *interfere* — when adding one changes how another applies. The design has a direct interference detector: every edit's `predicts_unaffected` set, checked at the gate and in later epochs. A rising rate of predicted-unaffected cases that changed is a measured violation of submodularity, and the per-bucket no-regression rule bounds its damage. Narrow, well-scoped lines keep interference small, which means the choices that make the playbook auditable are the same choices that make the theorem closer to true.

---

## 5. Target-then-fix, and a boosting-shaped bound

Section 4 is about selecting among proposals. The sharper version of the question is whether the *generation* step can be made to produce the most-reducing proposal. For an LLM proposer, no: it emits a sample, not an argmax, and it sees the loss only through the reflector's summary. The way to get a guarantee is to split proposing into a part that can be exactly optimal and a part that reduces to selection.

### 5.1 Targeting is exactly solvable

The loss decomposes over cases. The reflector already attributes each failure to a lesson with evidence; extend that to a two-level failure taxonomy — a fixed top level (wrong field extraction, wrong node or tool selected, wrong arguments, precondition missed, unsafe side effect, should have escalated, over-escalated) with domain-specific leaves induced underneath. For bucket b, define the failure mass

```
m_b = Σ_{c attributed to b} (1 − r̄(c))
```

so that L̂ = Σ_b m_b + (unattributed). Then m_b is an *upper bound* on the loss any edit confined to bucket b can remove, and b* = argmax_b m_b is the most-reducing target given the attribution. This is coordinate descent in which the per-coordinate derivative is read directly off the failure histogram. No heuristic is involved beyond the attribution itself.

### 5.2 Fixing is best-of-N

For b* only, the curator proposes N candidate edits. Narrowing matters: "improve the harness" is open-ended generation with a low hit rate; "these 23 cases fail because precondition X is missed at node Y — here are the trajectories" is a constrained task with a high one. Race the N on b*'s cases, confirm survivors on the full S_val (which is where interference with other buckets shows up), accept the best if it clears the gate. Record

```
fix efficiency  e_t = realized Δ / m_{b*}
```

which is the number that says whether the proposer is earning its keep.

### 5.3 The bound

**Proposition 2 (geometric descent under a weak-proposer assumption).** Let B be the number of top-level buckets with positive mass. Suppose that in every epoch the accepted edit removes at least a fraction γ ∈ (0, 1] of the targeted bucket's mass, and that no other bucket's mass increases. Then

```
L̂_{t+1} ≤ L̂_t − γ · m_{b*} ≤ L̂_t − (γ / B) · L̂_t = (1 − γ/B) · L̂_t
```

since the largest of B buckets holds at least L̂_t / B. Hence L̂_t ≤ (1 − γ/B)^t · L̂_0.

With gate noise the no-regression condition holds only up to η_b per bucket, which adds at most (B − 1) η to the right-hand side each epoch. The recursion then converges not to zero but to a floor of order B(B − 1) η / γ. Two design implications fall out: keep the top-level taxonomy small (B appears squared), and buy down η with k_gate rather than tolerating a wide floor.

The shape is AdaBoost's: target the current residual, require only an edge from each round, get geometric decrease of the training error. The assumption is on the proposer and it is weak — any positive edge — and it is measured every epoch as e_t, so the bound is live rather than asserted. Together with §4.4, this is as close to "guaranteed maximal descent" as the problem admits: optimal targeting, best-of-N fixing with a measured edge, and near-optimality of the greedy sequence when interference is small.

### 5.4 What breaks it

| Failure | Effect on the bound | Detected by |
|---|---|---|
| Attribution error — the reflector assigns failures to the wrong bucket | Targeting is optimal relative to a wrong map; m_{b*} is not an upper bound | Hand-label a sample of attributions each epoch; track attribution accuracy alongside judge κ |
| Interference — fixing b* changes outcomes in other buckets | Masses are not additive; the no-regression term grows | `predicts_unaffected` violations; per-bucket Δ at the gate |
| Edge collapses — e_t → 0 on the top bucket | Descent stalls | The stall itself. It means the fix is not an edit the proposer can write from the seed it has: route the bucket to the operator questionnaire (`docs/selection.md`) rather than drawing more samples |
| Judge drift during an epoch | Δ is biased; every proposition above is about the proxy | Goodhart gap; floor pass rate diverging from judge score (`rl.md` §8) |

---

## 6. What to measure to make the argument empirical

Everything above becomes a claim about this system rather than a general one once these are reported per epoch:

| Metric | What it tests |
|---|---|
| Acceptance rate | Is the proposer better than random? Random search accepts at a low, flat rate |
| Rank correlation between predicted and realized Δ across the N candidates | Is the proposer *informed* — does it know which of its own proposals is best? |
| Fix efficiency e_t | The edge in Proposition 2 |
| `predicts_unaffected` violation rate | Interference; the submodularity assumption in §4.4 |
| Attribution accuracy on a labeled sample | The map Proposition 2 depends on |
| Sealed-vs-rolling gap, sealed-reads count | The §2.2 generalization gap |
| Goodhart gap | Whether the loss being descended is the real one |

---

## 7. The answer in one paragraph

The proposer is a mutation operator, not a gradient; nothing about it is assumed to point downhill. Descent is enforced by the gate: an edit is kept only if its paired improvement on the search-validation set clears an empirically estimated noise floor, which makes the measured loss on that set monotonically non-increasing by construction. Memory is the accepted policy (state) plus the edit library the proposer conditions on (optimizer memory: a tabu list and an evidence accumulator). Generalization from the gate's set to the live distribution is not guaranteed and is the same problem every validated model has; it is handled with disjoint data roles, a read budget on the validation set, and a rolling held-out. "Maximal descent" is not well-defined over harness edits, but best-of-N selection with racing gives the best step among sampled candidates, and a target-then-fix schedule — attack the failure bucket with the largest mass, propose only for it, accept only with a measured edge — yields geometric decrease of the validation loss under a weak-proposer assumption that is itself measured every epoch. When the edge on the top bucket goes to zero, the missing piece is knowledge, not search, and the case goes to a human.

---

## References

- Pryzant et al. 2023 — Automatic Prompt Optimization with "Gradient Descent" and Beam Search (ProTeGi)
- Yuksekgonul et al. 2024 — TextGrad: Automatic "Differentiation" via Text
- Yang et al. 2023 — Large Language Models as Optimizers (OPRO)
- Cheng et al. 2024 — Trace is the Next AutoDiff: Generative Optimization with Rich Feedback, Execution Traces, and LLMs (OPTO)
- Agrawal et al. 2025 — GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning
- Beyer & Schwefel 2002 — Evolution Strategies: A Comprehensive Introduction ((1+λ)-ES)
- Dwork, Feldman, Hardt, Pitassi, Reingold, Roth 2015 — The Reusable Holdout: Preserving Validity in Adaptive Data Analysis
- Recht, Roelofs, Schmidt, Shankar 2019 — Do ImageNet Classifiers Generalize to ImageNet?
- Nemhauser, Wolsey, Fisher 1978 — An Analysis of Approximations for Maximizing Submodular Set Functions
- Freund & Schapire 1997 — A Decision-Theoretic Generalization of On-Line Learning and an Application to Boosting (AdaBoost)
- Jamieson & Talwalkar 2016 — Non-stochastic Best Arm Identification and Hyperparameter Optimization (successive halving)
- Harness² — arXiv 2610.14224; RRSI — github.com/google-research/rrsi (proposer conditioned on edit history)
