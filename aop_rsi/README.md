# aop_rsi — scaffold (DESIGN.md §12)

Firm-agnostic code for the parts of the harness that come *before* the loop: the case
schema and loaders, the four-role split, the bucket scorer, the verifiable floor, the
field extractor, the problem-indexed edit library, and experiments E0′–E2. No optimizer,
judge, or gate — per `DESIGN.md` §11 those are not built until E0′–E2 pass on the target
mailbox.

Everything runs with no model calls against the synthetic confirmations environment
(`pilot/env2.py`), so each component is exercised before it meets firm data.

```
python -m aop_rsi.experiments.run_all --env2 Q2             # synthetic policy Q2
python -m aop_rsi.experiments.run_all --firm export.jsonl   # firm export
```

## Layout

| Path | What |
|---|---|
| `cases/schema.py` | `Case` = (email, reply_text, snapshot); `ReplyFields`; the closed `Snapshot` tool vocabulary |
| `cases/split.py` | Roles by time order: learning / search_validation / final_test (`DESIGN.md` §7) |
| `cases/parse.py` | Deterministic as-of date and stated-quantity parsing from the email |
| `cases/signature.py` | Observable case parameters at coarse / decision / fine granularity |
| `cases/adapters/env2.py` | Cases from the synthetic environment, matching `pilot/bench2.build` case for case |
| `cases/adapters/firm.py` | **The firm export contract**: JSONL schema and `RecordedSnapshot` over recorded tool results |
| `complexity/buckets.py` | (complexity, completeness) per case from email + snapshot only (`DESIGN.md` §5) |
| `reward/fields.py` | Reply text → structured fields; per-field agreement. The core of the field-level judge |
| `reward/verifiable.py` | The floor (`DESIGN.md` §4.1): identifiers resolve, figures and dates match the snapshot, internally consistent. Facts only — never the business decision |
| `memory/library.py` | Problem-indexed edit library (`DESIGN.md` §9.1); `inherit()` for transfers (§9.2) |
| `baselines.py` | `MajorityBaseline`, `RetrievalBaseline` — the control arm |
| `experiments/e0_noise_floor.py` | E0′: operator noise floor from intra-cluster disagreement; no labels needed |
| `experiments/e1_snapshot.py` | E1: does the snapshot reconcile, and is it point-in-time rather than current-state |
| `experiments/e2_baseline.py` | E2: per-bucket baseline rates; frontier buckets for E3 |
| `experiments/results/` | Outputs on env2 Q1–Q4 |

## What the environment runs say (Q1–Q4, 400 cases each, ρ_op = 0.2)

- **E0′.** The intra-cluster disagreement bound depends on signature granularity exactly as it should: coarse ≈ 0.4 (unobserved parameters dominate), decision-level 0.06–0.12, fine 0.04–0.05, against a true operator-error rate of 0.065. At the decision level, "minority outcome in its cluster" flags a perturbed reply with precision 0.68 (Q2) and recall 0.72 within clusters. The estimator works, and the decision-level signature is the one to use.
- **E1.** 100% reconciliation; positions moved between as-of and reply time in 23% of dated replies. The movement check is what would catch a current-state export on firm data.
- **E2.** Deterministic retrieval over 200 learning cases scores 0.65–0.83 full-field agreement with the historical reply on validation (gold outcome 0.67–0.89), against 0.21–0.50 for the majority class. For comparison, the pilot's LLM history-only arm reached 0.87 from 25 histories: an LLM induces rules a nearest-signature lookup cannot. Frontier buckets (0.3–0.7) exist in every policy, so E3 would have signal.

## Firm handover

1. Write the export job to `cases/adapters/firm.py`'s schema. Record positions for the as-of
   date the reply states *and* the email's sent date; the SOR is not replayable.
2. `run_all --firm`. Read E1 first. If it fails or is SUSPECT, fix the export; nothing else is valid.
3. Read E0′ at the decision level. That number is the ceiling on judge agreement with operators.
   If it is high, the labeling protocol (reasons, not bare verdicts) is the fix, not the judge.
4. Read E2. Retrieval is the control arm. The frontier buckets are where the regression set
   should be stratified and where E3 samples.
5. Replace `RegexFieldExtractor` with an LLM-backed extractor of the same interface and
   measure its accuracy on the operator-verified regression set before trusting field agreement.

Hidden environment fields (gold outcome, perturbation flags) live only in
`Case.meta["_benchmark"]`; every number that uses them is labeled benchmark-only and has no
firm counterpart.
