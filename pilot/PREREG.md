# Pre-registration — decisive pilot (written before any run, 2026-10-26)

## Question

Does learning a verifier first, then searching against it, beat the simpler ways of spending the same expert questions, on a benchmark where history alone leaves headroom?

## Design

- **Environment:** v2 (`env2.py`), verified solvable (reference procedure 2,400/2,400).
- **Policies:** Q2, Q3, Q4.
- **Inputs every arm gets (identical):**
  - 25 labeled histories (request + operator reply + decision)
  - 175 *unlabeled* requests (no reply)
  - 13 tools
  - the agreement harness
  - the same README
- **Oracle:** verdict + one-sentence reason on any (history or unlabeled) request and a proposed response. Budget **15 questions**; noise ρ = 0.05. The no-oracle arm gets none.
- **Arms:**
  1. **History-only** — no oracle.
  2. **Policy-first** — write a procedure; spend questions on its own outputs; fix.
  3. **Spec-once** — write a rule spec; spend questions testing uncertain rules; implement once.
  4. **Verifier-first** — write a reference-free checklist verifier; spend questions calibrating it; then search procedures by verifier pass rate over the 200 labeled + unlabeled requests.
- **Replicates:** 3 independent runs per arm per policy, giving 36 runs. Each run is isolated in its own sandbox with its own scratch directory.
- **Metric:** exact correctness against the executable policy on 2,000 fresh emails per policy, plus questions used.

## Decision rules (fixed now)

**Q1 — Do expert questions help at all?** YES if the best oracle arm's mean exceeds history-only by ≥ 3 points and wins on all 3 policies.

**Q2 — Do we have something (verifier-first)?** YES if verifier-first:

- beats **both** policy-first and spec-once by ≥ 2 points in pooled mean accuracy, with the 95% bootstrap CI of the difference (resampling runs within policy) excluding 0, **and** wins on at least 2 of 3 policies; **or**
- matches the best of them (within 1 point) using ≤ 70% of the questions on average.

**NO** if verifier-first is within 2 points of, or below, the better of policy-first and spec-once, with no question savings.

**INCONCLUSIVE** otherwise. That outcome is reported as inconclusive, not reinterpreted.

## Known limitations, stated in advance

- Subagents are not compute-matched; tokens and tool calls are reported per run.
- The benchmark is synthetic. A YES here is a reason to run the API version and the real desk, not a publishable result by itself. A NO here, on a benchmark built to favor the method (headroom in rare rules, unlabeled pool available), is strong evidence against the method claim.
