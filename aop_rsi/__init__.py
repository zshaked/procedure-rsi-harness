"""aop_rsi — firm-agnostic scaffold for the AOP harness (DESIGN.md §12).

Scaffold only. Contains the case schema and loaders, the four-role split, the
bucket scorer, the verifiable floor, the field extractor, the problem-indexed
edit library, and experiments E0′–E2. It does not contain the optimizer, the
judge, or the gate: per DESIGN.md §11, those are not built until E0′–E2 pass.

Everything here runs against the synthetic confirmations environment
(`pilot/env2.py`) through `aop_rsi.cases.adapters.env2`, so the code is
exercised before it meets firm data. The firm adapter
(`aop_rsi.cases.adapters.firm`) documents the export schema it expects.
"""
