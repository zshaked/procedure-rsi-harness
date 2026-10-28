# Pre-registration — question selection (v2 of this document, after independent review; written before any run, 2026-10-27)

The first draft (commit 1 earlier today) was reviewed by an agent with no stake in the outcome. Its blocking findings and the fixes are recorded in §6 so the changes are auditable. No run was started under the first draft.

## 1. Question

Given the same 15 expert questions, does a disciplined selection protocol beat the LLM's default choice of what to ask? Secondary: does a confirmation rule for noisy answers help on its own, and does selection matter at all versus random?

## 2. Design

- **Environment:** v2 (`env2.py`). Decision policies **Q2, Q3, Q4**; **Q1 is a held-out confirmatory policy** the protocol was not tuned on.
- **Sandbox (identical across arms):** 25 histories with operator reply text *and* the reply's fields; 175 unlabeled requests; 13 tools; a harness reporting outcome agreement and full-field agreement; an oracle with 15 questions.
- **Oracle noise:** ρ = 0.05, keyed on (policy, replicate, question index) so every arm in replicate r faces the same flips. Flipped answers carry reasons drawn from the same pool as genuine ones. The schedule is published in `results/v4_noise_schedule.json` (25 flips in 360 slots).
- **Arms** — all policy-first in form; prompts are committed verbatim in `prompts/` and differ only in the arm-specific section:
  1. **default** — rerun today from `prompts/v4_default.txt` (the v3 wording). Not reused.
  2. **random** — 15 unlabeled cases drawn uniformly per replicate (seeded), asked sequentially in fixed order with fixes allowed between. `prompts/v4_random.txt`.
  3. **default_robust** — default plus rule R2: a rule supported by ≥ 2 history cases is changed only after two contradicting answers on different cases. `prompts/v4_default_robust.txt`.
  4. **disciplined** — R2 plus a one-shot selection plan: a required branch tag per request; unsupported branches (≤ 1 history case) first, ordered by unlabeled traffic; then parameter edges and unsupported conventions; branches with ≥ 2 field-level-agreeing history cases are not asked about; plan truncated to 15, no re-planning. `prompts/v4_disciplined.txt`.
- **Replicates:** default and disciplined **6** per policy on Q2–Q4 (the powered comparison); random and default_robust **3** per policy; Q1 confirmatory **3** each for default and disciplined. **60 runs.** Each run isolated in its own sandbox with its own scratch directory; the same model for every run.

**Amendment (2026-10-28, before any counted run completed):** the first launch of 20 runs on the session model (Fable 5.1) was killed by the account usage limit before any run asked a question or wrote notes; those sandboxes were wiped and re-exported. All 60 runs will use the **Sonnet** subagent model (Agent `model: sonnet`) for every arm, so the comparison stays within one model; results are therefore "for Sonnet-class models" and are not numerically comparable to v3 (Opus 5.5). A single uncounted smoke run (`Q2_smoke_r9`, default arm) runs first as a floor-effect guard: if it cannot produce a procedure scoring ≥ 0.75 on fresh emails, the model is too weak for the task and the experiment is not run on it. This guard is a feasibility check, not a decision rule.
- **Metric:** exact correctness against the executable policy on the same 2,000 fresh emails per policy as v3. Also recorded per run: questions used, regressions per rule vs history-only (from v3), and an integrity audit (§5).

## 3. Decision rules (fixed now)

Pooled mean over Q2–Q4. Significance by a **permutation test** on run labels within policy (10,000 permutations), one-sided where the direction is pre-stated; 95% CI by bootstrap for reporting only.

- **S1 — Selection matters at all:** `default − random ≥ 3` points, p < 0.05. If `random ≥ default`, selection is irrelevant at this budget; the thread stops regardless of S2.
- **S2 — Disciplined beats default (primary):** `disciplined − default ≥ 3` points, p < 0.05, and disciplined's mean is higher on ≥ 2 of 3 policies. YES/NO.
- **Q1 confirmatory:** reported separately. If S2 is YES on Q2–Q4 but disciplined is worse than default on Q1 by ≥ 3 points, the result is reported as **in-sample only**, not YES.
- **S3 — Attribution (exploratory, no decision attached):** `default_robust − default` and `disciplined − default_robust`, each with CI. With ~1–2 actionable flips per run this is underpowered; it is reported, not concluded on.
- **Power, stated:** with v3's within-cell SD (~0.025) and 6 vs 6 runs per policy, the chance of S2 firing for a true +3 is roughly 0.6, for +5 roughly 0.95. A NO therefore means "no large effect", not "no effect".

## 4. Continue / stop

- S2 YES (and Q1 not contradicting) → one more session (budget sweep 5/15/30 × history 10/25/50), then write: benchmark, representation null, selection result.
- S2 NO → write the benchmark and the two nulls as a workshop note; stop the research thread.

## 5. Integrity

- After all runs: hash `tools.py` and `state.json` in every sandbox against the originals; grep every deliverable for references to hidden paths; grep every run transcript (without reading it) for reads of `data2`, `policy.txt`, `ref_procedure2`, or another sandbox. Any hit voids that run; voided runs are listed in the results.
- The oracle's log records the true verdict alongside the delivered one, so flips can be audited.
- Prompts contain no hidden rule names; the only rule-shaped words in them are example branch labels that are also visible in the histories.

## 6. Review findings and what changed

| # | Finding (severity) | Change |
|---|---|---|
| 1 | Noise keyed on sandbox name; arms got different flip schedules (blocking) | Keyed on (policy, rep, idx); schedule published |
| 2 | Reused v3 default invalid: prompt not in repo, saw almost no noise, conditional rerun was a free choice (blocking) | Default rerun today from a committed prompt; no conditional |
| 3 | Disciplined protocol oversubscribed, no tie-break, "branch" undefined (blocking) | Required `decide()` branch tag; deterministic order; truncate to 15; plan once |
| 4 | Protocol contradicted its motivation: forbade asking about `confirm`, where field-level gains lived; "prior-handled" claim leaks rule names (should-fix) | Harness and S4 use full-field agreement; prior-handled metric dropped |
| 5 | "Not sure" phrase appeared only on one noise direction — R1 encoded the implementation (should-fix) | Symmetric uninformative noise; R1 removed; only R2 kept |
| 6 | Random arm: batch vs sequential unspecified, drew from labeled histories (should-fix) | Sequential fixed order, fixes between, unlabeled only |
| 7 | Underpowered at 3 reps; bootstrap anti-conservative; "a NO is strong" false (should-fix) | 6 reps on the key arms; permutation test; power stated; S3 exploratory |
| 8 | In-sample tuning (note) | Q1 held out as confirmatory |
| 9 | Log dir collision; hash tools post-run; record model (note) | `oracle_logs_v4`; integrity audit in §5; model recorded |

## 7. Known limitations

- Subagents are not compute-matched; the disciplined arm does more pre-work, which biases toward it. A marginal YES must be reproduced with the API harness before being claimed.
- A NO falsifies this protocol, not every possible selection policy.
- The benchmark is synthetic; the firm replication is the external-validity check and is not part of this experiment.
