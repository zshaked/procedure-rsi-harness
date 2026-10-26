# procedure-rsi-harness

A self-improving harness for Agentic Operating Procedures (AOPs): procedures expressed as DAGs and executed by a fixed LangGraph engine, evolved from historical operations data under a cheap learned verifier that is calibrated against an expensive human oracle on a budget.

Status: design only. Nothing is built. The design is verifier-first (v0.3): the primary artifact is a learned verifier that earns the right to stand in for the human operator bucket by bucket; the procedure is what search against that verifier produces. See `DESIGN.md` §11 — experiments E0′–E2 at the firm and the kill test in `paper/OUTLINE.md` §9 on public data decide whether anything should be built.

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
- Scaling Laws for Reward Model Overoptimization — Gao et al. 2022
- Deep RL from Human Preferences — Christiano et al. 2017 (query selection by ensemble disagreement)
- Conformal Risk Control — Angelopoulos, Bates et al.
- τ-bench / τ²-bench — the environments inverted in `benchmark/`
- GRPO / DAPO — group-relative advantage; dynamic sampling

## Scope note

This repository is intentionally firm-agnostic. It contains no data, no system names, and no proprietary procedure content. Terms like "SOR" (system of record) and "position confirmation" are generic.
