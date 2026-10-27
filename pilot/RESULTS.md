# Pilot results — smoke test (2026-10-26)

**Verdict: the benchmark as built is too easy to tell the arms apart. Every method recovers the hidden procedure almost perfectly from 200 outcome-only histories. Nothing here supports or refutes verifier-first. What it does show is what the benchmark has to become before a comparison means anything.**

## Setup

- Environment: synthetic position confirmations (`env.py`), with five executable hidden policies. P3 and P4 are held out and were used for every arm below.
- Each arm was a subagent working in a sandbox with only the method-visible files (`export_public.py`):
  - 200 learning histories: request, reply text, and the operator's decision
  - 4 tools
  - a harness reporting agreement with the operators' decisions
  - a budgeted oracle
- Operators: 1/15 of historical replies are harmful errors (ρ_op = 0.2, one third harmful). Oracle noise: ρ = 0.05.
- Deliverable: an executable `procedure.py`, graded by the hidden executable policy. No LLM is involved in grading.
- Grading sets: search validation (100), final test (100), and 2,000 fresh requests per policy (`fresh_eval.py`).

## Results

| Arm | Oracle Qs | P3 final | P3 fresh 2k | P4 final | P4 fresh 2k |
|---|---|---|---|---|---|
| true spec revealed | 0 | 1.00 | 1.000 | 1.00 | 1.000 |
| history only | 0 | 0.96 | 0.970 | 1.00 | 1.000 |
| policy-first | 12 / 19 | 1.00 | 1.000 | 1.00 | 1.000 |
| spec-once-then-policy | 23 / 21 | 1.00 | 1.000 | 1.00 | 1.000 |
| verifier-first | 21 / 21 | 1.00 | 1.000 | 1.00 | 0.998 |

Oracle questions are listed as P3 / P4.

The verifier-first arms' learned verifiers agree with the executable policy on 200/200 checks per policy, including deliberately mutated (wrong) responses: 0 false accepts, 0 false rejects.

LLM-free baseline (`phase1.py`): a decision tree on hand-built perfect features reaches 0.92–0.95 from 200 histories, and 0.67–0.75 from 25.

## What we learned

1. **Two hundred clean outcome histories are enough.** Given four obvious tools and structured request fields, an LLM recovers a 9-parameter procedure from outcomes alone, with zero expert questions. P4 came out perfect. P3 missed only one threshold: the history-only arm guessed zero tolerance from contradictory examples, which costs 3% on fresh requests.
2. **Expert questions bought exactly one thing: thresholds that fall in gaps no history covers.** Every oracle arm spent its questions resolving the quantity tolerance, the pending cutoff, and suspected operator errors. Policy-first did it on P3 with 12 questions, against 21–23 for spec-once and verifier-first.
3. **Operator errors were not a problem.** All arms correctly identified the harmful historical replies as mistakes, mostly by majority evidence, and the oracle confirmed them.
4. **Unexercised boundaries are where the remaining risk lives.** P4 verifier-first confirms when settled is 0 but pending is positive. No history covered that case, and the arm flagged it as uncertain. That is 4 errors in 2,000.

## Why the benchmark is too easy, and what to change

The real-desk blocker is discovering which lookups and compositions to run. This environment hands it over:

- **Too few tools, too obvious.** Four tools, one per concept. *Change:* 12–20 tools with overlapping, partial and distractor endpoints, where a correct answer needs a composition (e.g. a position plus a corporate-action adjustment plus a pending-instruction lookup).
- **Requests arrive pre-parsed.** *Change:* raw email body only, with free-form phrasing, forwarded threads, and multiple asks per email.
- **Rules fire often.** Every rule triggers dozens of times in 200 histories. *Change:* a long tail of rules that each fire in under 1% of cases, so no history covers them. This is where the oracle budget and a verifier can matter.
- **Few interactions.** *Change:* rules that override each other conditionally, and per-client exceptions.
- **Too many histories.** *Change:* sweep N ∈ {10, 25, 50}, the regime where the decision tree also degrades.
- **Grading is per-case exact.** Keep this; it worked.

## Process issues to fix before the real run

- **Arms shared a scratch directory.** Two arms report another arm overwrote a helper script. Both say they saw only generic code or a case list, never oracle answers, but it is a contamination risk. *Fix:* per-arm scratch, enforced.
- **Subagents are not compute-matched.** Tool calls ranged from 9 to 37 and tokens from 77k to 156k. *Fix:* the API-driven harness with fixed budgets per arm.
- **One run per arm.** No variance estimate.
- **Rule numbering in the rendered policy skips numbers.** Two true-spec arms noticed. Cosmetic.

## Decision

Do not run the full pilot on this environment. Harden the benchmark along the five changes above, re-run the decision tree and history-only arms first (both cheap), and only proceed to oracle arms once history-only falls below ~0.8 on held-out policies. If no realistic hardening gets it there, that is itself the finding: outcome histories suffice for procedures of this complexity, and expert time should go to the long tail.
