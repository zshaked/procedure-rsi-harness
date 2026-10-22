# AOP RSI Harness — Design

Self-improving harness that evolves Agentic Operating Procedures (AOPs) from historical operations data, under a fixed execution engine, with a cheap learned verifier calibrated against an expensive human oracle on a budget.

Status: design v0.2. Nothing is built. Experiments E0–E2 gate whether anything should be.

Deeper treatments live in `docs/`:
- `docs/rl.md` — how each RL piece works, where the analogy stops, a worked example, hyperparameters
- `docs/metrics.md` — metric definitions, gate statistics, the verifier-cost curve, v1 targets
- `docs/selection.md` — which cases get judged and which get escalated; the taxonomy agent's role

---

## 0. One-paragraph summary

An AOP is a DAG (YAML/JSON) executed by a fixed LangGraph engine. We have ~400 historical cases for one procedure (position confirmation), each a triple of inbound email, the human operator's reply, and a point-in-time snapshot of the system of record (SOR). Correctness is defined by operators, not by a spec — there is no written SOP. The harness runs k candidate executions per case against the frozen snapshot, scores them with a lexicographic reward (deterministic checks first, then a rubric-based LLM judge), computes group-relative advantage, and turns the contrast between high- and low-advantage candidates into typed edits to the AOP's playbook and graph. Edits are accepted only if they clear a sealed time-split gate with a noise floor. A small weekly budget of operator questions is spent where the judge is least certain, and every answer updates the judge's rubric. The engine, and all model weights, stay fixed.

The research question embedded in the system: under a fixed budget of expensive human verdicts, which regularizers stop a self-improving harness from exploiting its cheap judge?

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
- Ceiling: the judge cannot exceed inter-operator agreement. E0 measures this before anything is built.

### 4.3 Graded, not binary

Binary reward makes most groups zero-variance (all pass / all fail) and kills the advantage signal. Judge sub-scores provide the gradient of quality the optimizer needs.

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
| **E0** | Do operators agree with each other? | 30 cases, 2 operators, independent yes/no + reason on the historical reply; compute kappa | Ceiling for the judge. Below ~0.6, stop and fix the labeling protocol before building. |
| **E1** | Is the snapshot point-in-time? | For a sample, check that entities/figures in the historical reply reconcile with the snapshot | Whether the environment is valid at all. |
| **E2** | Where is the frontier? | Run AOP_0 on dev set; pass rate per bucket under the verifiable floor only | Which buckets to sample from in E3. |
| E3 | Does the playbook-only loop move the curve? | 10 epochs, k=8, playbook edits only, sealed-set gate | Go / no-go for structural edits. |
| E4 | Which regularizers close the Goodhart gap? | Ablate: ± verifiable floor, ± group normalization, ops budget ∈ {0, 25, 50, 100} | The research result. |

E0–E2 are cheap and run before any scaffold beyond the loader. E0 is the single number that decides whether the rest is real.

---

## 12. Proposed repo layout (scaffold only — do not build the loop until E0–E2 pass)

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
  experiments/  e0_agreement.py, e1_snapshot.py, e2_baseline.py
```

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Judge is exploited by the proposer | Verifiable floor; group normalization; kappa gate; critic; ops audit |
| Operators disagree with each other | E0 first; if low, refine labeling protocol (reasons, not verdicts) |
| Snapshot drift | E1 first |
| Single held-out set burns | Time split + rolling production held-out |
| Ops disengage | Budget of 5/week; one-sentence asks; approval instrumentation as a control feature |
| Structural edits overfit | Unlocked only after kappa gate; annealed budget; no-regression per bucket |
| Rubric / playbook bloat | Delta updates; counters; pruning |

---

## 14. Phasing

- **v1** — one procedure; judge with evolving rubric; verifiable floor; playbook/prompt/template edits; time-split gate; escalation policy; E0–E3.
- **v2** — structural edits after kappa gate; approval instrumentation; edit library consulted by curator; E4.
- **v3** — judge fine-tuned on accumulated ops verdicts + rationales (supervised); second procedure; meta-level improvement harness. Proposer stays frozen throughout.

---

## Appendix A — Seed prompt for a coding agent

```
Read DESIGN.md in full. Produce:
(a) A short gap analysis: anything in the design that conflicts with the existing engine or data as you find them. Ask before resolving conflicts.
(b) The scaffold in §12 with typed interfaces and docstrings only — no loop logic.
(c) experiments/e0_agreement.py, e1_snapshot.py, e2_baseline.py, runnable.
Stop after (c) and report E0–E2 results before building anything in optimizer/ or gate/.
Constraints: engine is fixed; LangGraph 0.2.76 (Send targets receive plain dicts; retry param is `retry`); no model fine-tuning; every memory item carries provenance.
```
