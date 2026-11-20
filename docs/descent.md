# Why the loop descends without a gradient

> **Status (2026-11-20).** This is commentary that applies known results to the parked loop in `DESIGN.md`. It contains no new result and no experiment. The question in §2.2 — how much of a loop's gain is real when it keeps re-using its evaluation set — has been measured by others; see the note added there. Two literature annotations (RRSI; Recht et al.) were wrong and have been corrected. For where the project stands, read `STATUS.md`.

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

This is the worst case in Dwork et al.'s adaptive-data-analysis setting. How often the worst case shows up in practice is an empirical question; see "Measured since" below. The design already carries the mitigations:

| Mechanism | Where | What it buys |
|---|---|---|
| Noise-floor threshold on the paired Δ | `metrics.md` §4.2 | A crude Thresholdout: answers below the threshold reveal nothing about S_val |
| Sealed-reads counter, refresh at ~50 | `metrics.md` §4.3 | The budget accounting Thresholdout needs |
| Four disjoint data roles; final test touched once | `DESIGN.md` §7 | An estimate of L_D the loop cannot have fit |
| Rolling held-out from new production cases | `rl.md` §8 | A fresh sample every period; the gap against S_val is the overfitting signal |
| Edit budget b_t annealed toward 1 | `rl.md` §5.3 | Small steps: fewer degrees of freedom per accepted edit |

The closest precedent for the gate itself is Blum & Hardt's Ladder mechanism for ML leaderboards: a submission's score is updated only when it beats the current best by more than a fixed threshold, and under that rule the leaderboard's generalization error grows only logarithmically in the number of submissions rather than polynomially. The noise-floor gate is a Ladder with an empirically estimated threshold; the sealed-reads counter is the conservative fallback for when the threshold is misestimated.

**Measured since (added 2026-11-20).** This section was first written as if the size of the gap were unmeasured for self-improvement loops. It is not:

- RRSI (arXiv 2609.24972) re-ran four published harness optimizers from one starting harness: gains of 1.3–3.6 points on the tuning tasks, about +2 on a held-out slice of the same benchmark, and −1.7 to +0.9 on unseen benchmarks. The loss is on transfer to new task families, not on fresh cases of the same kind. Its own acceptance rule is an empirical noise band, not a formal reuse correction.
- REUSE (arXiv 2609.33180) is the Ladder idea worked out for exactly this loop: the proposer sees only promote/reject, each candidate faces an exact paired sign test, and the error budget is split across every possible decision history. With probability 1 − α every promotion is a true improvement. Uncontrolled keep-the-best selection made false promotions about one time in five at n = 2,000. It also gives the minimum detectable improvement at a given n, which is the binding constraint at small case counts (`STATUS.md`).
- Bertran, Roth, Wu (arXiv 2606.11045) found that LLM research agents, left to ordinary prompting, overfit a reused validation set by under 2 points; large gaps had to be provoked. Their explanation is that a successful strategy is short to describe, so little validation-specific information can ride along.
- *Rethinking the Evaluation of Harness Evolution for Agents* (arXiv 2607.12227) found no held-out gain from harness evolution on Terminal-Bench 2.1 and that matched-budget repeated sampling did better.

Taken together: leakage on fresh cases of the same kind has been small where it was measured; the larger loss is on transfer to new task families; and the practical problem at a few hundred cases is that the gate cannot detect gains of the size these loops produce.

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

**4.1 Best of the sampled neighborhood.** Generate N candidate edits, evaluate all, take the best. This guarantees maximal descent *over the N sampled*. It is what the per-epoch candidate set and the compose step already do (`rl.md` §5.3). Cost is N gate evaluations; racing reduces it — evaluate all N on the target bucket's cases first, drop the bottom half, repeat, and only survivors reach the full gate. This is Maron & Moore's Hoeffding race for model selection, in its modern successive-halving form: it returns the best of N with probability 1 − δ at a fraction of the evaluations, and its sample-complexity bounds are the only "how many rollouts do we need" results that apply directly here.

**4.2 Exhaustive neighborhood.** Define the neighborhood finitely — every `playbook.add` from the current lesson pool, every `playbook.retire` of a line with negative counters — and evaluate every member. This is discrete steepest descent and a true guarantee within the neighborhood. It is feasible when the pool is small and rollouts are cached, which is the v1 regime (typed edits, playbook-first), and infeasible once structural edits unlock.

**4.3 Surrogate with regret bounds.** Fit a cheap model from edit features to predicted Δ and optimize over it, as DSPy's MIPROv2 does over instruction candidates. Bayesian-optimization regret bounds exist but assume kernel smoothness that text edits do not satisfy cleanly. Useful in practice; weak as a theorem. The edit library's prediction records are the training data for such a surrogate, which is another reason to keep them.

**4.4 Submodularity.** The one real theorem available. Treat the playbook as a set of lines and the objective as floor-pass coverage: the number of cases a policy handles correctly as a function of which lines are present. Coverage functions are the canonical monotone submodular objective, and for monotone submodular maximization greedy — always add the element with the largest marginal gain — is within (1 − 1/e) ≈ 0.63 of the optimal set (Nemhauser, Wolsey, Fisher 1978). Under a precision constraint the problem becomes constrained submodular maximization, which still admits constant-factor greedy guarantees.

That is a bound on the *trajectory*, not on one step, and the greedy algorithm it certifies is the one the loop runs anyway. The assumption is diminishing marginal returns, which fails when lines *interfere* — when adding one changes how another applies. Interference need not be all-or-nothing: Das & Kempe's submodularity ratio γ_s ∈ [0, 1] measures how far a set function is from submodular, and greedy still achieves a (1 − e^{−γ_s}) approximation. So the question is not "is coverage submodular" but "what is γ_s," and the design has a direct estimator for it: every edit's `predicts_unaffected` set, checked at the gate and in later epochs. A rising rate of predicted-unaffected cases that changed is a measured drop in γ_s, and the per-bucket no-regression rule bounds its damage. Narrow, well-scoped lines keep γ_s near 1, which means the choices that make the playbook auditable are the same choices that make the theorem closer to true.

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

The shape is AdaBoost's: target the current residual, require only an edge from each round, get geometric decrease of the training error. The assumption is on the proposer and it is weak — any positive edge — and it is measured every epoch as e_t, so the bound is live rather than asserted.

This also closes the loop on the original question. Mason et al. and Friedman showed that boosting *is* gradient descent — in function space, where each weak learner is the best available approximation to the negative functional gradient (the residual). Target-then-fix is the discrete analogue: the failure histogram is the residual, the typed edit is the weak learner, and the gate measures the edge. The reviewer was right that the text proposer is not a gradient; the correct reply is that the loop does not need one, because it is organized the way gradient boosting is, where the "gradient" is read off the residual and the learner only has to beat chance on it. Together with §4.4, this is as close to "guaranteed maximal descent" as the problem admits: optimal targeting, best-of-N fixing with a measured edge, and near-optimality of the greedy sequence when interference is small.

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

## Literature

Grouped by the section each result supports. One line each on what it contributes here; `README.md` carries the judge-reliability and reward-model references, which are not repeated.

### §1 — The optimizer class: derivative-free search

- Beyer & Schwefel 2002 — *Evolution Strategies: A Comprehensive Introduction.* The (1+λ)-ES and (1,λ)-ES formalism; the loop is a (1+λ)-ES with a held-out fitness and a learned mutation distribution.
- Hansen 2016 — *The CMA Evolution Strategy: A Tutorial* (arXiv 1604.00772). What a *learned* mutation distribution buys in continuous spaces; the curator conditioning on the edit library is the discrete, text-valued analogue.
- Salimans et al. 2017 — *Evolution Strategies as a Scalable Alternative to Reinforcement Learning.* ES competitive with policy gradients on RL benchmarks; the empirical case that "no gradient" is not "no optimization."
- Nesterov & Spokoiny 2017 — *Random Gradient-Free Minimization of Convex Functions.* Zeroth-order methods pay a factor of the dimension d per gradient estimate; the formal reason "certify the steepest step" is unavailable when d is undefined.
- Duchi, Jordan, Wainwright, Wibisono 2015 — *Optimal Rates for Zero-Order Convex Optimization.* Matching lower bounds for the above.
- Glover 1989 — *Tabu Search — Part I.* Memory of rejected moves as a first-class component of a local search; the edit library's rejection record is a tabu list.

### §1 — Text-valued proposers ("textual gradients")

- Pryzant et al. 2023 — *Automatic Prompt Optimization with "Gradient Descent" and Beam Search* (ProTeGi). The first explicit textual-gradient framing; the scare quotes are the authors' own. Beam search over edits is §4.1's best-of-N.
- Yuksekgonul et al. 2024 — *TextGrad: Automatic "Differentiation" via Text.* The metaphor taken furthest: backpropagated natural-language feedback through a compound system. Useful for intuition; no descent guarantee is claimed.
- Yang et al. 2023 — *Large Language Models as Optimizers* (OPRO). The optimizer's context holds the trajectory of (solution, score) pairs — the optimizer-memory half of §3.
- Cheng et al. 2024 — *Trace is the Next AutoDiff* (OPTO). The one framing that formalizes rich feedback as a generalization of a first-order oracle and is careful about what properties survive the generalization. Recommended for anyone who wants the colleague's question answered at the level of definitions.
- Agrawal et al. 2025 — *GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning.* Pareto-front population search over reflective edits; the population-based alternative to a single accepted AOP_t when local optima become the problem.
- Opsahl-Ong et al. 2024 — *Optimizing Instructions and Demonstrations for Multi-Stage Language Model Programs* (MIPROv2 / DSPy). Bayesian optimization over instruction candidates — §4.3's surrogate route, with its assumptions visible.
- Fernando et al. 2023 — *Promptbreeder*; Guo et al. 2023 — *EvoPrompt.* Evolutionary prompt optimization with LLM mutation operators; the lineage the harness belongs to, with the same absence of per-step guarantees.
- Shinn et al. 2023 — *Reflexion*; Madaan et al. 2023 — *Self-Refine.* Verbal self-critique as the update signal; the ancestors of the reflector. Neither has a gate, which is why neither has a descent guarantee.
- Zhang et al. 2025 — *Agentic Context Engineering* (ACE); Suzgun et al. 2025 — *Dynamic Cheatsheet.* Delta-updated playbooks with helpful/harmful counters; the "context collapse" failure in ACE is divergence from too large a step and is the empirical argument for the edit budget b_t.

### §1 — Harness-level optimizers (2024–2026)

- Hu, Lu, Clune 2024 — *Automated Design of Agentic Systems* (ADAS / Meta Agent Search). Code-valued search over whole agent designs with an archive; the archive is optimizer memory.
- Zhang et al. 2024 — *AFlow.* MCTS over workflow graphs — tree search as the alternative to (1+λ)-ES when the edit space is structural (`graph.*`).
- Novikov et al. 2025 — *AlphaEvolve.* Evolutionary search over programs under an automated evaluator at scale; the cleanest demonstration that evaluator quality, not proposer cleverness, is the binding constraint.
- Lee et al. 2026 — *Meta-Harness: End-to-End Optimization of Model Harnesses* (arXiv 2603.28052). Harness search with full execution traces as optimizer input; reports gains on *online text classification*, the closest published benchmark to a routing problem.
- Lin et al. 2026 — *Agentic Harness Engineering* (AHE, arXiv 2604.25850). Every edit paired with a self-declared prediction verified on the next round — the decision-observability discipline `DESIGN.md` §7 adopts, and the source of the "edit → prediction → outcome" log §3 depends on.
- *Towards Direct Evaluation of Harness Optimizers via Priority Ranking* (arXiv 2605.22505). Asks whether harness optimizers act on information or by trial-and-error, and proposes evaluating the optimizer directly rather than through end performance — precisely the §6 question of whether the proposer is informed.
- Pan et al. 2026 — *Evolving Agents in the Dark: Retrospective Harness Optimization via Self-Preference* (RHO, arXiv 2606.05922). Harness optimization from past trajectories with no labels, selected by pairwise self-preference; the relevant design for mailboxes with no historical replies, and a reminder that self-preference without an external anchor is exactly the Goodhart surface §2.3 warns about.
- Liu et al. 2026 — *Adaptive Auto-Harness* (arXiv 2606.01770). Harness evolution on unbounded, heterogeneous, non-stationary task streams — the deployment regime, and the reason the rolling held-out exists.
- *Harness²: Recursive Agent Harnessing for an Open World* (arXiv 2610.14224). Two-level recursion; probe-then-compose is §4.1; its verifier-free contrastive probing is what the harness does *not* need because it has a judge, and its reported case of a lower-scoring output being preferred is the canonical illustration of §2.3.
- *RRSI: Regularized Recursive Self-Improvement of Agent Harnesses* (arXiv 2609.24972, github.com/google-research/rrsi). *Corrected 2026-11-20: an earlier note here described only its edit-history conditioning.* Its subject is overfitting in harness self-improvement. Four published optimizers re-run from one starting harness gained 1.3–3.6 points on their tuning tasks, about +2 on a held-out slice of the same benchmark, and −1.7 to +0.9 on unseen benchmarks; RRSI's regularizers (annealed edit budget, proposer sees the full accept/reject history, leakage screening, a noise-adjusted acceptance floor, cost-aware acceptance, pruning) traded a smaller tuning gain for about +4 on unseen ones.
- Wang et al. 2026 — *Rethinking the Evaluation of Harness Evolution for Agents* (arXiv 2607.12227). Matched-budget comparison on Terminal-Bench 2.1: harness evolution did not beat simply sampling more attempts (67.4 vs 72.3 without tests) and showed no gain on held-out tasks. It did win on long-horizon games (ARC-AGI-3, EdgeBench) where there is headroom and granular feedback.
- Yu et al. 2026 — *Self-Improvement Memory Enables Continual Recursive Self-Improvement* (SIM, arXiv 2611.18856). Optimizer memory indexed by root-cause problem, each holding every attempt's edit, rationale, predicted and observed outcome, and provenance; carried across datasets and models it beat harness-only transfer by 2–11 points, and root causes without the attempt record did not. The §3 optimizer-memory argument with measurements behind it; adopted in `DESIGN.md` §9.1–9.2, minus its LLM selector.

### §2 — Adaptive data analysis and the validation gap

- Dwork, Feldman, Hardt, Pitassi, Reingold, Roth 2015 — *The Reusable Holdout* (Science) and *Preserving Statistical Validity in Adaptive Data Analysis* (STOC). The √(k/n) adaptive versus √(log k / n) non-adaptive gap, and Thresholdout: answer a holdout query only when it differs from the training estimate by more than a noisy threshold. The noise-floor gate is a crude Thresholdout without the budget accounting; the sealed-reads counter supplies it.
- Blum & Hardt 2015 — *The Ladder: A Reliable Leaderboard for Machine Learning Competitions.* Update the reported score only on improvements above a threshold; generalization error then grows logarithmically in submissions. The closest precedent for the gate as designed.
- Bassily et al. 2016 — *Algorithmic Stability for Adaptive Data Analysis.* Tighter bounds and the general stability argument behind the above.
- Recht, Roelofs, Schmidt, Shankar 2019 — *Do ImageNet Classifiers Generalize to ImageNet?* *Corrected 2026-11-20: an earlier note here said this showed that years of test-set reuse overfit ImageNet. It shows nearly the opposite.* Accuracy fell 11–14 points on a freshly collected ImageNet test set, but gains on the original test set carried over to the new one, and the authors conclude the drop comes from the new images being slightly harder, not from adaptive reuse. Evidence that real leakage is smaller than the worst-case theory.
- *Which Self-Improvements Should We Trust? Reliable Self-Improvement When Agents Reuse Their Benchmarks* (REUSE, arXiv 2609.33180). Decision-only feedback, exact paired sign tests, error budget split over decision histories; every promotion is a true improvement with probability 1 − α. The reusable-holdout idea made concrete for self-improvement loops. Tested on tabular classification with a 7B proposer, not on agent harnesses.
- Bertran, Roth, Wu 2026 — *What Fits (Into Few Tokens) Doesn't Overfit* (arXiv 2606.11045). Validation-to-holdout gaps of 0–1.9 points for LLM research agents under ordinary prompting; large gaps only when provoked; a one-bit-per-query "ladder" explorer did as well as score feedback.
- *What Does a Harness Repair? A Preregistered Study of Visibility, Baseline Adequacy and Evaluation Defects* (arXiv 2610.05533). A keep-if-better loop can be selecting for an evaluation defect, a weak baseline, or answers merely becoming parseable; replication through the same pipeline cannot detect a defect every run shares.

*Verification note: RRSI, Rethinking the Evaluation of Harness Evolution, REUSE, Bertran et al. and What Does a Harness Repair? were checked against the papers' own text on 2026-11-19 (through an automated reader, not line by line); the Recht et al. correction was checked against its abstract. The other 2026 entries in this document were annotated from abstracts and summaries and should be read with that in mind.*

### §4 — Submodularity and greedy guarantees

- Nemhauser, Wolsey, Fisher 1978 — *An Analysis of Approximations for Maximizing Submodular Set Functions.* The (1 − 1/e) greedy bound for monotone submodular maximization under a cardinality constraint.
- Sviridenko 2004 — *A Note on Maximizing a Submodular Set Function Subject to a Knapsack Constraint.* (1 − 1/e) survives a knapsack constraint with partial enumeration; the form a token-cost or precision budget takes.
- Leskovec et al. 2007 — *Cost-Effective Outbreak Detection in Networks* (CELF). Cost-benefit greedy with lazy evaluation; the practical algorithm when each marginal-gain evaluation is a gate run.
- Das & Kempe 2011 — *Submodular Meets Spectral.* The submodularity ratio γ_s and the (1 − e^{−γ_s}) greedy bound for approximately submodular objectives; turns "do lines interfere" into a quantity the `predicts_unaffected` record estimates.
- Krause & Golovin 2014 — *Submodular Function Maximization* (survey chapter). The map of what else is available: curvature, adaptive submodularity, online greedy.

### §4.1 — Racing and best-arm identification

- Maron & Moore 1994 — *Hoeffding Races: Accelerating Model Selection Search.* The original: evaluate all candidates on growing samples and eliminate those whose confidence intervals fall below the leader's.
- Even-Dar, Mannor, Mansour 2006 — *Action Elimination and Stopping Conditions for the Multi-Armed Bandit and RL Problems.* PAC sample-complexity bounds for identifying the best arm.
- Jamieson & Talwalkar 2016 — *Non-stochastic Best Arm Identification and Hyperparameter Optimization* (successive halving); Li et al. 2018 — *Hyperband.* The budget-allocation versions used in practice.

### §5 — Boosting and residual targeting

- Freund & Schapire 1997 — *A Decision-Theoretic Generalization of On-Line Learning and an Application to Boosting* (AdaBoost). Geometric decrease of training error from a weak-learner edge; the shape of Proposition 2.
- Mason, Baxter, Bartlett, Frean 1999 — *Boosting Algorithms as Gradient Descent*; Friedman 2001 — *Greedy Function Approximation: A Gradient Boosting Machine.* Boosting as gradient descent in function space, with the residual as the negative functional gradient. The precise sense in which target-then-fix is a descent method without a parameter-space gradient.
- Schapire & Freund 2012 — *Boosting: Foundations and Algorithms.* The margin-based generalization theory, relevant if the loop ever needs a generalization bound stronger than §2.2's.

### §2.3 — Optimizing against a learned objective

- Gao, Schulman, Hilton 2022 — *Scaling Laws for Reward Model Overoptimization.* Proxy reward rises while gold reward peaks and falls as optimization pressure grows; the quantitative version of the Goodhart gap, and the reason judge quality bounds how many epochs the loop can run.
- Skalse, Howe, Krasheninnikov, Krueger 2022 — *Defining and Characterizing Reward Hacking.* When a proxy is "hackable" relative to the true objective; a learned judge is hackable almost by construction, which is why the lexicographic floor is not.
- Manheim & Garrabrant 2018 — *Categorizing Variants of Goodhart's Law.* Regressional, extremal, causal, adversarial — the gate faces the first two from sampling noise and the fourth from the proposer.
