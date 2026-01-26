# Abletools UX Style Guide (PyQt)

This document defines the UI component templates and styling rules for the PyQt app.
Formal name: **Design System** (also called a **UI Style Guide** or **Component Library**).

## Visual tokens
- **Primary accent:** `#19f5c8` (neon teal)
- **Primary text:** `#e6f1ff`
- **Muted text:** `#9bb3c9`
- **Panel background:** `#0e1824`
- **Input background:** `#0b1420`
- **Border / separators:** `#2f5b7a`
- **Grid overlay:** `resources/grid_overlay.svg` (low opacity)
- **Font:** `Avenir Next` for UI, `Menlo` for logs/monospace

## Layout + spacing
- **Root padding:** 12px horizontal, 8–12px vertical
- **Header height:** 64px
- **Card radius:** 8px
- **Field padding:** 6–8px
- **Tab padding:** 12px 20px, min-height 36px
- **Panel inset:** 12px content padding inside each tab view (top-level container).
- **Panel gaps:** 12px minimum between bordered panels; never less than 10px.
- **Grid gutters:** 12px between card rows/columns for dashboards and summary grids.
- **Border spacing:** default 12px between adjacent bordered elements (cards, panels, subpanels).
- **Row spacing:** default 12px between controls; use 8px for tight control rows.
- **Checkbox groups:** grid spacing 12px; vertical spacing uses `CHECKBOX_VERTICAL_SPACING` (50% of horizontal); labels sit left of checkboxes with right‑aligned label column.
- **Label → control gap:** fixed gap for all labels/controls (see `LABEL_WIDGET_GAP`).
- Use `_checkbox_flow` for all checkbox groups so options wrap instead of overlapping.
- **Control row height:** derived from font metrics (base text height + 10px).
- **Buttons:** derived from font metrics (base text height + 14px).
- **Group padding:** 12px internal padding for group boxes and card containers.
- **Section gap:** 16px between major vertical sections (stacked panels/rows).

## Components (templates)

### Header (Brand Bar)
- Left: SVG mark (44px) + title, vertically centered
- Divider: 2px bottom border
- Title: 24px, bold, neon accent

### Tabs
- Rounded top tabs with 2px border
- Selected tab shows neon underline (3px)
- Minimum width 92px for consistent click targets

### Hint Text
- Use `HintText` role for muted explanatory copy (11px, muted color).

### Buttons
- **Primary:** neon fill (`#19f5c8`), dark text
- **Secondary:** dark fill with bright border
- **Hover:** brighten border and background slightly
- **Spacing:** 12px between buttons in the same row.

### Inputs (LineEdit, ComboBox)
- Dark fill, 2px border
- Focus border becomes neon accent
- Default height derived from control row height (font metrics).
- **Scope dropdown width:** fit to longest item + ~26px padding (match dashboard dropdown).
- **Search width:** slightly wider than scope; default 240px in catalog.
- **Button height alignment:** button heights should visually align to adjacent inputs in the same row.

### Cards / Panels (GroupBox)
- 2px border, subtle background
- Title uses muted text for hierarchy

### Tables / Lists
- 2px header borders, 8px padding
- Gridline color matches separator color
- Row padding 6px
- Catalog columns right-align all numeric/status fields; left-align name.

### Logs / Monospace Areas
- `Menlo 11` for readability
- Optional background effect: scanners GIF + cmatrix overlay

### Splitter
- Handle matches border color
- Hover to neon accent

## Interaction patterns
- **Primary actions**: right-aligned on headers or left-aligned in panels
- **Secondary actions**: grouped adjacent to primary
- **Background activity**: status label + animated overlay (Scan)
- **Advanced options**: hide behind a single toggle; keep the default view compact.
- **Control rows**: align all labels and inputs to a shared center line.
- **Action rows**: buttons live in their own row type; do not mix buttons with inputs.

## UX architecture rules
- **Row/column grammar:** everything is built from rows and columns. No ad-hoc spacing or one-off layout patterns.
- **Row ownership:** every widget must belong to a row (or grid cell) container; no floating widgets.
- **Hierarchy spacing:** only parent containers own margins; children use row spacing only.
- **Single sizing system:** input height = control row height, button height = action row height.
- **Labeling:** every editable input has a visible label (not placeholder-only); labels sit above or to the left via `_field_label`.
- **One spacing source:** internal control spacing is from layout tokens; QSS is only for visual styling.
- **Label alignment:** checkbox labels are right‑aligned in a column to line up controls.
- **Checkbox layout:** all checkbox groups use `_checkbox_flow`; no manual `_hbox` checkbox rows.
- **Primary actions:** one primary per row; secondaries/tertiaries are visually subordinate.
- **No per-screen sizing:** no `setFixedHeight/Width` calls outside factory helpers and explicit allowlists (e.g., header logo).

## Catalog tab tenets
- **Single control row**: filters, scope, search, and actions share one vertical center line.
- **Filters**: label sits close to the checkbox grid; checkbox labels align to a column.
- **Control sizing**: scope/search fields stay compact to visually balance the row.
- **Details actions**: bottom action buttons centered as a group for quick access.
- **Card spacing**: keep stat cards and subpanels at least 12px apart; no border overlap.

## Design system rules of use
- New UI elements must follow these tokens and spacing rules by default.
- If a new pattern is required, update this guide alongside the code change.
- All layouts should use shared helpers (`_vbox`, `_hbox`, `_grid`) to enforce spacing rules.
- Each panel builds its UI in dedicated methods; avoid ad-hoc widget construction inline.
- Widgets should be created via factory helpers (`_button`, `_label`, `_value_label`, `_checkbox`, `_line_edit`, `_combo`, `_group`, `_group_box`, `_checkbox_flow`, `_controls_bar`, `_controls_grid`, `_button_grid`, `_action_row`, `_action_status_row`, `_hgap`).
- **No per-screen sizing:** avoid `setFixedHeight/Width` outside factory helpers.
- **Checkbox groups:** use `_checkbox_flow` (FlowLayout) so controls wrap and stay aligned.
- Maintain the UI catalog (`docs/UI_CATALOG.md`) with new elements, layout objects, and style roles.
- Use UI hierarchy levels: **Tab view (panel inset) → Groups → Rows/Grids → Controls**.

## UX principles checklist (visual audit)
- **Fitts' Law:** primary actions are large, nearby, and easy to hit.
- **Hick's Law:** reduce visible options per row; group with labels and toggles.
- **Gestalt proximity + similarity:** related controls sit close and share styling.
- **Visual hierarchy:** titles > section headings > labels > values.
- **Alignment:** shared baselines in rows; labels aligned to their controls.
- **Consistency:** identical controls share size, spacing, and placement.
- **Feedback:** status labels and activity indicators are visible near actions.

## UX audit categories
- **Navigation:** tabs, headers, global actions.
- **Inputs:** line edits, combos, checkboxes, toggles.
- **Actions:** primary/secondary buttons, action rows, status indicators.
- **Data views:** tables, lists, detail panes, summaries.
- **Containers:** group boxes, cards, panels, spacing contracts.
## Iconography
- **Logo:** `resources/abletools_mark.svg`
- **App icon:** `resources/abletools_icon.png`

## Implementation guidelines
- All visual tokens live in `apply_theme()` (QSS + palette).
- QSS is stored in `resources/theme.qss` and substituted with token values in `apply_theme()`.
- Component construction should assign object names for styling hooks:
  - `Primary` for primary buttons
  - `HeaderBar`, `HeaderLogo`, `appTitle`, `SectionTitle`
- Prefer consistent spacing and fixed minimum sizes for readability.
- Enforced via `scripts/ui_lint.sh`:
  - No stray `setFixedHeight/Width` outside helpers/allowlist.
  - No raw `QCheckBox(...)` usage; use `_checkbox` + `_checkbox_flow`.
  - Line edits must be paired with `_field_label` (label above/left) or part of a labeled `_controls_grid` tuple.
