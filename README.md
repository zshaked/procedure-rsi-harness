# procedure-rsi-harness

A self-improving harness for Agentic Operating Procedures (AOPs): procedures expressed as DAGs and executed by a fixed LangGraph engine, evolved from historical operations data under a cheap learned verifier that is calibrated against an expensive human oracle on a budget.

Status: design only. Nothing is built. See `DESIGN.md` §11 — experiments E0–E2 decide whether anything should be.

## Files

| File | What it is |
|---|---|
| `DESIGN.md` | The full design: setting, reward, stratification, optimizer, gate, human loops, memory, metrics, experiments, scaffold layout, risks, phasing. |
| `PROMPT.md` | Entry-point prompt for a coding agent working inside the target environment. |

## For a coding agent

Read `DESIGN.md` in full, then follow `PROMPT.md`. Stop after experiments E0–E2 and report before building the optimizer or gate.

## References

- ACE — Agentic Context Engineering (Generator / Reflector / Curator; delta-updated playbooks)
- Procedural Graphs: Self-Evolving Execution Structures for LLM Agents — arXiv 2609.09153
- Harness²: Recursive Agent Harnessing for an Open World — arXiv 2610.14224
- RRSI: Regularized Recursive Self-Improvement of Agent Harnesses — github.com/google-research/rrsi
- GRPO / DAPO — group-relative advantage; dynamic sampling

## Scope note

This repository is intentionally firm-agnostic. It contains no data, no system names, and no proprietary procedure content. Terms like "SOR" (system of record) and "position confirmation" are generic.
