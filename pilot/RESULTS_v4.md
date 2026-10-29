# Results — question selection (v4, pre-registered in `PREREG_v4.md`)

**Verdict: NO.** The disciplined selection protocol does not beat the model's default choice of questions. It is slightly *worse* (−1.0 point, 95% CI −1.9 to −0.1), wins on 1 of 3 policies, and is 8 points worse on the held-out confirmatory policy Q1. Under §4 of the pre-registration, the research thread stops here: write up the benchmark and the nulls as a workshop note.

Model: Sonnet (Agent `model: sonnet`) for all 60 counted runs, per the 2026-10-28 amendment. Not numerically comparable to v3 (Opus 5.5). Smoke run `Q2_smoke_r9` (0.969) is not counted.

## 1. Primary numbers (fresh accuracy, 2,000 emails per policy)

| Arm | Q2 | Q3 | Q4 | Pooled | Q1 (held out) | n per policy |
|---|---|---|---|---|---|---|
| random | 0.924 | 0.930 | 0.948 | **0.934** | — | 3 |
| default | 0.947 | 0.969 | 0.984 | **0.967** | 0.933 | 6 (Q1: 3) |
| default_robust (R2 only) | 0.957 | 0.950 | 0.965 | **0.957** | — | 3 |
| disciplined (R2 + plan) | 0.950 | 0.952 | 0.967 | **0.956** | 0.850 | 6 (Q1: 3) |

## 2. Decision rules, applied mechanically

| Rule | Threshold | Observed | Result |
|---|---|---|---|
| S1 selection matters | default − random ≥ 3 pts, p < 0.05 | +3.27 pts, p = 0.0005, CI [+1.95, +4.58] | **YES** |
| S2 disciplined beats default (primary) | ≥ 3 pts, p < 0.05, wins ≥ 2/3 | −1.01 pts, p = 0.97, CI [−1.92, −0.08], wins 1/3 | **NO** |
| Q1 confirmatory | disciplined not ≥ 3 pts worse | 0.850 vs 0.933 (−8.3 pts) | contradicts |
| S3 attribution (exploratory) | — | robust − default −0.94 [−2.06, +0.18]; disciplined − robust −0.07 [−1.14, +0.99] | no conclusion |

The test is one-sided (disciplined > default) as pre-stated; the CI shows the observed effect runs the other way.

## 3. What this means

- **Which questions you ask matters.** The model choosing its own questions beats 15 random unlabeled cases by about 3 points. That's the one positive result.
- **A hand-written selection discipline doesn't help, and can hurt.** The model's default choices were already better than the branch-table plan. Neither half of the protocol pays off: the plan adds nothing over R2 alone (−0.07), and R2 alone trends negative (−0.94, CI crosses zero).
- **Why R2 hurts (post hoc, not a pre-registered claim).** R2 says "don't change a rule supported by ≥ 2 history cases on a single contradicting answer." When the histories themselves contain operator errors, R2 protects the error. On Q1, two history cases (Q1-0005, Q1-0022) are operator mistakes. Two of three disciplined runs (r1, r3) got one contradicting answer, kept the wrong rule under R2, and each missed 238 of 2,000 fresh emails on `not_entitled`. The third (r2) happened to get a second contradicting answer, changed the rule, and missed 0 — as did all three default runs. Q1_disciplined_r1 states this reasoning in its notes. This one rule accounts for essentially the whole Q1 gap. So the "be robust to oracle noise" rule trades a small, rare risk (ρ = 0.05 flips, ~1 per run) for a larger, systematic one (history noise).

## 4. Integrity audit (§5)

- `tools.py` and `state.json`: all 61 sandboxes match the original hashes.
- Deliverables: the only references to the pilot directory are the 61 generated `oracle.py` wrappers; no run references another sandbox.
- Transcripts (tool inputs only, latest transcript per sandbox): no reads of `data2`, `policy.txt`, `ref_procedure2`, `env2.py`, `bench2.py`, oracle logs, or any other sandbox; no direct access to any pilot file other than the two prompt files. About 35 runs viewed the `oracle.py` wrapper (which shows the backend's path, not its contents). Recorded, not voided. `results/v4_integrity_tx.json` has the per-run scan.
- **Voided runs: none.**
- Self-reported protocol deviations (`results/v4_deviations.txt`): Q2_disciplined_r5 asked 4 follow-ups beyond its plan; Q1_disciplined_r2 swapped one planned question; Q4_disciplined_r6 and Q4_random_r2 each asked one case twice; Q3_default_robust_r2 wasted 2 questions on its own slips. Kept as run. Sensitivity (exploratory): dropping the three Q2–Q4 deviation runs leaves disciplined − default at −1.01 and default − random at +2.81.
- Flip counts per run differ across arms within a replicate only because the schedule is indexed by question number and some runs asked fewer than 15.

## 5. Limits

- Power: as stated in the pre-registration, a NO means no *large* effect. Here, the point estimate is negative, so it's not a near-miss either.
- Subagents aren't compute-matched; the disciplined arm did more pre-work, which should have biased *toward* it.
- One model (Sonnet), one synthetic benchmark, one protocol. A NO falsifies this protocol, not every selection policy.

## 6. Where the thread stands

| Experiment | Question | Answer |
|---|---|---|
| v3 | Does verifier-first beat simpler uses of the same expert questions? | No (+0.6 pts, CI crosses 0) |
| v4 | Does a disciplined question-selection protocol beat the default? | No (−1.0 pts, CI excludes 0 on the wrong side) |
| both | Do expert questions help at all? | Yes: +9.5 pts over history alone (v3); model-chosen beats random by +3.3 (v4) |

Files: `analyze_v4.py`, `results/v4_runs.json`, `results/v4_analysis.json`, `results/arms_v4/`, `results/oracle_logs_v4/`, `results/v4_integrity_tx.json`, `results/v4_deviations.txt`.
