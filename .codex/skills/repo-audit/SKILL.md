---
name: repo-audit
description: Quick repo audit focused on correctness, safety, and maintainability (no style bikeshedding).
metadata:
  short-description: Practical audit
---

## Rules
- Focus on correctness bugs, footguns, and deploy/installer hazards.
- No formatting critiques unless they cause real issues.
- Provide a prioritized list with concrete fixes.

## Output
- Findings grouped by severity: Critical / Important / Nice-to-have
- For each: file + line hint + fix suggestion
