---
name: patch-fullfile
description: Produce full-file replacements for all changed files.
metadata:
  short-description: Full files only
---

## Rules
- Never output partial snippets.
- Never omit unchanged sections.
- If multiple files change, output each full file.

## Output
- Bullet list of changed files
- Full content for each file in a separate code block
