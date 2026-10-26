# Formal statements

Four pieces of math. Each section ends with what is actually computed and, after external review, with what it does *not* establish. §1 and §3 are load-bearing; §2 is background analysis; §4 is deferred with H5.

Revision note (v0.2): the review of commit 0c01a49 found that §2's "predicted flip point" and §3's "high-probability conditional guarantee" were not supported by the stated procedures. Both are corrected below. §1 is unchanged except for the independence caveat being made explicit.

---

## 1. Latent specification inference

### 1.1 Model

A desk's procedure has a correctness criterion that was never written down. Model it as a latent **specification** `S`: a set of conditions a correct response must satisfy.

Fix a hypothesis space of candidate rules `H = {h_1, …, h_M}` (a rule is a checkable predicate over `(request x, state s, response y)`; the space is seeded from priors, context, and rules distilled from histories, and grows when the taxonomy agent proposes new clusters). Represent the specification as `σ ∈ {0,1}^M`, `σ_j = 1` iff rule `h_j` is part of the desk's spec. Prior `p(σ)`.

A response is **acceptable** iff it satisfies every active rule that applies:

```
acc(x, s, y; σ) = ∧_{j : σ_j = 1, h_j applies to (x, s)} h_j(x, s, y)
```

Operators are noisy: an operator's verdict agrees with `acc` with probability `1 − ρ`. `ρ` is the irreducible noise, measured by the noise-floor check (`../DESIGN.md` §11, E0′).

### 1.2 Channels

Three observation channels, each with a likelihood and a cost:

| Channel | Observation | Likelihood | Cost |
|---|---|---|---|
| Histories `D_H` | `(x_i, s_i, y_i)` with `y_i` written by an operator | `p(y_i | x_i, s_i, σ) ∝ (1−ρ)^{acc} ρ^{1−acc}` over the response's rule satisfactions | ~0 (already exists) |
| Confirmed rules `D_R` | operator says `σ_j = 1` or `0` | `p(answer | σ_j) = 1 − ρ_R` | `c_R` per rule |
| Verdicts `D_V` | `(x, s, ŷ, v)`: operator says `v ∈ {0,1}` for candidate `ŷ` | `p(v | x, s, ŷ, σ) = (1−ρ)^{[v = acc]} ρ^{[v ≠ acc]}` | `c_V` per verdict |

The verifier is the posterior predictive: `P(acc(x, s, ŷ) = 1 | D)`.

### 1.3 Information

Specification entropy `H(σ | D)` is the quantity every channel reduces. Under a mean-field posterior (rules treated as independent given data — an approximation that is wrong whenever rules interact, e.g. an escalation rule that overrides a confirmation rule; the paper states this and reports the operational estimator of §1.4, which does not depend on it):

```
H(σ | D) ≈ Σ_j H_b(p_j),   p_j = P(σ_j = 1 | D),   H_b = binary entropy
```

The **yield** of a channel `c` is its information per unit cost:

```
Y_c = I(σ ; D_c) / cost(D_c) = [H(σ) − H(σ | D_c)] / cost(D_c)      (bits per unit cost)
```

### 1.4 Exchange rate

The quantity practitioners want: how many histories is one verdict worth?

**Formal:** `X_{H→V} = Y_V / Y_H` (histories per verdict at equal information).

**Operational (what the paper reports):** from the measured curves `κ(n_H)` (agreement vs histories, no verdicts) and `κ(n_V)` (agreement vs verdicts, histories fixed), the exchange rate at level `κ*` is the ratio of marginal costs:

```
X(κ*) = (dn_H / dκ)|_{κ*} / (dn_V / dκ)|_{κ*}
```

estimated by finite differences on the level set. It is a function of `κ*`, not a constant: histories are cheap early (they fix the common rules) and nearly worthless late (they never reveal the tail). That shape is itself a result.

### 1.5 Query selection as expected specification gain

The selection policy (`../docs/selection.md`) chooses the next oracle query to maximize expected information per cost:

```
q* = argmax_q  E_{v ~ p(v | q, D)} [ H(σ | D) − H(σ | D ∪ {(q, v)}) ] / c(q)
```

Under the mean-field posterior the inner expectation is computable per rule. **Practical estimator:** query-by-committee — maintain `K` candidate verifiers (samples from the posterior, or the rubric under `K` bootstrap resamples of `D`); the expected gain of a case is monotone in committee disagreement on it. This is the formal justification for the disagreement signals in the selection policy, and it is what Christiano et al. (2017) did with reward-model ensembles.

### 1.6 What is computed

- `p_j` for every rubric line: the verifier's calibrated per-line confidence, updated by each verdict (Beta-Bernoulli with the line's helpful/harmful counters).
- `H(σ | D)` as the mean-field sum, logged per epoch; plotted against κ. Prediction: κ is a monotone function of remaining entropy.
- Exchange rate from the curves, reported at κ* ∈ {0.5, 0.6, 0.7}.
- Committee disagreement as the selection score.

---

## 2. A Goodhart bound for optimization against a learned verifier — background analysis

**Status after review: valid inequality, not an operational predictor.** It is kept because it names the two quantities to track and gives the inner loop a stopping rule that does not depend on the verifier's opinion of itself. It is *not* used to predict a flip point or to define a κ threshold; H3 was rewritten accordingly (`OUTLINE.md` §4).

### 2.1 Setting

`r*(τ) ∈ [0,1]` true acceptability of a trajectory/response (the oracle, noise-free). `r̂(τ) ∈ [0,1]` the verifier. `δ(τ) = r̂(τ) − r*(τ) ∈ [−1, 1]`. `π_0` the reference policy (AOP_0, or the current accepted AOP_t); `π` a policy obtained by optimizing against `r̂`.

### 2.2 Statement

For any `π, π_0` over the same case distribution,

```
E_π[r*]  ≥  E_π[r̂]  −  E_{π_0}[δ]  −  2 · TV(π, π_0)                      (1)
```

and, in terms of gains over the reference,

```
E_π[r*] − E_{π_0}[r*]  ≥  ( E_π[r̂] − E_{π_0}[r̂] )  −  2 · TV(π, π_0)        (2)
```

where `TV` is total variation between the two policies' trajectory distributions. Via Pinsker, `2·TV ≤ √(2·KL(π ‖ π_0))`, which gives the KL form if a KL is available.

**Proof.** `E_π[r*] = E_π[r̂] − E_π[δ]`. Write `E_π[δ] = E_{π_0}[δ] + (E_π[δ] − E_{π_0}[δ])`. Since `δ ∈ [−1,1]`, `|E_π[δ] − E_{π_0}[δ]| ≤ 2·TV(π, π_0)`. Substitute for (1); subtract the identity at `π_0` for (2). ∎

### 2.3 Reading

- **Judged gain must exceed the divergence penalty.** True gain is guaranteed positive when `Δ̂ := E_π[r̂] − E_{π_0}[r̂] > 2·TV(π, π_0)`. This is a *sufficient* condition for trusting a judged gain.
- **Granularity.** The bound holds at whatever granularity `r*`, `r̂` are defined on. If the verifier scores responses, `TV` is over response distributions; if it scores trajectories (tool calls and arguments), `TV` must be over trajectories, and response-level TV underestimates it.

### 2.4 What it does not establish

- **No κ term.** The inequality says nothing about agreement rates; it cannot define a κ threshold. The earlier claim that it was "the mechanism behind a threshold on κ" is withdrawn.
- **No prediction of decline.** When `Δ̂ < 2·TV` the sufficient condition fails; that does not imply true gain is negative. "Predicted flip point" is withdrawn.
- **Edit size is not divergence.** A small textual edit to a prompt or playbook can produce a large behavioral change. The edit budget does *not* bound `TV`; only behavioral measurement does.
- **Estimator instability.** Per-case TV from `k = 8` samples per policy is upward-biased and noisy. Averaging over cases helps the mean; it does not make per-case values trustworthy.

### 2.5 What is computed (background only)

- `E_{π_0}[δ]` and `E_π[δ]` on the random-calibration slice, against executable ground truth on the benchmark (against oracle verdicts on the real desk).
- Behavioral `TV` from `k ≥ 16` samples per case per policy at the gate, response-level if the verifier scores responses, trajectory-level otherwise; reported with a bootstrap CI.
- The ratio `γ = (E_π[δ] − E_{π_0}[δ]) / (2·TV)` as a descriptive statistic of how adversarial the realized optimization was, with no threshold attached.
- These feed H3's *error-concentration × pressure* analysis: where the verifier's errors sit (per rule, per bucket, measured before optimization against executable truth) and how much of the realized exploitation gap falls in those regions after optimization. That is an empirical map, not a bound.

---

## 3. Selective stand-in — corrected

**What was wrong (v0.1).** The earlier text cited generic conformal risk control for a high-probability bound on error *conditional on selection*. Basic CRC controls an *expected* monotone loss, marginally. A conditional-on-selection guarantee with high probability needs a specific selective-risk procedure and its assumptions. Two sound options are given below, and the sample-size cost — which the earlier text ignored — is stated.

### 3.1 Objective

Let `C(x, ŷ) ∈ [0,1]` be the verifier's confidence. A selection rule `S_τ = {C ≥ τ}` auto-decides those cases. The **selective risk** is

```
R(τ) = E[ loss | C ≥ τ ],     loss = [verifier verdict ≠ ground truth]
```

Goal: choose `τ̂` from calibration data such that `R(τ̂) ≤ ε` holds with probability ≥ `1 − α` over the calibration draw, and report **coverage** `cov(τ̂) = P(C ≥ τ̂)`.

### 3.2 Sound procedures

**(a) Learn-then-Test (Angelopoulos, Bates, Candès, Jordan, Lei 2021).** Treat each candidate threshold on a grid as a null hypothesis `H_τ : R(τ) > ε`; test each with a valid p-value from the calibration sample (e.g. Hoeffding or exact binomial on the selected subset); select `τ̂` among thresholds rejected under a family-wise error control (fixed-sequence testing from the most conservative threshold down works because coverage is monotone in `τ`). Then `P(R(τ̂) ≤ ε) ≥ 1 − α`. Selective risk is not monotone in `τ` in general, which is why LTT's testing framework rather than monotone CRC is the right tool.

**(b) Trust-or-Escalate construction (Jung et al. 2024).** Selective evaluation with a provable human-agreement rate via calibrated confidence and cascaded judges; directly built for "when may the judge decide alone." Use as the reference implementation and compare.

Either way the guarantee is **marginal over cases drawn exchangeably with the calibration set**, not per bucket unless calibrated per bucket (which multiplies the sample cost by the number of buckets), and not conditional on any particular case.

### 3.3 Sample-size cost (exact, one fixed rule, zero observed errors)

One-sided 95% upper bound on selective error after `n` audited auto-decisions with no error: `1 − 0.05^{1/n}`.

| n | upper bound |
|---|---|
| 20 | 13.9% |
| 40 | 7.2% |
| 59 | 5.0% |
| 100 | 3.0% |
| 300 | 1.0% |

With observed errors, use Clopper–Pearson. Threshold selection over a grid, per-bucket certification, and repeated recertification all consume additional multiplicity budget on top of this. **Certifying ε = 5% per bucket with, say, six buckets is a several-hundred-label commitment**, and that is the number to put in front of the firm.

### 3.4 Recertification under optimization

The calibration guarantee is for the distribution the calibration sample was drawn from — the *current* policy's outputs. Optimizing the policy changes that distribution. Therefore:

- Calibration draws come from the current accepted policy's fresh outputs; nothing certified on AOP_t transfers to AOP_{t+1}.
- After each accepted change, `τ̂` is re-selected on new calibration draws; coverage is re-reported.
- Drift in the environment (procedure change) is a second source of exchangeability failure, detected by a change-point test on the calibration loss sequence.

The label tax for *holding* stand-in status is therefore recurring, and proportional to how often the policy changes.

### 3.5 Two stand-ins, two thresholds

| Use | Risk | Procedure |
|---|---|---|
| Production gate (auto-approve a response) | wrong response to a client | §3.2 with ε set by the business; §3.3 sample cost; §3.4 recertification |
| Optimization target (reward for the inner loop) | exploitation under pressure | no guarantee is claimed; only auto-decided cases contribute non-floor reward; H3 measures what happens |

### 3.6 What is computed

- `cov(τ̂)` at ε ∈ {0.05, 0.10}, marginal and (where the budget allows) per bucket, vs expert seconds spent on calibration.
- The multiplicity-adjusted label cost of each certification, reported alongside coverage.
- Change-point statistic on calibration loss.

---

## 4. Reliability in the reward, and structuredness (H5) — deferred

H5 is deferred (`OUTLINE.md` §4). The definitions are kept for a possible separate paper; nothing here is run in the pilot or in X1–X7.

### 4.1 Reliability-weighted reward

For a candidate procedure representation `P` (graph, skill, or script) and a case `c`, draw `k` responses with `m` seeds each. Define

- **Reproducibility** `rep(P, c) = 1 − H_norm(cluster frequencies of the k·m responses)`: 1 when every run lands in one response cluster.
- **Stability** `stab(P, c)`: fraction of `n_pert` paraphrased requests (same facts, different wording) whose outcome class matches the unperturbed one.
- **Cost** `cost(P, c)`: tokens per run, normalized by `AOP_0`.

```
r_rel(P, c) = r(P, c) − λ_rep · (1 − rep) − λ_stab · (1 − stab) − λ_cost · cost
```

with `r` the lexicographic reward of `../docs/rl.md` §3. Reliability is scored only on floor-pass responses (a reproducibly wrong procedure earns nothing).

### 4.2 Structuredness

How procedure-like an evolved representation is, independent of its syntax:

- `det(P)`: fraction of steps that are deterministic (tool call with bound arguments, no free-form generation).
- `seq(P)`: 1 − normalized entropy of the tool-call sequence over `k·m` runs.
- `struct(P) = (det + seq) / 2`.

**H5, stated:** under `r_rel` with `λ_rep, λ_stab > 0`, `struct(script_t)` increases with `t` and approaches `struct(graph)`; under `r` alone it does not. Secondary: label efficiency (κ-matched pass rate vs `N`) and Goodhart gap ordered graph < skill < script.

### 4.3 Cost note

Reliability scoring multiplies rollouts by `m · (1 + n_pert)`. Defaults `m = 3`, `n_pert = 2` → 9× rollouts per candidate on the reliability subset. Score reliability on the sealed set only at the gate, not in the inner loop.

---

## 5. Notation

| Symbol | Meaning |
|---|---|
| `σ ∈ {0,1}^M` | latent specification over rule hypotheses `h_1…h_M` |
| `ρ`, `ρ_R` | operator noise on verdicts / on confirmed rules |
| `D_H, D_R, D_V` | histories, confirmed rules, verdicts |
| `Y_c` | yield of channel `c`: bits per unit cost |
| `X(κ*)` | exchange rate, histories per verdict at agreement level `κ*` |
| `r*, r̂, δ` | true reward, verifier, their difference |
| `π_0, π` | reference and optimized policies |
| `TV`, `KL` | total variation, Kullback–Leibler |
| `Δ̂` | judged gain `E_π[r̂] − E_{π_0}[r̂]` |
| `γ` | Goodhart efficiency |
| `C`, `τ_ε`, `cov_ε` | verifier confidence, conformal threshold, coverage at risk ε |
| `rep, stab, struct` | reproducibility, stability, structuredness |
