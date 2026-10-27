# Pilot v2 — hardened benchmark, cheap baselines (2026-10-26)

**Verdict: v2 opens real headroom, but less than the gate asked for.** History-only LLM procedures score 0.83–0.955 on fresh emails (mean 0.895), against a gate of about 0.8. The errors are not diffuse. They sit almost entirely in rules that are rare or absent in the 25–50 histories, which is exactly the slice expert questions are meant to buy. Worth running the oracle arms, at N = 25 and with replicates, because run-to-run variance is as large as the effect of history size.

## What changed from v1 (`env2.py`)

- **Requests.** Raw emails with greetings, signatures, forwarded headers and free-text dates ("end of last month", "3/3/2026", "yesterday") and quantities ("12.5k", "1.2mm"). Account and instrument spans arrive unnormalized, as an upstream extractor would give them.
- **Tools.** Thirteen overlapping tools; the correct figure needs several of them combined:
  - ledger transactions per custody sub-account, recorded in pre-split units, plus a corporate-actions lookup
  - instruction status (cancelled and unmatched instructions excluded)
  - entitlements per contact and account, with expiry
  - client profiles
  - a business calendar with holidays
  - a stale convenience summary that is wrong for about 44% of confirmations
- **Rare rules.** Legal hold, client opt-out of email confirmations, expired entitlements, future dates, non-business dates, implicit account, pre-split stated quantities.
- **Solvability check.** A reference procedure using only the public tools and email text scores **2,400/2,400 on every policy** (`ref_procedure2.py`), so every miss below is the method's, not the environment's.

## Results

Held-out policies Q3 and Q4. Each arm is a single subagent run with its own scratch directory inside its sandbox, and no oracle. Graded by the executable policy on 100 final-test cases and 2,000 fresh emails.

| Arm | N histories | final test | fresh 2,000 | largest miss sources (fresh) |
|---|---|---|---|---|
| Q3 history-only | 25 | 0.87 | **0.830** | non-business-day handling (233), 1M escalation never seen (25), pending threshold |
| Q3 history-only | 50 | 0.96 | **0.955** | 1M escalation seen once and dismissed as operator error (25), no-holding edge (21) |
| Q4 history-only | 25 | 0.90 | **0.914** | "as_of_assumed" convention guessed wrong, future dates, ambiguous-account handling |
| Q4 history-only | 50 | 0.89 | **0.880** | check order (authorization vs missing details), no-holding treated as REQUEST_INFO |

Perfect-feature decision tree (what to look up is given to it), mean over Q0–Q4: 0.58 at N=10, 0.66 at N=25, 0.79 at N=50, 0.92 at N=200 (`results/v2_tree.json`).

## What we learned

1. **The LLM beats the perfect-feature tree at small N** (0.83–0.91 vs 0.69–0.77 on Q3/Q4 at N=25). LLM priors about how a desk "should" work fill gaps the data cannot. Sometimes they fill them wrongly: rolling weekend dates back where this desk asks instead.
2. **Remaining errors are rule gaps, not composition failures.** Every arm got the composition right: sub-account sums, split adjustment, and instruction status. Every arm also identified the distractor summary tool as a trap. The misses are rules with zero or one supporting history.
3. **A rule seen once gets dismissed as noise.** Q3 at N=50 saw the 1M escalation in one case and treated it as an operator mistake. That costs 25 errors in 2,000. A single expert question would have settled it. This is the cleanest example yet of where expert time is worth spending.
4. **Run-to-run variance is large.** Q4 scored 0.914 at N=25 and 0.880 at N=50. One run per cell cannot separate a method effect of a few points.

## Decision

- **Proceed to the oracle comparison on v2 at N=25**, where headroom is largest (9–17 points). Arms: history-only, policy-first, spec-once, verifier-first.
- **Replicates are required.** At least 3 seeds per arm per policy; the variance seen here would swamp a 3–5 point effect.
- **Compute matching** still needs the API harness. With subagents, report it as a smoke-level comparison only.
- **Expected outcome if the thesis has legs:** oracle arms close the rare-rule gap, and verifier-first does so with fewer questions or generalizes better on rules absent from the histories. If policy-first closes the same gap with the same questions, the verifier is overhead. That is the spec-once control from the review, now testable.
