# Coding-agent prompt

Paste the block below as the first message to the coding agent in the target environment, after it has access to this repository, the existing AOP execution engine, and the case data.

```
Read DESIGN.md in full before doing anything else.

Context you will find locally, not in the repo:
- The existing AOP execution engine (LangGraph 0.2.76). It is FIXED. Do not modify it. Send targets receive plain dicts, not Pydantic models; the retry parameter is `retry`.
- The case data: ~400 triples of (inbound email, historical operator reply, point-in-time SOR snapshot) for one procedure.
- An MCP server for navigating the SOR. The tool vocabulary is closed.

Produce, in this order, and stop after each to report:

(a) Gap analysis. Read the engine's graph builder and task plan code and the case data schema. List every place DESIGN.md conflicts with what actually exists (field names, outcome classes, snapshot shape, how AOP graphs are represented, how node prompts are stored). Ask before resolving any conflict. Do not write code yet.

(b) Scaffold. Create the layout in DESIGN.md §12 with typed interfaces, dataclasses/Pydantic models, and docstrings only. No loop logic in optimizer/ or gate/. The typed edit schema in optimizer/edits.py must cover every edit type in §6.3 and carry rationale, predicted-fixed case ids, predicted-unaffected case ids, and evidence pointers.

(c) Experiments E0–E2 as runnable scripts in experiments/:
    - e0_agreement.py: given two operators' independent verdicts (yes/no + one-sentence reason) on the same 30 historical replies, compute Cohen's kappa and print the disagreements with both reasons. This script consumes a CSV the humans fill in; it does not call a model.
    - e1_snapshot.py: for a sample of cases, extract entities and figures from the historical reply and reconcile them against the snapshot. Report the reconciliation rate. A low rate means the snapshot is not point-in-time and the environment is invalid.
    - e2_baseline.py: run the current AOP on the dev set (oldest ~250 cases, time-ordered). Score with the verifiable floor only (DESIGN.md §4.1). Report pass rate per (complexity, completeness) bucket as defined in §5. Write the complexity scorer as part of this step.

Report E0, E1 and E2 numbers. Do not build anything in optimizer/, gate/, reward/judge.py or escalation/ until those numbers have been reviewed.

Constraints throughout: engine is fixed; no model fine-tuning; every memory item carries provenance; the sealed set (newest ~150 cases) is never read by anything except gate/.
```
