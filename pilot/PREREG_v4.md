# Pre-registration — question selection (written before any run, 2026-10-27)

## Question

Given the same 15 expert questions, does a disciplined selection policy — derived from the v3 gain analysis — beat the LLM's default choice of what to ask? And how much of any gain is selection versus noise handling?

## What v3 showed (`results/v3_gain_by_rule.json`)

- 17–36 of 135 questions per policy went to rules the model's prior already handled (zero history-only misses): legal hold, future dates.
- In Q4, oracle arms regressed on two common rules after acting on single noisy answers.
- Gains came from two sources: rules absent from the histories (Q3: 92% of gain) and under-determined parameters of common rules (Q2, Q4: 55–87%).

## Design

- **Environment:** v2 (`env2.py`), policies Q2, Q3, Q4. Identical sandboxes to v3: 25 histories, 175 unlabeled requests, 13 tools, harness, 15-question oracle with ρ = 0.05.
- **Arms** (all policy-first in form — write a procedure, ask about its own outputs, fix — differing only in *which* questions and *how answers are used*):
  1. **default** — the v3 policy-first runs, reused unchanged (9 runs). Selection: "ask where you are least sure."
  2. **random** — 15 cases drawn uniformly from the 200 in advance (seeded, listed in the sandbox). The model must ask exactly those, submitting its current procedure's output for each. Lower bound on selection.
  3. **default+robust** — default selection plus two answer-handling rules: treat "not sure, please double-check" as no information; do not change a rule supported by ≥ 2 history cases on one answer — ask a second, different case first. Isolates noise handling.
  4. **disciplined** — the robust rules plus a selection protocol: (i) run the procedure on all 200 requests and group them by the branch that decided each; (ii) a branch exercised by 0–1 history cases is *unsupported* — ask one representative case per unsupported branch; (iii) for every numeric threshold in the procedure, ask the unlabeled case nearest the threshold on each side; (iv) do not ask about branches supported by ≥ 2 agreeing history cases. Isolates selection on top of noise handling.
- **Replicates:** 3 per arm per policy. 27 new runs plus 9 reused. Each run isolated in its own sandbox with its own scratch directory.
- **Metric:** exact correctness against the executable policy on the same 2,000 fresh emails per policy as v3 (`bench2.evaluate`, seed unchanged). Also recorded: questions used, questions spent on prior-handled rules (legal_hold, asof_future), regressions per rule vs history-only.

## Decision rules (fixed now)

Pooled mean over policies; 95% bootstrap CI resampling runs within policy; "wins" = policies where the arm's mean is higher.

- **S1 — Does selection matter at all?** `default − random ≥ 3` points with CI excluding 0. If random ≥ default, selection is irrelevant at this budget and the thread stops.
- **S2 — Does the disciplined policy beat the default?** YES if `disciplined − default ≥ 3`, CI excludes 0, wins ≥ 2/3.
- **S3 — Attribution.** If S2 is YES, report `(default+robust − default)` and `(disciplined − default+robust)`; the larger is the finding. If S2 is NO but `default+robust − default ≥ 2` with CI excluding 0, the finding is noise handling alone.
- **NO** if neither S2 nor the S3 fallback holds. **INCONCLUSIVE** otherwise, reported as such.

## Continue / stop

- S2 YES → one more session (budget sweep 5/15/30 × history 10/25/50) and write the paper: benchmark, representation null, selection result.
- S2 NO and S3 fallback NO → write the benchmark and the two nulls as a workshop note; stop the research thread.

## Known limitations

- Subagents are not compute-matched. The disciplined arm does more pre-work, which biases toward it; a NO under that bias is strong, a marginal YES is weak and must be reproduced with the API harness before being claimed.
- The default arm is reused from v3 (same model, same sandboxes, two days earlier). If the reviewer or results suggest drift, default is rerun.
- The disciplined protocol is a hypothesis about *how* to select; a NO falsifies this protocol, not every possible selection policy.
