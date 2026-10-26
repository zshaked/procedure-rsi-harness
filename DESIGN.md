# AOP RSI Harness — Design

Self-improving harness that evolves Agentic Operating Procedures (AOPs) from historical operations data, under a fixed execution engine, with a cheap learned verifier calibrated against an expensive human oracle on a budget.

Status: design v0.3. Nothing is built. Experiments E0′–E2 gate whether anything should be.

Deeper treatments live in `docs/`:
- `docs/rl.md` — how each RL piece works, where the analogy stops, a worked example, hyperparameters
- `docs/metrics.md` — metric definitions, gate statistics, the verifier-cost curve, v1 targets
- `docs/selection.md` — which cases get judged and which get escalated; the taxonomy agent's role

The paper and its testbed live alongside:
- `paper/OUTLINE.md` — question, abstract, hypotheses H1–H5, baselines, experiments, kill test, timeline
- `paper/MATH.md` — latent specification inference and the exchange rate; the Goodhart bound; conformal stand-in; reliability reward
- `benchmark/README.md` — the synthetic confirmations domain and the τ-bench inversion; knobs, splits, oracle simulator, build order

### v0.3 changes (verifier-first)

The project's primary artifact is the **verifier**, not the AOP. Once the verifier generalizes, AOP improvement is cheap and automatic; until it does, every inner-loop iteration optimizes noise. Consequences, each detailed in the sections marked:

1. **Ground truth v0 is an operator-verified regression set** (~100 stratified cases, ≥ 40 held out for calibration and never used for rubric curation), not two operators agreeing. E0 is replaced by E0′, a noise-floor measurement (§11).
2. **Cold start is not zero.** The verifier opens with three provenance tiers — priors (model knowledge), context (schema, tools, sibling-procedure rubric), rules distilled from the historical replies — and the first operator questions *verify* inferred rules rather than elicit new ones. κ₀, the zero-label verifier, is a reported baseline (§4.2).
3. **The judge is a checklist, not a critic**: independently checkable conditions with provenance; the holistic score is a shrinking residual. De-anchored: it commits to its own answer before scoring the candidate (§4.2).
4. **Stand-in is selective and earned per bucket**: conformal risk control sets a confidence threshold with a bounded error rate; coverage-at-risk is the stand-in metric; the random audit slice persists as the drift detector (§4.4).
5. **Two thresholds**: production gate (bounded error) vs optimization target (judged gain must exceed the divergence penalty, `paper/MATH.md` §2) (§4.4).
6. **Representation is a knob in the paper, fixed at the firm**: AOP graphs in production for auditability; graph / skill / script compared on the benchmark with reliability in the reward (`paper/MATH.md` §4).
7. **Two loops, one rule**: the verifier learns only from operators and state; the policy learns only from the verifier. The recursion is in the data routing (policy disagreement → operator question → verifier update), never in the supervision.

---

## 0. One-paragraph summary

An AOP is a DAG (YAML/JSON) executed by a fixed LangGraph engine. We have ~400 historical cases for one procedure (position confirmation), each a triple of inbound email, the human operator's reply, and a point-in-time snapshot of the system of record (SOR). Correctness is defined by operators, not by a spec — there is no written SOP. The harness runs k candidate executions per case against the frozen snapshot, scores them with a lexicographic reward (deterministic checks first, then a rubric-based LLM judge), computes group-relative advantage, and turns the contrast between high- and low-advantage candidates into typed edits to the AOP's playbook and graph. Edits are accepted only if they clear a sealed time-split gate with a noise floor. A small weekly budget of operator questions is spent where the judge is least certain, and every answer updates the judge's rubric. The engine, and all model weights, stay fixed.

The research question embedded in the system (v0.3): when can a learned verifier stand in for the human in a self-improvement loop for a latent procedure, and how many human labels does it take to get there? The bottleneck is specification, not evaluator intelligence. See `paper/OUTLINE.md`.

---

## 1. Setting

| Element | State |
|---|---|
| Execution engine | Fixed. LangGraph 0.2.76. Send API for fan-out, RetryPolicy, checkpointer. |
| Editable surface | AOP graph structure, node prompts, per-AOP playbook (business rules), reply template. |
| Cases | ~400 triples: `(email, historical_reply, sor_snapshot)`. Snapshot must be point-in-time at the moment of the historical reply (verified by E1). |
| Tools | MCP server for SOR navigation. Tool vocabulary is closed and known. |
| Oracle | Operators ("ops"). Expensive, slow, politically constrained. Define correctness. |
| Spec | None. Procedure is latent; must be induced from the triples. |

### 1.1 Why this setting is different from the literature

| Work | Verifier assumption | Edit target |
|---|---|---|
| Procedural Graphs (Google, arXiv 2609.09153) | Benchmark verifier; edit kept only if no held-out regression | Procedure graph |
| Harness² (Google, arXiv 2610.14224) | No verifier (open world); contrastive Propose–Probe–Compose | Execution harness + improvement harness |
| RRSI (Google, google-research/rrsi) | Benchmark suite; regularized proposal/selection | Agent harness |
| ACE | Task reward | Context playbook (delta updates) |
| **This** | **Partial** verifiable reward + cheap noisy judge + expensive human oracle with a budget | Playbook + procedure graph |

We sit in the gap between "no verifier" and "benchmark verifier." The main figure of the system is accuracy vs verifier cost.

---

## 2. What we take from each reference

- **ACE** — Generator / Reflector / Curator roles. Memory is itemized bullets with ids, provenance and helpful/harmful counters, updated by deltas, never rewritten wholesale (avoids context collapse and brevity bias).
- **Procedural Graphs** — The AOP is the editable graph. A refiner contrasts failed vs successful trajectories and rewrites structure. An edit is kept only if it does not hurt held-out cases.
- **Harness²** — Propose–Probe–Compose: propose several edits, probe them on the same case, compose the ones that help. A persistent library of past edits (their ablation's largest single component).
- **RRSI** — The regularizers: annealed edit budget per candidate, proposer conditioned on full edit history, critic screens candidates before evaluation, noise-adjusted acceptance floor, cost rule (added tokens must buy measured gain), pruning of components that stop helping.
- **GRPO / DAPO** — Group-relative advantage normalization (cancels per-case judge bias); dynamic sampling (drop groups with zero reward variance).

---

## 3. Architecture

```
                 ┌─────────────────────────────────────────────────────────┐
                 │                     CASE STORE                          │
                 │  (email, historical_reply, sor_snapshot) × ~400          │
                 │  time split: dev (oldest ~250) | sealed (newest ~150)    │
                 └──────────────┬──────────────────────────────────────────┘
                                │ stratified sample (frontier buckets)
                                ▼
┌──────────────┐      ┌───────────────────┐      ┌──────────────────────────┐
│ COMPLEXITY   │─────▶│ CANDIDATE SAMPLER │─────▶│ FIXED ENGINE (LangGraph) │
│ SCORER       │      │ k=8 per case      │      │ runs AOP_t on snapshot   │
└──────────────┘      └───────────────────┘      └───────────┬──────────────┘
                                                             │ k trajectories
                                                             ▼
                                   ┌─────────────────────────────────────────┐
                                   │ REWARD                                   │
                                   │  1. verifiable floor (deterministic)     │
                                   │  2. critic (finds ops-rejection reason)  │
                                   │  3. judge (rubric → score 0–1 + reason)  │
                                   └───────────┬─────────────────────────────┘
                                               │ group-relative advantage
                                               ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌─────────┐
│ ESCALATION   │◀─────│ REFLECTOR    │─────▶│ CURATOR      │─────▶│ GATE    │
│ POLICY       │      │ hi vs lo     │      │ typed edits  │      │ sealed  │
│ (ops budget) │      │ contrast     │      │ ≤2/candidate │      │ + floor │
└──────┬───────┘      └──────────────┘      └──────────────┘      └────┬────┘
       │ verdict + rationale                                           │ accept
       ▼                                                               ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ MEMORY                                                                     │
│  rubric (judge) │ rules w/ provenance │ procedure graph │ open questions   │
│  edit log (edit, prediction, evidence, outcome) │ edit library             │
└───────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Components

| Component | Responsibility | Notes |
|---|---|---|
| Case store | Load triples; enforce time split; expose bucket labels | Sealed set is read only by the gate |
| Complexity scorer | Assign each case `(complexity, completeness)` bucket | §5 |
| Candidate sampler | Produce k candidates per case | Temperature sampling of LLM nodes, or k candidate edits applied to AOP_t |
| Fixed engine | Execute AOP against frozen snapshot | Send API fan-out; no engine changes ever |
| Verifiable checker | Deterministic checks → pass/fail | §4.1 |
| Critic | Asymmetric adversary: "why would ops reject this?" with SOR access | Output feeds the judge; predicted reasons are checkable against ops rationales |
| Judge | Rubric-based score 0–1 + reason; rubric is an ACE-style playbook | §4.2 |
| Reflector | Within each group, contrast high- vs low-advantage trajectories; emit candidate lessons | ACE Reflector / Procedural Graphs refiner |
| Curator | Convert lessons into typed edits; enforce edit budget; consult edit library | §6.3 |
| Gate | Paired comparison on sealed set with noise floor + cost rule | §7 |
| Escalation policy | Choose which cases to send to ops within budget | §8.1 |
| Memory | Persistent, versioned, with provenance | §9 |

---

## 4. Reward

Lexicographic. A candidate that fails the verifiable floor scores 0 regardless of judge output. This is the hard constraint that stops the loop from learning to please the judge while being factually wrong.

### 4.1 Verifiable floor (deterministic)

Computed against `sor_snapshot` and `historical_reply`:

- Entity match — every account / position / instrument identifier in the candidate reply resolves in the snapshot and matches the entities referenced in the historical reply.
- Figure match — every quantity / amount / date in the candidate reply matches the snapshot within tolerance.
- Outcome class match — candidate outcome ∈ {confirmed, not confirmed, escalate, request info} equals the class of the historical reply.
- Schema / safety — reply is well-formed; no hallucinated identifiers.

Any failure → reward 0.

### 4.2 Judge (learned, in context)

- Prompted model + evolving rubric. No fine-tuning in v1.
- Input: email, snapshot, historical reply, candidate reply, critic output.
- Output: structured — sub-scores per rubric item, aggregate 0–1, one-sentence reason, cited rubric item ids.
- Objective: predict P(ops approves) and the reason. The rubric is curated from ops verdicts + rationales (ACE deltas: add / strengthen / weaken / retire a rubric line, each with provenance).
- Comparative, not absolute: the judge always sees the historical reply as reference. Comparative judgments are more reliable than absolute scoring.
- Calibration metric: Cohen's kappa vs an ops audit sample. **Structural edits are unlocked only when kappa ≥ 0.7.**
- Ceiling: the judge cannot exceed the operators' own consistency. E0′ measures the noise floor before anything is built (§11).
- **Checklist, not critic (v0.3).** The rubric is a list of independently checkable conditions, each with provenance (prior / context / inferred-from-history / ops-stated). The holistic score is a residual for what the checklist does not cover, and it shrinks as the checklist grows. A holistic judge scores plausibility; a checklist scores conditions, generalizes from fewer labels, and is auditable line by line.
- **De-anchored.** On cases without a reference reply, the judge first commits to its own reply, then scores the candidate. Reference-free judging is the regime where judges get hacked; committing first cut false positives from 0.72 to 0.01 in the self-play judge-hacking study.
- **Cold start (v0.3).** Three provenance tiers seed the rubric before any ops label: *prior* (model domain knowledge — useful, sometimes wrong for this desk), *context* (SOR schema, tool docs, the sibling procedure's rubric and floor checks), *inferred* (rules distilled from the historical replies: "every confirmed reply states the as-of date"). Inferred rules stay inferred until an ops verdict or a state check upgrades them. The first ops questions are rule *verification* ("here are 20 rules we inferred from your replies — which are wrong, which are missing?"), which costs seconds per rule where elicitation costs minutes. κ₀ — agreement with ops before any label — is reported as the leftmost point of every curve.
- **Train/held-out split of ops labels.** Of the operator-verified regression set, ≥ 40% is held out, never used for rubric curation, and is the only data on which κ, Brier and coverage-at-risk are computed. Curating on all of it memorizes the test. With n = 30, κ = 0.7 has a confidence interval of roughly ±0.25; aim for ~100 labeled, ~40 held out.

### 4.3 Graded, not binary

Binary reward makes most groups zero-variance (all pass / all fail) and kills the advantage signal. Judge sub-scores provide the gradient of quality the optimizer needs.

### 4.4 Selective stand-in (v0.3)

The verifier does not replace ops all at once; it replaces them on cases where it is confident and escalates the rest.

- **Conformal risk control** (`paper/MATH.md` §3): from the held-out audit slice, choose a confidence threshold τ_ε such that the verifier's disagreement with ops on auto-decided cases is ≤ ε with probability 1 − α. **Coverage at risk**, cov_ε = P(confidence ≥ τ_ε), is the stand-in metric, computed per bucket. Simple complete cases are covered long before escalation cases.
- **Two thresholds.** As a *production gate* (auto-approve a reply), the risk is a wrong reply to a client: ε is a business number (e.g. 0.05) and the conformal guarantee applies. As the *optimization target* for the inner loop, the risk is Goodhart under pressure: judged gain must exceed the divergence penalty (`paper/MATH.md` §2), and only auto-decided cases contribute non-floor reward.
- **Maintained, not reached.** Conformal guarantees assume exchangeability; drift breaks it. The uniform random audit slice persists indefinitely as the drift detector; τ_ε is re-estimated each batch; a bucket whose coverage drops loses stand-in status until re-earned. The label tax for holding stand-in status is the audit slice, and that is the cost to report to the firm.
- Decisions use the lower confidence bound on agreement, never the point estimate.

---

## 5. Case stratification

Two axes, computed per case:

- **Complexity** (traversal): number of distinct SOR entities to resolve; minimum API hops in the closed tool vocabulary; whether disambiguation is required. Derivable from the historical reply (what the human looked up) plus the snapshot.
- **Completeness** (ambiguity): fraction of required parameters present and unambiguous in the email. Low completeness cases are where "escalate / request info" is the right answer.

Uses:

1. Curriculum — start where pass rate is highest.
2. Sampling — each epoch draws from buckets whose current pass rate is near 50% (DAPO dynamic sampling); groups with zero reward variance are dropped.
3. Reporting — per-bucket success curves are more informative than aggregate F1, and show where the frontier is.
4. Grouping key — advantages are compared within buckets, so they are comparable.

Intent routing (which AOP handles an email) is unchanged; stratification is a training/evaluation axis only.

---

## 6. Optimizer — GRPO without gradients

Full treatment, including a worked example: `docs/rl.md`.

### 6.1 Mapping

| RL piece | Here |
|---|---|
| Environment | `(email, sor_snapshot)` — replayable, deterministic |
| Policy | AOP_t = graph + prompts + playbook (text and structure, not weights) |
| Rollout | One execution of AOP_t on a case → trajectory + reply |
| Reward | §4 |
| Advantage | Group-relative: `A_i = (r_i − mean_group) / std_group` |
| Policy update | Reflector contrast → Curator typed edits (replaces policy gradient) |
| KL penalty | Edit budget + sealed-set gate + cost rule |
| Reward model | Judge rubric, curated from ops verdicts (replaces RM fine-tune) |

### 6.2 Loop (one step)

```
sample cases C from frontier buckets (dev set only)
for each case c in C:
    run k=8 candidates of AOP_t on c.snapshot            # Send API fan-out
    r_i = reward(candidate_i)                             # §4
    if var(r) == 0: skip c                                # dynamic sampling
    A_i = (r_i - mean(r)) / std(r)
    lessons += reflector(top-m by A, bottom-m by A, c)    # within-group contrast
edits = curator(lessons, edit_library, budget_t)          # typed, ≤ b_t per candidate
for each candidate AOP' in compose(AOP_t, edits):
    if gate(AOP', AOP_t): accept, log(edit, prediction, evidence)
    else: log rejection; feed back to curator
```

### 6.3 Typed edits

| Type | Example | Unlocked |
|---|---|---|
| `playbook.add / modify / retire` | "Verify settlement date before confirming" | v1 |
| `prompt.edit` | Change a node's instruction | v1 |
| `template.edit` | Reply template wording | v1 |
| `graph.rebind_arg` | Change argument binding on an existing node | after kappa ≥ 0.7 |
| `graph.add / remove / reorder` | Change SOR traversal | after kappa ≥ 0.7 |

Each edit carries: rationale, the cases it predicts it will fix, the cases it predicts it will not affect, evidence pointers (case ids, ops answer ids).

Annealed budget `b_t`: start at 2 edits per candidate, decay toward 1. Proposer is conditioned on the full edit history so a falsified hypothesis is not redrawn (RRSI).

Why playbook first: structural edits that change SOR traversal are exactly what overfit when learned from terminal outcome reward alone. They are only safe once the verifier is trusted.

---

## 7. Gate and regularization

- **Time split** — oldest ~250 cases are the dev set the loop sees; newest ~150 are sealed and touched only by the gate. New production cases become a rolling held-out the loop never trains on. Time-based splitting is honest about drift and limits adaptive overfitting of a single held-out set.
- **Paired comparison** — AOP' vs AOP_t on identical sealed cases. Use discordant-pair statistics (McNemar on pass/fail; bootstrap CI on judge score deltas), not raw accuracy deltas. With ~150 cases, an unpaired 3-point gain is noise.
- **Noise floor** — accept only when the paired improvement clears the estimated evaluation variance.
- **No-regression** — no bucket may fall by more than the noise floor.
- **Cost rule** — added inference tokens per case must be paid for by measured gain.
- **Pruning** — playbook lines whose helpful/harmful counters go negative over N epochs are retired.
- **Decision observability** — every accepted edit is stored with its prediction; predictions are checked on later epochs; edits with bad prediction records lower the curator's trust in similar edits.

---

## 8. Human loops

### 8.1 Escalation policy (ops)

Full treatment, including which cases get judged in the first place: `docs/selection.md`.

- Weekly budget `B` of questions (start: 5).
- Priority score per case = judge uncertainty (sub-score disagreement, low confidence) + candidate disagreement (high within-group variance) + bucket frontier weight.
- Question format: one concrete case, the candidate reply, yes/no, and **one sentence of reason**. Rationales are the high-value signal; a bare verdict is nearly worthless for rubric curation.
- Every answer → rubric delta with provenance; verdict joins the audit sample for kappa.

### 8.2 Approval instrumentation (future state)

When AOP-drafted replies enter the production path, the approve / edit / reject step is the only ops signal that scales, and it costs operators nothing. Frame it to stakeholders as a human-in-the-loop control feature, not as data labeling.

### 8.3 Product-owner loop (deferred)

Unstructured PO feedback is low bandwidth relative to ops rationales. Deferred to v2.

---

## 9. Memory layout

All items are itemized, versioned, and carry provenance. Updates are deltas.

| Store | Contents | Provenance |
|---|---|---|
| `rubric/` | Judge rubric lines, each with helpful/harmful counters | ops verdict ids |
| `rules/` | Business rules the AOP's LLM nodes consume | case ids, ops answer ids |
| `procedure/` | The AOP graph (versioned) | edit ids |
| `questions/` | Open-questions queue for escalation | case ids |
| `edits/` | Edit log: edit, prediction, evidence, gate outcome, later verification | — |
| `library/` | Past edits + outcomes, consulted by the curator | edit ids |

---

## 10. Metrics

Definitions, slices, gate statistics and targets: `docs/metrics.md`. Headline set:

- **Per-bucket success curve** (main figure): pass rate by `(complexity, completeness)` bucket over epochs, on the sealed set.
- **Goodhart gap**: judge score − ops audit score, over epochs. The paper's dependent variable.
- **Judge kappa** vs ops audit sample.
- **Ops questions consumed** per unit of sealed-set improvement.
- **Cost**: tokens per case vs AOP_0.
- **Edit prediction accuracy**: fraction of accepted edits whose predictions held.

---

## 11. Experiments

| Id | Question | Method | Decides |
|---|---|---|---|
| **E0′** | What is the human noise floor? | Cheapest first: (a) intra-cluster consistency of the historical replies — cluster by parameter set, check outcome-class and reported-fact agreement within cluster, no new labels; (b) test–retest: the operator who verified the regression set re-labels 20 cases weeks later; (c) only if the verifier must stand in for the *team* rather than one operator: two operators on 30. | Sets ε. If the operators' own inconsistency is 15%, a 5% risk bound is unreachable and labels are spent chasing noise. The stand-in threshold is defined relative to this number. |
| **E1** | Is the snapshot point-in-time? | For a sample, check that entities/figures in the historical reply reconcile with the snapshot | Whether the environment is valid at all. |
| **E2** | Where is the frontier? | Run AOP_0 on dev set; pass rate per bucket under the verifiable floor only | Which buckets to sample from in E3. |
| E3 | Does the playbook-only loop move the curve? | 10 epochs, k=8, playbook edits only, sealed-set gate | Go / no-go for structural edits. |
| E4 | Which regularizers close the Goodhart gap? | Ablate: ± verifiable floor, ± group normalization, ops budget ∈ {0, 25, 50, 100} | The research result. |

E0′–E2 are cheap and run before any scaffold beyond the loader. E0′(a) needs no one's time but yours. The regression set itself (~100 operator-verified cases, stratified by bucket and outcome class, oversampling escalations and request-info) is requested in parallel; it is ground truth v0 and the source of the held-out calibration slice.

The benchmark's kill test (`paper/OUTLINE.md` §9) runs on public data in the same window and is independent of the firm.

---

## 12. Proposed repo layout (scaffold only — do not build the loop until E0′–E2 pass)

```
aop_rsi/
  cases/        loader, time split, bucket labels
  complexity/   scorer (entities, hops, disambiguation, completeness)
  reward/       verifiable.py, critic.py, judge.py, rubric/
  sampler/      frontier sampling, dynamic-sampling filter
  engine/       thin adapter over the fixed LangGraph engine (no logic)
  optimizer/    reflector.py, curator.py, edits.py (typed edit schema)
  gate/         paired tests, noise floor, cost rule
  memory/       stores in §9, all versioned with provenance
  selection/    pre-judge signals, scoring, slice allocation, taxonomy agent (docs/selection.md)
  escalation/   uncertainty ranking, question formatting, budget
  metrics/      one row per (epoch, version, split, slice, bucket, metric, value, n) (docs/metrics.md)
  experiments/  e0_noise_floor.py, e1_snapshot.py, e2_baseline.py
```

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Judge is exploited by the proposer | Verifiable floor; group normalization; kappa gate; critic; ops audit |
| Operators are inconsistent | E0′ first; set ε above the measured noise; if the floor is high, refine the labeling protocol (concrete cases with contrast, reasons, not bare verdicts) |
| Regression replies are "ideal" rather than what operators actually send | Ask for replies as they would send them in production, time-boxed; cross-check against any real outbound that exists |
| Judge exploited on cases without a reference reply | De-anchoring; checklist structure; conformal stand-in only where calibrated |
| Snapshot drift | E1 first |
| Single held-out set burns | Time split + rolling production held-out |
| Ops disengage | Budget of 5/week; one-sentence asks; approval instrumentation as a control feature |
| Structural edits overfit | Unlocked only after kappa gate; annealed budget; no-regression per bucket |
| Rubric / playbook bloat | Delta updates; counters; pruning |

---

## 14. Phasing

- **v1** — one procedure; operator-verified regression set; checklist verifier seeded from three tiers, κ₀ measured; verifiable floor; playbook/prompt/template edits; time-split gate; escalation policy; conformal stand-in per bucket; E0′–E3. Process story per mailbox: label ~100 → build verifier → measure κ and coverage on the held-out → AOP optimization switches on only when the inner-loop condition holds → questionnaire loop grows the labeled set and re-measures each batch.
- **v2** — structural edits after kappa gate; approval instrumentation; edit library consulted by curator; E4.
- **v3** — judge fine-tuned on accumulated ops verdicts + rationales (supervised); second procedure; meta-level improvement harness. Proposer stays frozen throughout.

---

## Appendix A — Seed prompt for a coding agent

```
Read DESIGN.md in full. Produce:
(a) A short gap analysis: anything in the design that conflicts with the existing engine or data as you find them. Ask before resolving conflicts.
(b) The scaffold in §12 with typed interfaces and docstrings only — no loop logic.
(c) experiments/e0_noise_floor.py, e1_snapshot.py, e2_baseline.py, runnable.
Stop after (c) and report E0′–E2 results before building anything in optimizer/ or gate/.
Constraints: engine is fixed; LangGraph 0.2.76 (Send targets receive plain dicts; retry param is `retry`); no model fine-tuning; every memory item carries provenance.
```
