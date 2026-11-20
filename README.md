# procedure-rsi-harness

Design, pre-registered pilot, and measurement scaffold for learning an unwritten operations procedure from historical cases plus a small budget of operator answers. The starting hypothesis was a self-improving harness for Agentic Operating Procedures (AOPs) — procedures expressed as DAGs, executed by a fixed LangGraph engine, evolved under a learned verifier. The pilot did not support it and the loop is parked. **Read `STATUS.md` first.**

## Status (2026-11-20)

- **Found** (pre-registered pilot, synthetic environment, simulated operator): operator answers are worth +9.5 points over history alone. Building a verifier first and searching against it adds nothing measurable (+0.6 points, CI −1.4 to +2.7). Which questions get asked matters a little (model-chosen beats random by +3.3), but a hand-designed rule for choosing them is slightly worse than the model's default (−1.0, CI −1.9 to −0.1) and 8 points worse on the held-out policy. Details: `pilot/RESULTS_v3.md`, `pilot/RESULTS_v4.md`. Per the pre-registered stop rule, that research thread ended there.
- **Withdrawn:** the audit study in `audit/PREREG.md`, before any run. Its question — how much of a self-improving loop's gain is real — had already been answered by others (RRSI, REUSE and three more, listed in `STATUS.md`). The plan was written without a literature search.
- **Parked:** the self-improving loop described in `DESIGN.md`. With a few hundred cases it cannot tell a real improvement from noise (`STATUS.md`, "The arithmetic that parks the loop").
- **Not done:** anything on real data. `aop_rsi/` has only run on the synthetic environment.
- **Next:** one measured baseline on real cases, then copilot mode with operator corrections as labels. Stop/go rules are in `STATUS.md`.

## Files

| File | What it is |
|---|---|
| `STATUS.md` | One page, plain language: what was found, what is withdrawn or parked, what the wider evidence says, the arithmetic, what to do instead, stop/go rules. |
| `DESIGN.md` | The design of the hypothesis that was tested: setting, reward, stratification, optimizer, gate, human loops, memory, metrics, experiments, scaffold layout, risks, phasing. The loop (§6–§9) is parked. |
| `PROMPT.md` | Entry-point prompt for a coding agent working inside the target environment. Steps (a) and (c) still apply; the loop scaffolding in (b) does not. |
| `docs/rl.md` | How each RL piece works (environment, policy, reward, advantage, update, trust region, reward model, Goodhart), where the analogy stops, a worked example, hyperparameters. |
| `docs/metrics.md` | Metric definitions by split and slice, gate statistics and noise floor, the accuracy-vs-verifier-cost curve, edit/memory health, v1 targets. |
| `docs/selection.md` | Which cases get judged after a run and which get escalated to operators; the taxonomy agent's role; the calibration trap. |
| `docs/descent.md` | Commentary, not a contribution: why an accept-if-better loop goes downhill without a gradient, what its gate does and does not guarantee, and what "maximal descent" can mean over discrete edits. Applies known results; two literature notes corrected 2026-11-20. |
| `paper/OUTLINE.md` | The paper: question, draft abstract, contributions, hypotheses H1–H5 with their figures, baselines, experiments X0–X8, related work, kill test, timeline. |
| `paper/MATH.md` | Latent specification inference and the history-per-verdict exchange rate; a Goodhart bound with its flip-point test; conformal selective stand-in; reliability-weighted reward and structuredness. |
| `pilot/` | Runnable pilot: environments v1/v2, executable policies, grader, oracle, baselines, all arm outputs. Results: `RESULTS.md` (v1 smoke), `RESULTS_v2.md` (hardened benchmark), `PREREG.md` + `RESULTS_v3.md` (decisive comparison). |
| `benchmark/README.md` | The testbed: a synthetic confirmations domain and an inversion of τ-bench; knobs (history size, inconsistency, drift, budget, representation), splits, oracle simulator, schema, build order. |
| `audit/PREREG.md` | **Withdrawn before any run.** Draft pre-registration for a study of validation-set reuse in harness optimizers; kept as a record, with the prior work that made it redundant listed at the top. |
| `aop_rsi/` | Firm-agnostic measurement scaffold: case schema and the closed snapshot interface, env2 and firm adapters, time-ordered split, verifiable floor, field extractor and field-level agreement, deterministic baselines, experiments E0′–E2 with results on env2 Q1–Q4, and `experiments/power.py` (how big a gain n cases can detect). The bucket scorer and edit library were written for the parked loop. See `aop_rsi/README.md`. |

## For a coding agent

Read `STATUS.md` first, then `aop_rsi/README.md`. E0′–E2 are implemented in `aop_rsi/` and run on the synthetic environment; point them at a firm export via `aop_rsi/cases/adapters/firm.py`. Do not build an optimizer, judge or gate: `DESIGN.md` and step (b) of `PROMPT.md` describe the parked hypothesis.

## References

- ACE — Agentic Context Engineering (Generator / Reflector / Curator; delta-updated playbooks)
- Procedural Graphs: Self-Evolving Execution Structures for LLM Agents — arXiv 2609.09153
- Harness²: Recursive Agent Harnessing for an Open World — arXiv 2610.14224
- RRSI: Regularized Recursive Self-Improvement of Agent Harnesses — arXiv 2609.24972, github.com/google-research/rrsi (a study of overfitting in harness self-improvement; source of the regularizers in `DESIGN.md` §7)
- Self-Improvement Memory Enables Continual Recursive Self-Improvement (SIM) — arXiv 2611.18856 (problem-indexed optimizer memory; history travels with the harness across datasets and models; `DESIGN.md` §9.1–9.2)
- LLM-as-a-Judge Is Not an Oracle (PROCTOR) — arXiv 2609.02246
- More Convincing, Not More Correct: Self-Play Reward Hacking of Reference-Free LLM Judges — arXiv 2607.05904
- Trust or Escalate: LLM Judges with Provable Guarantees for Human Agreement — 2024
- Learn then Test: Calibrating Predictive Algorithms to Achieve Risk Control — Angelopoulos, Bates, Candès, Jordan, Lei 2021
- SibylSense: Adaptive Rubric Learning via Memory Tuning and Adversarial Probing — arXiv 2602.20751 (closest prior method)
- EvoRubrics — arXiv 2606.23038; AdaRubric — arXiv 2603.21362; Learnable Assessment Skills — arXiv 2605.29274
- Rulers: Locked Rubrics and Evidence-Anchored Scoring — arXiv 2601.08654; Rubrics as an Attack Surface — arXiv 2602.13576
- Scaling Laws for Reward Model Overoptimization — Gao et al. 2022
- Deep RL from Human Preferences — Christiano et al. 2017 (query selection by ensemble disagreement)
- Conformal Risk Control — Angelopoulos, Bates et al.
- τ-bench / τ²-bench — the environments inverted in `benchmark/`
- GRPO / DAPO — group-relative advantage; dynamic sampling

### Prior work that changed the plan (added 2026-11-20; findings summarized in `STATUS.md`)

- Rethinking the Evaluation of Harness Evolution for Agents — arXiv 2607.12227
- Which Self-Improvements Should We Trust? Reliable Self-Improvement When Agents Reuse Their Benchmarks (REUSE) — arXiv 2609.33180
- What Fits (Into Few Tokens) Doesn't Overfit: Compression and Generalization in ML Research Agents — Bertran, Roth, Wu, arXiv 2606.11045
- What Does a Harness Repair? A Preregistered Study of Visibility, Baseline Adequacy and Evaluation Defects — arXiv 2610.05533
- SynAct: Synergistic Active Feedback Learning for LLM Agents — arXiv 2610.12651
- Learning Selective LLM Autonomy from Copilot Feedback in Enterprise Customer Support Workflows — arXiv 2604.23855
- Harness Engineering for Self-Improvement — Lilian Weng, July 2026, lilianweng.github.io/posts/2026-07-04-harness/

## Scope note

This repository is intentionally firm-agnostic. It contains no data, no system names, and no proprietary procedure content. Terms like "SOR" (system of record) and "position confirmation" are generic.
