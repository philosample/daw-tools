# Abletools Codex Instructions

These instructions apply to all future changes in this repo.

## UX system rules (must follow)
- Use the UX design system defined in `docs/UX_STYLE_GUIDE.md`.
- Use the UI inventory in `docs/UI_CATALOG.md` when adding or modifying widgets.
- Build layouts only with row/column helpers (`_vbox`, `_hbox`, `_grid`, `FlowLayout`).
- Do not add per-screen sizing overrides; only use factory helpers for sizes.
- Use `_checkbox_flow` for multi-checkbox groups; avoid fixed row layouts that can overlap.
- Keep margins at container boundaries only (group box margins + panel margins); no extra nested padding unless documented.

## Documentation
- When adding a new UI pattern or helper, update both `docs/UX_STYLE_GUIDE.md` and `docs/UI_CATALOG.md`.
- Record UX audit tasks in `ux/tasklists/`.
