---
name: shell-safe
description: Generate safe, explicit shell commands optimized for macOS dev workflows.
metadata:
  short-description: Safe shell commands
---

## Rules
- Prefer readable commands over clever one-liners.
- Avoid sudo unless the user explicitly requests it.
- If destructive, include a dry-run or a backup step.
- Use zsh-compatible syntax unless asked otherwise.
