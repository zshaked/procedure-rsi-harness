# Pre-registration — the reusable-holdout problem in harness optimization (draft 1, written before any run, 2026-11-17)

Status: **first draft, not yet reviewed.** As with `pilot/PREREG_v4.md`, this document goes to an independent reviewer with no stake in the outcome before any counted run starts; blocking findings and fixes will be recorded in §7. No code has been written under this design.

Motivation and the theory this tests are in `docs/descent.md` §2.2. The study is a continuation of the thread in `paper/OUTLINE.md`, not a restart: the pilot's nulls concerned *which expert questions* to ask; this concerns *how many times the optimizer may consult its validation set* before that set stops measuring anything.

## 1. Question

Harness optimizers — GEPA, ACE, OPRO, Meta-Harness, AHE, Harness² and the loop in `DESIGN.md` — select among candidate edits by evaluating them on a validation set, repeatedly and adaptively: each proposal depends on earlier results. Adaptive data analysis says the gap between validation and true performance can then grow like √(k/n) in k reads on n items, versus √(log k / n) when the k candidates are fixed in advance. Published optimizers report on a separate test set, so their *reported* numbers are not the target. The target is the regime where a sealed test does not exist: a continual self-improvement loop in production, where the validation set is the only signal and is consulted every epoch.

**Primary.** After k adaptive validation reads on n items, what fraction of the validation gain survives on a never-touched test set?

**Secondary.** Does a thresholded, read-budgeted gate (a Ladder / Thresholdout analogue; the noise-floor gate of `docs/metrics.md` §4) raise the surviving fraction at matched k, without lowering test performance?

**Exploratory, no decision attached.** (a) Does the excess gap grow with √(k/n) as predicted, and how much of it is attributable to adaptivity rather than to selection per se? (b) Is the proposer informed — does it accept more often than a random-mutation proposer under the same gate?

## 2. Design

### 2.1 Optimizers

Run as published, unmodified except for a logging hook that records every validation read (candidate id, items read, score, timestamp) and the incumbent after each read.

1. **GEPA** (public DSPy implementation) — reflective, Pareto-front selection on validation. The strongest and most-cited current optimizer.
2. **OPRO-style loop** (implemented in `audit/`, ≤ 300 lines) — trajectory of (prompt, score) in the optimizer's context, best-on-validation selection. The simplest adaptive optimizer; exists so that the result is not about GEPA's particulars.
3. *Stretch, if code is available and runs within budget:* **ACE / Dynamic Cheatsheet** playbook curation.

### 2.2 Benchmarks

Each must have a pool large enough to carve disjoint train / validation / sealed-test splits with a sealed test of ≥ 500 items.

1. **HotpotQA** (as in the GEPA paper; exact-match answer scoring, no LLM judge, so the metric itself cannot be gamed). Pool: the standard dev set, several thousand items.
2. **Confirmations environment** (`pilot/env2.py`, executable hidden policies; correctness computed, not judged). Fresh requests are generated per split, so the sealed test is unbounded and ground truth is exact.
3. *Stretch:* **τ-bench retail** — agentic, tool-using, expensive. Included only if the two core benchmarks come in under budget.

### 2.3 Data roles

| Role | Size | Touched by |
|---|---|---|
| Train | optimizer's native requirement | optimizer only |
| Validation | n ∈ {50, 200} | optimizer's selection, k times; re-sampled from the pool per seed |
| Sealed test | ≥ 500 | the final evaluation script only, once per snapshot; never by any optimizer, gate, or human decision during the run |

### 2.4 Manipulations

- **k, adaptive reads.** Each run proceeds under the optimizer's native loop. The incumbent is snapshotted by *read count*, not by score, at k ∈ {0, 5, 10, 20, 50, 100}. Each snapshot is scored once on sealed test. k = 0 is the initial prompt and measures the distribution-shift component of the gap that has nothing to do with selection.
- **n, validation size.** {50, 200}, crossed with k.
- **Gate.** Two arms per optimizer: *native* selection as published, and *Ladder*: a candidate replaces the incumbent only if its paired validation improvement exceeds a noise floor η estimated by bootstrapping the incumbent's own per-item validation scores (`docs/metrics.md` §4.1), with the read count logged and the run halted at k = 100 regardless.
- **Non-adaptive control.** k candidates generated *before* any validation feedback (the initial proposer sampled k times with different seeds); the best on validation is selected once. This is the √(log k / n) reference. The difference between adaptive and non-adaptive leak at matched k isolates adaptivity's contribution from selection's.
- **Random-mutation control (exploratory).** The optimizer's proposer replaced by content-free mutations (paraphrase, demonstration reorder, instruction deletion) under the same gate. Measures proposer informedness as acceptance rate relative to this baseline.

### 2.5 Replicates and model

≥ 3 seeds per cell; each seed re-draws the validation sample from the pool. One model for all arms within a benchmark, recorded in `results/`. A **pilot cell** — one optimizer, one benchmark, n = 50, 3 seeds, k ≤ 50 — runs first to estimate the per-cell standard deviation and cost; seeds for the full grid are set from it (§3, power) and the grid is cut per §4 if cost exceeds the cap.

### 2.6 Metrics (per snapshot, per seed)

```
val_k, test_k           incumbent score on validation and sealed test at read k
gap_k   = val_k − test_k
leak_k  = gap_k − gap_0                       excess gap attributable to selection
surv_k  = (test_k − test_0) / (val_k − val_0) fraction of validation gain that is real
```

`surv_k` is undefined when `val_k − val_0 ≤ 0`; such seeds are reported and excluded from the ratio, and the absolute `leak_k` is reported alongside for every cell. Also recorded: acceptance count per read, candidate id per read, and for the Ladder arm the estimated η per epoch.

## 3. Decision rules (fixed now)

Pooled over the two core optimizers and two core benchmarks unless stated. Bootstrap over seeds for CIs; permutation test on arm labels within (optimizer, benchmark, n) for comparisons; one-sided where direction is pre-stated.

- **A1 — Primary, survival at k = 100, n = 50.** `surv_100 < 0.75` with the 95% CI upper bound below 1.0 → **YES**: a quarter or more of the validation gain is not real at this scale. Otherwise **NO**: gains largely survive. Reported for n = 200 as well; A1 is decided on n = 50 because that is the production-realistic size.
- **A2 — Ladder gate.** `leak_100(native) − leak_100(Ladder) ≥ 1.0` point with 95% CI excluding 0, **and** `test_100(Ladder) ≥ test_100(native) − η` → **YES**: the gate buys generalization without costing performance. If the gate reduces leak only by reducing `val_k` (fewer accepts, no better test), that is **NO** and is said plainly.
- **A3 — Exploratory.** Spearman correlation of `leak_k` with √(k/n) across all (k, n) cells, pooled; and `leak_k(adaptive) − leak_k(non-adaptive)` at matched k. Reported with CIs; no decision attached.
- **A4 — Exploratory.** Acceptance rate of the native proposer vs the random-mutation proposer at matched k. Reported; no decision attached.
- **Power, to be stated after the pilot cell.** The pilot cell's SD sets seeds for the grid. The target is 0.8 power to detect `surv = 0.75` against `surv = 1.0` at n = 50, k = 100. If that needs more than 6 seeds per cell, the grid is cut per §4 rather than the threshold moved.

## 4. Continue / stop

- **A1 YES** → full grid including stretch items as budget allows; write-up as a main-track paper: the leak curves, the adaptive-vs-non-adaptive decomposition, the gate result, and the informedness metric. Framing: *continual harness optimization needs a reusable holdout.*
- **A1 NO** → write-up as a shorter note: the leak is small at this scale, here is the curve, here is the gate's effect anyway. Still the first measurement; the negative result is the result.
- **Budget cap.** A fixed dollar cap is set after the pilot cell and recorded here by amendment. If the full grid exceeds it, cut in this order: τ-bench, ACE, n = 200, k = 100. Never cut seeds below the power target; cut cells instead.
- **Stop.** If the pilot cell's SD implies the power target needs more than 12 seeds per cell, the design is underpowered for the budget and the study stops before the grid, with the pilot cell reported.

## 5. Integrity

- The sealed test is read by one script, `audit/eval_sealed.py`, which refuses to run unless the optimizer's run directory is marked complete and the snapshot list is already written. Its invocations are logged.
- Optimizer code is pinned by commit hash; the logging hook is the only modification and its diff is committed.
- Snapshot points are determined by read count in the hook, not chosen after seeing scores.
- Validation samples per seed are drawn from a seeded RNG whose seeds are committed before the runs.
- After all runs: grep every optimizer trace for reads of the sealed-test file paths; any hit voids that run and is listed.
- The random-mutation arm's mutation operators are committed before the runs and are the same across optimizers.

## 6. Known limitations

- The result is for the optimizers, benchmarks, model, and n range tested. "Leak is small on HotpotQA at n = 200 with GEPA" does not license "leak is small."
- Exact-match and executable-truth metrics are chosen so the *metric* cannot be gamed; the leak measured here is therefore pure selection leak. Loops with an LLM judge add a bias term (`docs/descent.md` §2.3) that this study does not measure. That is the next study, not this one.
- GEPA's Pareto-front selection reads validation per-item rather than as an aggregate; k is still well-defined as the number of candidate evaluations, but the √(k/n) reference was derived for aggregate queries and the fit in A3 is exploratory for that reason.
- The non-adaptive control uses the initial proposer, which is weaker than the adapted one; its candidates are worse, not just non-adaptive. The decomposition in A3 is therefore an upper bound on adaptivity's share.
- One model family. Model-family variation is appendix material if budget allows, not part of the pre-registered claims.

## 7. Review findings and what changed

*(To be filled after independent review, before any counted run. Format as in `pilot/PREREG_v4.md` §6.)*
