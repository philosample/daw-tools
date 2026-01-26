---
name: patch-minimal
description: Apply the smallest correct patch with minimal surface area.
metadata:
  short-description: Minimal patch, no refactors
---

## Rules
- Modify only what is required to satisfy the request.
- Do not refactor, reformat, or rename unless necessary for correctness.
- Preserve existing style and structure.
- Prefer explicit behavior; no silent defaults.

## Output
- Start with 1–3 lines: what changed + why
- Then output full updated file(s) with paths.
