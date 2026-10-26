# Formal statements

Four pieces of math, each load-bearing for one figure. Nothing here is decorative: each section ends with what is actually computed. Where the formal object is intractable, the operational estimator is stated and that is what the paper reports.

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

Specification entropy `H(σ | D)` is the quantity every channel reduces. Under a mean-field posterior (rules treated as independent given data — an approximation, stated as such):

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

## 2. A Goodhart bound for optimization against a learned verifier

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

- **Judged gain must exceed the divergence penalty.** True gain is guaranteed positive when `Δ̂ := E_π[r̂] − E_{π_0}[r̂] > 2·TV(π, π_0)`. This is the trust-region condition the gate enforces, in closed form: the edit budget and no-regression tests bound TV; the noise floor bounds Δ̂ from below.
- **Flip point.** Self-improvement *can* be negative once `2·TV` exceeds `Δ̂`. The bound is worst-case — it assumes the policy moved exactly into the region where the verifier is most wrong — which is the adversarial case Goodhart describes. H3 tests whether the observed flip point tracks the predicted one.
- **Why κ enters.** `E_{π_0}[δ]` and the realized growth of `E_π[δ]` are both smaller when the verifier is better; with a calibrated verifier, `|δ|` is small on most of the mass and the bound is slack. With a poor verifier the bound binds early. That is the mechanism behind "a threshold on κ."

### 2.4 Operationalization

- `E_{π_0}[δ]` and `E_π[δ]`: measured on the uniform random audit slice (`../docs/selection.md` §8) with oracle verdicts on the respective policy's outputs. This is the Goodhart gap of `../docs/metrics.md` §2.
- `TV(π, π_0)`: per case, estimated from the `k` sampled responses under each policy — cluster responses (τ_dup), TV ≈ half the L1 distance between the two cluster-frequency vectors — then averaged over cases. Cheap, uses samples the loop already draws. (A classifier two-sample test is the alternative if clustering is unreliable.)
- **Goodhart efficiency:** `γ = (E_π[δ] − E_{π_0}[δ]) / (2·TV(π, π_0)) ∈ [−1, 1]`. How adversarial the optimizer actually was relative to the worst case. Reported per epoch; a rising γ is the exploit signature before the flip.
- **Predicted vs observed flip:** predicted at the first epoch where `Δ̂ < 2·TV`; observed at the first epoch where hidden-anchor gain is negative. Fig 4 plots both.

### 2.5 Limits

The bound is loose when the optimizer is benign (it moves mass toward high `r*` as well as high `δ`), so it is a *sufficient* condition for trusting a judged gain, not a prediction of the gain. Its value is naming the two quantities to track — audit gap and divergence — and giving the inner loop a stopping rule that does not depend on the verifier's opinion of itself.

---

## 3. Selective stand-in with conformal risk control

### 3.1 Statement

Let `C(x, ŷ) ∈ [0,1]` be the verifier's confidence in its verdict. Choose a threshold `τ` so that, on cases the verifier decides alone (`C ≥ τ`), its disagreement with the oracle is at most `ε` with probability `1 − α`. With a calibration set of `n` oracle-labeled cases drawn from the same distribution (the random audit slice), conformal risk control (Angelopoulos, Bates et al.) selects `τ` with the finite-sample guarantee

```
P( E[ loss | C ≥ τ ] ≤ ε ) ≥ 1 − α,     loss = [verdict ≠ oracle]
```

**Coverage at risk ε:** `cov_ε = P(C ≥ τ_ε)`, the fraction of cases the verifier handles alone. This is the stand-in metric; it is computed per bucket, because the verifier earns stand-in status on simple complete cases long before escalation cases.

### 3.2 Two stand-ins, two thresholds

| Use | Risk | Threshold from |
|---|---|---|
| Production gate (auto-approve a response) | wrong response to a client | §3.1 with ε set by the business (e.g. 0.05) |
| Optimization target (reward for the inner loop) | Goodhart under pressure | §2: judged gain must exceed `2·TV`; in addition, only auto-decided cases contribute non-floor reward |

### 3.3 Maintenance

Conformal guarantees assume exchangeability; procedure drift breaks it. The random audit slice persists indefinitely; `τ_ε` is re-estimated each batch; a bucket whose `cov_ε` drops loses stand-in status until re-earned. The label tax for holding stand-in status is the audit slice size, and it is the honest cost to report.

### 3.4 What is computed

- `cov_ε(bucket, N)` for ε ∈ {0.05, 0.10}, plotted against oracle labels `N`.
- Lower confidence bound on agreement per bucket (Wilson interval); decisions use the bound, never the point estimate.
- Drift detector: change-point test on the audit-slice loss sequence.

---

## 4. Reliability in the reward, and structuredness (H5)

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
