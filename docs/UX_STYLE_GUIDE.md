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

### Buttons
- **Primary:** neon fill (`#19f5c8`), dark text
- **Secondary:** dark fill with bright border
- **Hover:** brighten border and background slightly
- **Spacing:** 12px between buttons in the same row.

### Inputs (LineEdit, ComboBox)
- Dark fill, 2px border
- Focus border becomes neon accent
- Default height 22px for all inputs (line edits + combos)
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
- **Control rows**: align all labels, inputs, and buttons to a shared center line.

## Catalog tab tenets
- **Single control row**: filters, scope, search, and actions share one vertical center line.
- **Filters**: keep label and checkbox spacing tight; label sits close to first checkbox.
- **Control sizing**: scope/search fields stay compact to visually balance the row.
- **Details actions**: bottom action buttons centered as a group for quick access.
- **Card spacing**: keep stat cards and subpanels at least 12px apart; no border overlap.

## Design system rules of use
- New UI elements must follow these tokens and spacing rules by default.
- If a new pattern is required, update this guide alongside the code change.
- All layouts should use shared helpers (`_vbox`, `_hbox`, `_grid`) to enforce spacing rules.
- Each panel builds its UI in dedicated methods; avoid ad-hoc widget construction inline.
- Widgets should be created via factory helpers (`_button`, `_label`, `_checkbox`, `_line_edit`, `_combo`, `_group`, `_checkbox_row`, `_action_row`).
- Maintain the UI catalog (`docs/UI_CATALOG.md`) with new elements, layout objects, and style roles.
- Use UI hierarchy levels: **Tab view (panel inset) → Groups → Rows/Grids → Controls**.

## Iconography
- **Logo:** `resources/abletools_mark.svg`
- **App icon:** `resources/abletools_icon.png`

## Implementation guidelines
- All visual tokens live in `apply_theme()` (QSS + palette).
- Component construction should assign object names for styling hooks:
  - `Primary` for primary buttons
  - `HeaderBar`, `HeaderLogo`, `appTitle`, `SectionTitle`
- Prefer consistent spacing and fixed minimum sizes for readability.
