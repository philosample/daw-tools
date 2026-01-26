# Project Codex Instructions

## Authority
These rules override global instructions.

## Prime directives
- Minimal surface area changes.
- Deterministic output.
- No silent fallbacks. Fail loudly with clear errors.
- No fallbacks or legacy shims; keep code clean and direct.

## Workflow
- If asked to “patch” or “fix”, do so directly:
  1) 1–3 lines: what changed + why

## Quality gate
- After any code change, run linting and auto-fixers for the modified files.
- Default commands:
  - `python -m ruff check --fix <changed_py_files>`
  - `python -m pylint <changed_py_files>`
- If a tool is unavailable or fails, stop and report the exact error; do not continue silently.

## Repo hygiene
- Preserve structure unless explicitly told to restructure.
- Do not add new dependencies unless requested.
- Do not rename files, paths, or public interfaces unless requested.

## Logging / reporting
- Prefer structured logs over print spam.
- If you add logging, make it meaningful and easy to grep.

## Packaging / installers
- Prefer single entrypoint scripts.
- Support non-interactive operation where possible.
- Prefer idempotent install behavior.

## Communication style
- No tutorials.
- No redundant restatement of the prompt.
- No motivational text.
- Do not dump full file contents unless explicitly requested.
