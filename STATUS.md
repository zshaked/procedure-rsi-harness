# Status — plain version (2026-11-20)

One page. Read this before anything else in the repo.

## What this repo set out to test

Whether an unwritten operations procedure can be learned from historical cases (request, operator reply, system-of-record state) plus a small budget of operator answers — and whether a self-improving loop driven by a learned checker ("verifier-first") is the right way to do it.

## What was found

From the pre-registered pilot (`pilot/RESULTS_v3.md`, `pilot/RESULTS_v4.md`), on a synthetic environment with a simulated operator:

- **Operator answers are the signal.** Fifteen questions were worth +9.5 points over history alone (0.870 → 0.965).
- **The machinery around the answers added nothing measurable.** Building the checker first and searching against it: +0.6 points (CI −1.4 to +2.7) over simpler uses of the same fifteen questions.
- **Which questions get asked matters a little** (model-chosen beats random by +3.3). A hand-designed rule for choosing them was slightly worse than the model's default (−1.0, CI −1.9 to −0.1) and 8 points worse on the held-out policy. The likely reason, found after the fact: its "don't overturn a rule on one contradicting answer" clause protected operator mistakes that were in the histories.
- **A checker the procedure was searched against agreed with it 200/200.** That agreement is circular and is not evidence.

Nothing in this repo has been run on real data. The scaffold in `aop_rsi/` has only run on the synthetic environment.

## What is withdrawn or parked

- **Withdrawn: the audit study (`audit/PREREG.md`), before any run.** It proposed measuring how much of a self-improving loop's gain survives on fresh data. Others had already measured that; the plan was written without a literature search. The prior work is in the table below.
- **Parked: the self-improving loop** (`DESIGN.md` §6–§9; the `optimizer/` and `gate/` parts of `PROMPT.md`). Not deleted. Reopen conditions are at the bottom.
- **Demoted: `docs/descent.md`.** It explains why an accept-if-better loop goes downhill. It is commentary on known results, not a contribution, and two of its literature notes were wrong (corrected 2026-11-20).

## What the wider evidence says (searched 2026-11-19)

| Finding | Source |
|---|---|
| Four published harness optimizers, re-run from one starting point, gained 1.3–3.6 points on the tasks they tuned on. On a held-out slice of the same benchmark they kept about +2. On unseen benchmarks they landed between −1.7 and +0.9. A regularized version got about +4 on unseen ones. | RRSI, arXiv 2609.24972 |
| Under matched budgets on Terminal-Bench 2.1, simply sampling more attempts beat harness evolution (72.3 vs 67.4), and held-out tasks from the same benchmark showed no gain. Harness evolution did win on long-horizon games with headroom and step-by-step feedback. | Rethinking the Evaluation of Harness Evolution for Agents, arXiv 2607.12227 |
| A keep-the-best loop accepted false improvements about one time in five, even with 2,000 evaluation cases. An acceptance rule with a finite-sample guarantee removes them. | REUSE, arXiv 2609.33180 |
| Left alone, LLM research agents overfit their validation set by under 2 points; large gaps had to be provoked. | Bertran, Roth, Wu, arXiv 2606.11045 |
| A loop that keeps a change because the score rose can be selecting for an evaluation defect or a weak baseline rather than for quality. | What Does a Harness Repair? (preregistered), arXiv 2610.05533 |
| One expert call returning a few lines of guidance was worth +8.3 points on average. The same expert routed through four memory/distillation methods bought under 1 point each. The expert was a model, not a person. | SynAct, arXiv 2610.12651 |
| A deployed enterprise system went logging → copilot → automation above a precision threshold. It fully automated 45% of sessions, was trained on about 210k logged examples, and keeps low-volume case types in copilot-only mode. | Learning Selective LLM Autonomy from Copilot Feedback, arXiv 2604.23855 |

Read together: on the same kind of task a loop is worth roughly 0–2 points; the gain mostly does not carry to a different kind of task; and it needs automatic scoring and many cases. Expert correction is worth several times more and needs neither. This matches the pilot.

## The arithmetic that parks the loop

Comparing two versions on the same n cases (paired test, 80% power, 5% two-sided). d is the share of cases on which the two versions disagree.

| n cases | smallest real gain detectable at d = 0.10 / 0.15 / 0.20 |
|---|---|
| 100 | 8.5 / 10.4 / 12.1 points |
| 200 | 6.1 / 7.5 / 8.7 |
| 400 | 4.4 / 5.4 / 6.2 |
| 1,000 | 2.8 / 3.4 / 3.9 |
| 2,000 | 2.0 / 2.4 / 2.8 |

Detecting a 3-point gain takes roughly 900–1,300 cases; a 2-point gain, roughly 2,000–3,000. A mailbox with a few hundred historical cases, about 100 of them held out for validation, can only see changes of 9 points or more. A loop whose realistic gain is about 2 points cannot tell progress from luck there. `python -m aop_rsi.experiments.power` reproduces the table.

## What to do instead

1. **Get the one number that does not exist yet.** On real cases, split by time: a strong model given similar past cases, system-of-record lookups, and the option to say "not sure, send to a human". Score field by field against the historical reply on the newest cases. Report the share answered at a fixed precision. `aop_rsi/` already has the scoring, the snapshot check (E1) and the operator-consistency estimate (E0′).
2. **Copilot before automation.** Operators accept or fix drafts. Their edits are the labels.
3. **Spend operator time on the failure clusters.** It is the only thing that moved the number, in the pilot and in the literature.
4. **Never let a pattern in the history outvote a confirmed operator correction.** That was the v4 failure.

## Stop / go

- **Stop** if the system-of-record state at the time of each reply cannot be reconstructed (E1 fails); if operators disagree with each other on like cases more than about 15% (E0′ — a rough line; no method beats the humans' own inconsistency); if no operator time is available; or if case volume is too small to repay the work.
- **Ship the simple version** if it clears the precision bar that operations sets, on whatever share of cases it answers.
- **Reopen the loop** only when all three hold: a few thousand operator-verified cases; an automatic check on the decision, not only on the facts; and hand edits to the playbook have stopped helping.
