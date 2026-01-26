---
name: debug-logfirst
description: Debug by adding the smallest useful instrumentation first, then iterating.
metadata:
  short-description: Log-first debugging
---

## Rules
- Start with the most likely root cause(s).
- Provide a minimal inspection or instrumentation step that confirms/disproves.
- Avoid speculative refactors.
- If adding logs, make them grep-friendly and scoped.

## Output
- Hypotheses (max 3)
- Quick confirmation step(s)
- Patch (full file(s)) if needed
