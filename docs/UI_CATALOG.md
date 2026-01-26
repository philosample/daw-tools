# UI Catalog (PyQt)

This catalog enumerates every UI object (widgets + layouts + style roles) used in the Qt UI.
It is the authoritative inventory used to enforce spacing/sizing rules and to drive future UI changes.
Enforcement is automated by `scripts/ui_lint.sh` (see UX style guide).

## Global theme
- `resources/theme.qss` with token substitution in `apply_theme()` (source of UI colors + base styling).

## Global layout objects
- `QVBoxLayout` / `QHBoxLayout`
  - Default spacing: `SPACE_PANEL` (12) for vertical stacks, `SPACE_ROW` (12) for rows.
  - Default margins: 0, with `_panel_margins()` applied at top-level.
- `QGridLayout`
  - Default spacing: `SPACE_PANEL` (12) for both axes.
  - Used for stat cards, summary grids, and checkbox clusters when needed.
- `FlowLayout`
  - Used via `_checkbox_flow` to wrap checkbox groups without overlap.
- `QSplitter`
  - Used in Preferences for left/right split; handle width styled.
- `QScrollArea`
  - Used in detail panes to avoid resizing panels.

## Widget factories (rule-based)
- `_label(text, name=None)` → `QLabel`
- `_field_label(text, buddy=None, name="FieldLabel")` → `QLabel` with buddy and vertical alignment.
- `_section_title(text)` → `QLabel#SectionTitle`
- `_value_label(text="-", name="ValueReadout")` → `QLabel` for read-only values.
- `_button(text, primary=False, name=None)` → `QPushButton` minimum height (font metrics + 14px).
- `_checkbox(text, checked=None, name=None)` → `QCheckBox` minimum height (control row height).
- `_line_edit(text=None, placeholder=None, name=None)` → `QLineEdit` minimum height (control row height).
- `_combo(items, name=None)` → `QComboBox` minimum height (control row height).
- `_group(title)` → `QGroupBox` (boxed panel).
- `_group_box(title, kind=\"vbox|hbox|grid\")` → `QGroupBox` + layout with standard margins.
- `_plain_text(font=None)` → `QPlainTextEdit`.
- `_table(columns, headers=None, selection_mode=SingleSelection, select_rows=True, name=None)`
- `_list(name=None)` → `QListWidget`
- `_scroll_area(name=None)` → `QScrollArea` (no frame, no horizontal scroll).
- `_splitter(orientation, name=None)` → `QSplitter` (children not collapsible).
- `_checkbox_flow(items)` → `QWidget` with `FlowLayout` for checkbox groups; label left, checkbox right, options wrap based on available width.
- `_action_row(*widgets, align=\"left|center|right\")` → `QWidget` with `QHBoxLayout` and standard top/bottom padding.
- `_action_status_row(*widgets, status=QLabel)` → `QWidget` with status label anchored right.
- `_controls_bar(*items)` → `QWidget` with standard control-row margins and center alignment.
- `_controls_grid(pairs, columns)` → `QWidget` with `QGridLayout` for label/control pairs.
- `_hgap(width)` → `QWidget` fixed-width spacer for control rows.
- `_boxed_row(*widgets, align="left|center|right")` → `QWidget` that adds consistent top/bottom spacing around an action row.
- `_button_grid(buttons, columns)` → `QWidget` with `QGridLayout` for button sets.

## Style roles (object names / QSS roles)
- `SectionTitle`, `FilterLabel`, `FieldLabel`, `CatalogScopeLabel`, `CatalogSearchLabel`
- `CatalogScope`, `CatalogSearch`, `CatalogSearchBtn`, `CatalogResetBtn`
- `SummaryBox`, `DetailsBox`, `SummaryTable`
- `StatValue`, `StatSub`, `ValueReadout`, `HintText`
- `Primary` (primary button)

## Non-widget display helpers
- `QMovie` (scan GIF animation)
- `QGraphicsOpacityEffect` (overlay opacity control for GIF/matrix)
- `QTimer` (matrix animation tick)
- `QFontMetrics` (dynamic combo width sizing)

## Screen catalog (exhaustive)
```json
{
  "global": {
    "header": {
      "logo": {"type": "QLabel", "factory": "_label", "style_role": "HeaderLogo"},
      "title": {"type": "QLabel", "factory": "_label", "style_role": "appTitle"}
    },
    "tabs": {"type": "QTabWidget", "style": "QTabBar/QTabWidget QSS"}
  },
  "Dashboard": {
    "layout": ["QVBoxLayout(panel)", "QHBoxLayout(header)", "QGridLayout(cards)", "QGroupBox(activity)", "QGroupBox(backups)", "QGridLayout(lists)"] ,
    "widgets": [
      {"name": "title", "type": "QLabel", "factory": "_section_title"},
      {"name": "scope_combo", "type": "QComboBox", "factory": "_combo", "rules": ["height=control_row", "width=_set_combo_width"]},
      {"name": "refresh_btn", "type": "QPushButton", "factory": "_button", "rules": ["height=34"]},
      {"name": "stat_cards", "type": "QGroupBox+QLabel", "factory": "_group/_label", "style_role": ["StatValue", "StatSub"]},
      {"name": "activity_text", "type": "QPlainTextEdit", "factory": "_plain_text"},
      {"name": "backup_buttons", "type": "QPushButton[]", "factory": "_button"},
      {"name": "top_lists", "type": "QPlainTextEdit[]", "factory": "_plain_text"}
    ]
  },
  "Scan": {
    "layout": ["QVBoxLayout(panel)", "QHBoxLayout(root_row)", "QHBoxLayout(scope_row)", "QGroupBox(full)", "QGroupBox(targeted)", "QHBoxLayout(actions)", "QStackedLayout(log)"] ,
    "widgets": [
      {"name": "title", "type": "QLabel", "factory": "_section_title"},
      {"name": "root_label", "type": "QLabel", "factory": "_field_label", "buddy": "root_value"},
      {"name": "root_value", "type": "QLabel", "factory": "_value_label", "rules": ["height=control_row"]},
      {"name": "browse_btn", "type": "QPushButton", "factory": "_button"},
      {"name": "scope_label", "type": "QLabel", "factory": "_field_label", "buddy": "scope_combo"},
      {"name": "scope_combo", "type": "QComboBox", "factory": "_combo", "rules": ["height=control_row"]},
      {"name": "full_scan_cbs", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
      {"name": "full_advanced_toggle", "type": "QCheckBox", "factory": "_checkbox"},
      {"name": "full_advanced_cbs", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
      {"name": "targeted_select_btn", "type": "QPushButton", "factory": "_button"},
      {"name": "targeted_summary", "type": "QLabel", "factory": "_label"},
      {"name": "targeted_cbs", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
      {"name": "targeted_advanced_toggle", "type": "QCheckBox", "factory": "_checkbox"},
      {"name": "targeted_advanced_cbs", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
      {"name": "action_buttons", "type": "QPushButton[]", "factory": "_button"},
      {"name": "status_label", "type": "QLabel", "factory": "_label"},
      {"name": "log_text", "type": "QPlainTextEdit", "factory": "_plain_text"},
      {"name": "log_gif", "type": "QLabel", "factory": "_image_label"},
      {"name": "log_matrix", "type": "QLabel", "factory": "_label"}
    ]
  },
  "Catalog": {
    "layout": ["QVBoxLayout(panel)", "QHBoxLayout(title)", "QHBoxLayout(controls)", "QHBoxLayout(content)", "QVBoxLayout(detail_rows)"] ,
    "widgets": [
      {"name": "title", "type": "QLabel", "factory": "_section_title"},
      {"name": "filters_label", "type": "QLabel", "factory": "_label", "style_role": "FilterLabel"},
      {"name": "filter_cbs", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
      {"name": "scope_label", "type": "QLabel", "factory": "_field_label", "buddy": "scope_combo"},
      {"name": "scope_combo", "type": "QComboBox", "factory": "_combo", "rules": ["height=control_row", "width=_set_combo_width"]},
      {"name": "search_label", "type": "QLabel", "factory": "_field_label", "buddy": "search_edit"},
      {"name": "search_edit", "type": "QLineEdit", "factory": "_line_edit", "rules": ["height=control_row"]},
      {"name": "search_btn", "type": "QPushButton", "factory": "_button", "style_role": "CatalogSearchBtn"},
      {"name": "reset_btn", "type": "QPushButton", "factory": "_button", "style_role": "CatalogResetBtn"},
      {"name": "summary_table", "type": "QTableWidget", "factory": "_table", "style_role": "SummaryTable"},
      {"name": "detail_scroll", "type": "QScrollArea", "factory": "_scroll_area"},
      {"name": "detail_labels", "type": "QLabel[]", "factory": "_label"},
      {"name": "detail_buttons", "type": "QPushButton[]", "factory": "_button"}
    ]
  },
  "Insights": {
    "layout": ["QVBoxLayout(panel)", "QHBoxLayout(header)", "QGroupBox(output)"] ,
    "widgets": [
      {"name": "title", "type": "QLabel", "factory": "_section_title"},
      {"name": "scope_combo", "type": "QComboBox", "factory": "_combo"},
      {"name": "refresh_btn", "type": "QPushButton", "factory": "_button"},
      {"name": "output_text", "type": "QPlainTextEdit", "factory": "_plain_text"}
    ]
  },
  "Tools": {
    "layout": ["QVBoxLayout(panel)", "QGroupBox(tool)", "QHBoxLayout(file_row)", "QHBoxLayout(options)", "QHBoxLayout(actions)"] ,
    "widgets": [
      {"name": "path_edit", "type": "QLineEdit", "factory": "_line_edit"},
      {"name": "choose_buttons", "type": "QPushButton[]", "factory": "_button"},
      {"name": "options_cbs", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
      {"name": "action_buttons", "type": "QPushButton[]", "factory": "_button"},
      {"name": "log_text", "type": "QPlainTextEdit", "factory": "_plain_text"}
    ]
  },
  "Preferences": {
    "layout": ["QVBoxLayout(panel)", "QHBoxLayout(header)", "QSplitter(left_right)", "QGroupBox(details)", "QVBoxLayout(detail_rows)"] ,
    "widgets": [
      {"name": "show_raw", "type": "QCheckBox", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
      {"name": "refresh_btn", "type": "QPushButton", "factory": "_button"},
      {"name": "splitter", "type": "QSplitter", "factory": "_splitter"},
      {"name": "source_list", "type": "QListWidget", "factory": "_list"},
      {"name": "detail_labels", "type": "QLabel[]", "factory": "_label"},
      {"name": "payload_text", "type": "QPlainTextEdit", "factory": "_plain_text"}
    ]
  },
  "Settings": {
    "layout": ["QVBoxLayout(panel)", "QGroupBox(maintenance)"] ,
    "widgets": [
      {"name": "maintenance_buttons", "type": "QPushButton[]", "factory": "_button"},
      {"name": "output_text", "type": "QPlainTextEdit", "factory": "_plain_text"}
    ]
  },
  "Dialogs": {
    "TargetedSetDialog": {
      "layout": ["QVBoxLayout(dialog)", "QHBoxLayout(header)", "QTableWidget(table)", "QHBoxLayout(footer)"] ,
      "widgets": [
        {"name": "search_label", "type": "QLabel", "factory": "_field_label", "buddy": "search_edit"},
        {"name": "search_edit", "type": "QLineEdit", "factory": "_line_edit"},
        {"name": "ignore_backups", "type": "QCheckBox", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
        {"name": "table", "type": "QTableWidget", "factory": "_table", "rules": ["selection=ExtendedSelection"]},
        {"name": "apply/cancel", "type": "QPushButton[]", "factory": "_button"}
      ]
    },
    "CleanCatalogDialog": {
      "layout": ["QVBoxLayout(dialog)", "QHBoxLayout(footer)"] ,
      "widgets": [
        {"name": "options_cbs", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
        {"name": "optimize/rebuild", "type": "QCheckBox[]", "factory": "_checkbox", "rules": ["layout=_checkbox_flow"]},
        {"name": "action_buttons", "type": "QPushButton[]", "factory": "_button"}
      ]
    }
  }
}
```

## Coverage summary
- All widgets are now created by rule-based factories or are explicitly listed above.
- Remaining work should **only** add widgets through factories or update this catalog.
