# Decisive pilot — results (2026-10-26)

Pre-registered in `PREREG.md` (commit 56760fa) before any run. Analysis is mechanical: `analyze_v3.py`, output in `results/v3_analysis.json`. Per-run scores are in `results/v3_runs.json`; every run's procedure, verifier, spec and notes are in `results/arms_v3/`; every oracle question is in `results/oracle_logs_v3/`.

## Verdict

| Pre-registered question | Answer |
|---|---|
| Q1: Do expert questions help at all? | **YES.** +9.5 points over history-only (0.870 → 0.965), on all three policies. |
| Q2: Does verifier-first beat the simpler uses of the same questions? | **NO.** +0.6 points vs policy-first (95% CI −1.4 to +2.7), +1.0 vs spec-once (CI −0.7 to +2.7). Same questions used (15). Below the 2-point bar and inside noise. |

**Verifier-first is not a better way to spend expert time than just asking about your own procedure's outputs.** The thing that matters is asking at all.

## Numbers

Exact correctness against the hidden executable policy on 2,000 fresh emails per policy. Mean of 3 independent runs per cell.

| Arm | Q2 | Q3 | Q4 | Pooled | Questions |
|---|---|---|---|---|---|
| History only | 0.878 | 0.834 | 0.898 | **0.870** | 0 |
| Policy-first | 0.937 | 0.984 | 0.957 | **0.959** | 15 |
| Spec-once | 0.933 | 0.972 | 0.961 | **0.956** | 14.8 |
| Verifier-first | 0.943 | 0.964 | 0.987 | **0.965** | 15 |

Run-level spread within a cell is up to 15 points for history-only (Q4: 0.796–0.953) and 3–7 points for the oracle arms. Verifier-first had the best single run on two policies and the tightest spread on Q4, but also the second-worst oracle-arm run on Q3.

## What the runs show

1. **Fifteen questions buy roughly ten points, and all three strategies spend them on the same things.** These are the rules the 25 histories never show or show once: the 1M escalation, non-business-day dates, comparing against settled plus pending, pre-split client figures, the no-email-confirmation flag, and what to do when nothing is held but the client quotes a figure. Reading the oracle logs, the three strategies converge on nearly the same questions. The strategy wrapper barely changes what gets asked.
2. **The verifier's 200/200 pass rate is circular, and several runs said so themselves.** The procedure is searched against the verifier, so agreement between them is guaranteed. That self-consistency carries no information the oracle answers did not already supply.
3. **Remaining errors are threshold guesses inside gaps nobody asked about.** These include the exact tolerance (anywhere from 2–8%) and the pending window or cutoff. They are inherently cheap to fix with one more targeted question each, and no strategy reliably found them within 15 questions.
4. **Unlabeled requests did not help verifier-first win.** It was the only arm instructed to use them as a search objective. Every arm had them.

## Threats to validity, and whether they change the verdict

- **Subagents are not compute-matched.** Tokens per run: history-only about 120–170k, oracle arms about 160–220k; verifier-first used slightly more. Higher compute for verifier-first would bias toward YES, so the NO stands.
- **Only 3 replicates.** The CI on the verifier-first advantage is about ±2 points. A true advantage of more than 3 points is unlikely; one under 2 points cannot be excluded. It would not meet the pre-registered bar or justify the method's complexity in any case.
- **Isolation.** Two oracle-arm runs printed the three-line `oracle.py` wrapper. It contains no rules, only a path. No deliverable references hidden data (grep of all procedures and verifiers is clean).
- **Synthetic benchmark.** A NO here means the method claim is not supported on a benchmark built with headroom where it was supposed to help: rare rules plus an unlabeled pool. It does not prove a real desk would behave the same, but it removes the reason to expect otherwise.

## What this means for the research

**The verifier-first method claim is dead in its current form.** On this evidence, a paper arguing "learn the verifier first" would not survive the spec-once and policy-first controls the reviewer asked for.

**What survived, and is real:**

- **Expert questions are worth about ten points at N=25, in every arm and every policy.** The value is concentrated on rules that are rare or absent in history. That is a clean, replicated result, and the label-efficiency question ("how many questions, about which cases") is still open.
- **History alone plateaus around 0.87 here, with large run-to-run variance (up to 15 points).** Expert questions mainly cut variance and remove one-off rule gaps.
- **The benchmark itself works.** It is solvable (the reference procedure scores 2,400/2,400), exposes composition traps that every arm learned to avoid, and separates history-only from expert-assisted methods by 10 points with low within-arm variance for the latter.

If there is a paper here, it is no longer "verifier-first". It is closer to **"where expert time goes when inducing procedures from outcome histories"**: a benchmark, the ~10-point value of a small question budget, the finding that question *selection* rather than spec/verifier/policy representation is what matters, and an analysis of which rule types consume the budget. That is a smaller, honest contribution. Whether it is worth pursuing is a separate decision; this pilot does not make it for you.
