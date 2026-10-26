# procedure-rsi-harness

A self-improving harness for Agentic Operating Procedures (AOPs): procedures expressed as DAGs and executed by a fixed LangGraph engine, evolved from historical operations data under a cheap learned verifier that is calibrated against an expensive human oracle on a budget.

Status: design only. Nothing is built. Design v0.4, revised after an external review of commit 0c01a49: the floor checks facts not decisions, data roles are disjoint, evaluation is reference-free against executable ground truth, the selective stand-in uses a sound procedure with its label cost stated, and scope is cut to a two-week pilot that tests whether a learned verifier beats simply handing the inferred specification to the agent. See `paper/OUTLINE.md` §9.

## Files

| File | What it is |
|---|---|
| `DESIGN.md` | The full design: setting, reward, stratification, optimizer, gate, human loops, memory, metrics, experiments, scaffold layout, risks, phasing. |
| `PROMPT.md` | Entry-point prompt for a coding agent working inside the target environment. |
| `docs/rl.md` | How each RL piece works (environment, policy, reward, advantage, update, trust region, reward model, Goodhart), where the analogy stops, a worked example, hyperparameters. |
| `docs/metrics.md` | Metric definitions by split and slice, gate statistics and noise floor, the accuracy-vs-verifier-cost curve, edit/memory health, v1 targets. |
| `docs/selection.md` | Which cases get judged after a run and which get escalated to operators; the taxonomy agent's role; the calibration trap. |
| `paper/OUTLINE.md` | The paper: question, draft abstract, contributions, hypotheses H1–H5 with their figures, baselines, experiments X0–X8, related work, kill test, timeline. |
| `paper/MATH.md` | Latent specification inference and the history-per-verdict exchange rate; a Goodhart bound with its flip-point test; conformal selective stand-in; reliability-weighted reward and structuredness. |
| `benchmark/README.md` | The testbed: a synthetic confirmations domain and an inversion of τ-bench; knobs (history size, inconsistency, drift, budget, representation), splits, oracle simulator, schema, build order. |

## For a coding agent

Read `DESIGN.md` in full, then follow `PROMPT.md`. Stop after experiments E0–E2 and report before building the optimizer or gate.

## References

- ACE — Agentic Context Engineering (Generator / Reflector / Curator; delta-updated playbooks)
- Procedural Graphs: Self-Evolving Execution Structures for LLM Agents — arXiv 2609.09153
- Harness²: Recursive Agent Harnessing for an Open World — arXiv 2610.14224
- RRSI: Regularized Recursive Self-Improvement of Agent Harnesses — github.com/google-research/rrsi
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

## Scope note

This repository is intentionally firm-agnostic. It contains no data, no system names, and no proprietary procedure content. Terms like "SOR" (system of record) and "position confirmation" are generic.
