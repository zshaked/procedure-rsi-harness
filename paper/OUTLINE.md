# Paper outline

Working title: **Learn to Verify Before You Act: Label-Efficient Verification for Latent Procedures**

Status: outline v0.1. No experiments run. The kill test in §9 runs before anything else.

Companion documents: `MATH.md` (formal statements), `../benchmark/README.md` (testbed), `../DESIGN.md` and `../docs/` (the harness).

---

## 1. The question

> When can a learned verifier stand in for the human in a self-improvement loop for a latent procedure, and how many human labels does it take to get there?

Framing that must survive into the abstract's first sentence: **the bottleneck is specification, not evaluator intelligence.** A frontier model can judge; it cannot know what "correct" means on a desk whose procedure was never written down. The verifier's job is to acquire that specification from the cheapest available channels, and the paper measures the exchange rate between channels.

---

## 2. Draft abstract

> Operational procedures in enterprises are rarely written down. What exists is a history of requests, the responses humans sent, and the state of the system of record at the time — and a human who can say whether a response is acceptable. Self-improvement methods for agent harnesses assume either a ground-truth verifier or none at all; the common enterprise case is neither: a verifier must be learned, from a human whose time is scarce, for a specification that lives only in that human's head. We argue the bottleneck is specification, not evaluator intelligence, and study verifier-first self-improvement: induce the specification as a learned verifier before optimizing the procedure against it. We model the desk's specification as a latent variable observed through three channels — outcome histories, confirmed rules, and verdicts on candidate responses — and measure each channel's yield in specification per unit cost. We release [BENCHMARK], built by inverting policy-following agent environments: a hidden policy generates outcome-only histories with operator inconsistency and drift, and a budgeted noisy oracle is the only ground truth. We find that (i) [spec-first beats policy-first at every label budget]; (ii) [checklist verifiers reach usable agreement with k× fewer labels than holistic ones and are harder to exploit]; (iii) [self-improvement against the verifier turns negative below a threshold predicted by the judge–truth gap and the policy's divergence from reference]; and (iv) [a selective verifier with conformal risk control can take over a growing fraction of cases at bounded error, bucket by bucket]. [Aggregate results from a production deployment reproduce the benchmark's curves.]

Bracketed claims are hypotheses; each is replaced by the measured result or deleted.

---

## 3. Contributions

1. **Problem.** Verifier-first self-improvement for latent procedures: formalized as latent specification inference with budgeted channels (`MATH.md` §1).
2. **Benchmark.** Outcome-only histories with hidden policy, inconsistency, drift, and a budgeted noisy oracle; history size as a knob (400 → 50 → 0); representation as a knob (graph / skill / script).
3. **Method.** Deterministic floor from state; checklist verifier with provenance, curated from oracle verdicts; query selection by expected specification gain; conformal selective stand-in.
4. **Results.** The five hypotheses in §4, each one figure.
5. **Bound.** A Goodhart bound relating judged gain, audit gap and divergence from reference, with its flip point tested empirically (`MATH.md` §2).

---

## 4. Hypotheses

| # | Hypothesis | Measurement | Figure |
|---|---|---|---|
| H1 | **Asymmetry.** Same N oracle labels: curating the verifier then searching beats fitting the policy directly on the labels, at every N. | Pass rate vs N, two curves (spec-first, policy-first), per history size | Fig 2 |
| H2 | **Representation of the spec.** Checklist conditions with provenance reach usable κ with fewer labels than retrieved exemplars or holistic rubric prose, and have a smaller Goodhart gap under optimization. | κ vs N and Goodhart gap vs steps, three verifier representations | Fig 3 |
| H3 | **Threshold.** Self-improvement against the verifier turns negative (worse than AOP_0 on the hidden anchor) below a κ level, and the flip point is predicted by the bound in `MATH.md` §2. | True gain vs judged gain over epochs at several κ levels; predicted vs observed flip | Fig 4 |
| H4 | **Circularity.** Provenance-tiered memory holds κ under injected agent hypotheses; flat memory drifts. | κ over epochs with/without tiers, with hypothesis injection | Fig 5 |
| H5 | **Representation freedom.** With reliability (reproducibility, stability, cost) in the reward, a free-form representation (script) converges toward structured procedures, and the constrained graph learns slowest but exploits the judge least. | Structuredness over epochs; label efficiency and Goodhart gap per representation | Fig 6 |

Secondary measurements, reported without hypotheses:
- κ₀: the zero-label verifier distilled from priors + context + histories alone, as a function of history size.
- Exchange rate between channels at matched κ (`MATH.md` §1.4).
- Coverage at fixed risk per bucket vs labels (`MATH.md` §3).

---

## 5. Method summary (one page in the paper; detail in `../DESIGN.md`)

- **Floor.** Deterministic checks against replayed state and the grounded facts in the reference response. Unexploitable; costs no labels.
- **Verifier.** Checklist of conditions, each with provenance (prior / context / inferred-from-history / oracle-stated), weights updated from oracle verdicts; de-anchored (commits to its own answer before scoring); residual holistic score shrinks over time.
- **Cold start.** Priors (model knowledge), context (schema, tools, sibling-procedure rubric), rules distilled from histories. First oracle queries are rule *verification*, not elicitation.
- **Selection.** Expected specification gain per unit cost; query-by-committee as the practical estimator (`../docs/selection.md`).
- **Inner loop.** Group sampling, lexicographic reward, contrastive reflection, typed edits, sealed gate (`../docs/rl.md`).
- **Stand-in.** Conformal risk control: auto-decide where calibrated confidence clears τ_ε, escalate the rest; τ re-estimated from the persistent random audit slice.

---

## 6. Baselines

| Baseline | Why it is required |
|---|---|
| Long-context procedure writing: all histories in context → write the procedure → execute | If this solves the hard splits, the thesis is wrong. Runs first (§9). |
| Retrieval few-shot: nearest histories in context at inference, no explicit procedure | Tests whether an explicit procedure is needed at all |
| Policy-first: fine-tune / few-shot the policy directly on oracle-labeled responses | The H1 comparison |
| Terminal-reward harness evolution (Procedural-Graphs-style refinement, outcome reward only) | Reproduces the known overfit; isolates the value of dense state verification |
| Gold-trace upper bound: same loop given the hidden policy's action traces | Bounds what outcome-only induction can reach |
| Holistic judge / exemplar judge | H2 comparators |
| Flat memory | H4 comparator |

---

## 7. Experiments

| Id | Purpose | Varies | Fixed |
|---|---|---|---|
| X0 | Kill test (§9) | — | — |
| X1 | κ₀ and the history knob | history size ∈ {0, 50, 400} | no oracle labels |
| X2 | H1 | N ∈ {0, 10, 25, 50, 100, 200}; spec-first vs policy-first | history 400 |
| X3 | H2 | verifier representation | N as in X2 |
| X4 | H3 | κ level (by truncating N); optimization steps | representation: checklist |
| X5 | H4 | memory tiering; hypothesis injection rate | N = 50 |
| X6 | H5 | representation (graph / skill / script); reliability weight λ | N = 50 |
| X7 | Drift and inconsistency splits | ρ_op ∈ {0, 0.1, 0.3}; drift on/off | best config |
| X8 | External validity (if permitted) | — | production desk, aggregate only |

Each experiment reports mean and bootstrap CI over ≥ 3 seeds. Budget estimate per experiment is in `../benchmark/README.md` §8.

---

## 8. Related work (positioning, not a survey)

- **Harness evolution:** ACE; Procedural Graphs (2609.09153); Harness² (2610.14224); RRSI; R²Flow; HarnessX. We use their machinery; our setting (learned verifier, budgeted oracle) is the gap between Harness²'s "no verifier" and the benchmark verifiers the others assume.
- **Judge failure:** PROCTOR (2609.02246) — deterministic guardrails; "More Convincing, Not More Correct" (2607.05904) — self-play judge hacking, hidden-anchor audit, de-anchoring. We adopt both; we add the label-budget axis and the flip-point prediction.
- **Selective judging:** Trust-or-Escalate (2024) — provable human agreement for evaluation. We put it inside the loop while the judge is being learned.
- **Reward-model overoptimization:** Gao et al. 2022 scaling laws; our bound is the in-context analogue.
- **Active reward learning:** Christiano et al. 2017 (query selection by ensemble disagreement); CIRL/assistance games as the frame.
- **Procedure induction:** TMI (2608.20319), AWM, Agent-S — all trace-based; process mining — event logs are traces; learning-from-observation (BCO, ILPO) — the closest RL cousin; program synthesis from I/O.
- **Rubric / checklist rewards:** RBR, RLCF — the representation H2 favors, used for a learned rather than authored spec.
- **Environments:** τ-bench / τ²-bench — inverted here.

---

## 9. Kill test (runs first, ~one weekend)

1. Generate the synthetic ops domain with history size 400, ρ_op = 0.2, drift at index 250.
2. Long-context baseline: frontier model, all 400 histories in context, asked to write the procedure; execute with ReAct over the tools on the held-out (post-drift) split.
3. If pass rate on the post-drift and high-inconsistency splits ≥ 0.9: the thesis is wrong for this domain; try one harder configuration (ρ_op = 0.3, two drifts); if still ≥ 0.9, stop and write the smaller paper ("long context solves outcome-only procedure induction; here is the boundary").
4. If it fails: proceed to X1.

Cost: on the order of tens of dollars of API calls.

---

## 10. Venue and timeline

- Weeks 1–4: benchmark (synthetic ops domain first, τ-mail second), X0, X1.
- Weeks 5–8: verifier + inner loop against the benchmark; X2, X3.
- Weeks 9–11: X4, X5, X6, X7.
- Weeks 12–14: writing; X8 if permitted.
- Target: a workshop at ICLR 2027 (deadlines typically around February), then the main-track version for NeurIPS 2027 (typically May). Confirm exact dates.
- Scope freeze: two τ-mail domains plus one synthetic; one policy model, one judge family; model-family variation in the appendix only; no sixth hypothesis.

---

## 11. What would make it a weaker paper, honestly

- X0 passes: the paper becomes a boundary result and a benchmark.
- Firm data unavailable: X8 is dropped; the paper rests on the benchmark alone and loses its external-validity paragraph.
- Results mushy (no flip point, no clear representation ordering): workshop paper with a clean benchmark, which still serves the first-artifact goal.
- Someone publishes "selective judge inside a self-improvement loop" first: the latent-specification framing, the history knob, and the real-desk validation remain; reposition as the enterprise-setting study.
