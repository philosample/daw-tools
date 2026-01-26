## Enforced UX rules (Abletools Qt)
- Single sizing system: control row height and button height come from shared tokens; no per-screen overrides.
- No per-screen sizing: `setFixedHeight/Width` only in factory helpers or explicit allowlist (header logo).
- Labels required: every editable input has a visible `_field_label` or lives in a labeled `_controls_grid` tuple; no placeholder-only fields.
- Checkbox layout: all checkbox groups use `_checkbox_flow`; no manual checkbox rows.
- Primary action hierarchy: one primary per row; secondaries/tertiaries subdued.
- Borders: one outline per logical group; use standard padding tokens; avoid double boxing.
- Spacing scale only: use spacing tokens (row/panel/section); no ad-hoc pixel gaps.
- Factory-only construction: build controls via helpers; avoid raw widget construction for common controls.
- Enforcement: `scripts/ui_lint.sh` must pass; update `docs/UX_STYLE_GUIDE.md` and `docs/UI_CATALOG.md` when introducing patterns.
