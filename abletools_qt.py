from __future__ import annotations

import json
import random
from string import Template
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QMovie, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSplitter,
    QStackedLayout,
    QGraphicsOpacityEffect,
    QScrollArea,
    QFrame,
)

from abletools_catalog_ops import backup_files
from abletools_actions import open_in_finder, run_catalog_cleanup, run_targeted_scan
from abletools_core import CatalogService, format_bytes, format_mtime, safe_read_json
from ramify_core import iter_targets, process_file

ABLETOOLS_DIR = Path(__file__).resolve().parent

_TIMESTAMP_BRACKET_RE = re.compile(r"\[[0-9][0-9  T:_-]{4,}[0-9]\]")


def is_backup_path(path: str) -> bool:
    if not path:
        return False
    p = Path(path)
    if any(part.lower() == "backup" for part in p.parts):
        return True
    return bool(_TIMESTAMP_BRACKET_RE.search(p.name))


def _set_combo_width(combo: QComboBox, padding: int = 44, minimum: int | None = None) -> None:
    metrics = QFontMetrics(combo.font())
    widest = 0
    for idx in range(combo.count()):
        widest = max(widest, metrics.horizontalAdvance(combo.itemText(idx)))
    width = widest + padding
    if minimum is not None:
        width = max(width, minimum)
    combo.setFixedWidth(width)


SPACE_PANEL = 12
SPACE_ROW = 12
SPACE_TIGHT = 8
SPACE_SECTION = 16
GROUP_MARGIN = 12
ROOT_MARGIN_X = 12
ROOT_MARGIN_TOP = 8
ROOT_MARGIN_BOTTOM = 12
HEADER_MARGIN_X = 18
HEADER_MARGIN_Y = 12
CONTROL_ROW_MARGIN = 4
DIALOG_MARGIN = 12
FILTER_LABEL_GAP = 4
HEADER_LOGO_SIZE = 44
FIELD_LABEL_HEIGHT = 22
DETAIL_LABEL_WIDTH = 96
CONTROL_ROW_HEIGHT = FIELD_LABEL_HEIGHT
BUTTON_HEIGHT = 32
BUTTON_PADDING_Y = 3


def _vbox(parent: QWidget | None = None, spacing: int = SPACE_PANEL) -> QVBoxLayout:
    layout = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(0, 0, 0, 0)
    return layout


def _hbox(parent: QWidget | None = None, spacing: int = SPACE_ROW) -> QHBoxLayout:
    layout = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(0, 0, 0, 0)
    return layout


def _grid(parent: QWidget | None = None, spacing: int = SPACE_PANEL) -> QGridLayout:
    layout = QGridLayout(parent) if parent is not None else QGridLayout()
    layout.setHorizontalSpacing(spacing)
    layout.setVerticalSpacing(spacing)
    layout.setContentsMargins(0, 0, 0, 0)
    return layout


def _panel_margins(layout: QVBoxLayout, inset: int = SPACE_PANEL) -> None:
    layout.setContentsMargins(inset, inset, inset, inset)


def _label(text: str, name: str | None = None) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    return label


def _image_label() -> QLabel:
    return QLabel()


def _section_title(text: str) -> QLabel:
    return _label(text, "SectionTitle")


def _field_label(
    text: str, buddy: QWidget | None = None, name: str | None = "FieldLabel"
) -> QLabel:
    label = _label(text, name)
    label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    label.setFixedHeight(FIELD_LABEL_HEIGHT)
    if buddy is not None:
        label.setBuddy(buddy)
    return label


def _value_label(text: str = "-", name: str | None = "ValueReadout") -> QLabel:
    label = _label(text, name)
    label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setFixedHeight(FIELD_LABEL_HEIGHT)
    return label


def _button(text: str, primary: bool = False, name: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setFixedHeight(BUTTON_HEIGHT)
    if primary:
        btn.setObjectName("Primary")
    elif name:
        btn.setObjectName(name)
    return btn


def _checkbox(text: str, checked: bool | None = None, name: str | None = None) -> QCheckBox:
    cb = QCheckBox(text)
    if checked is not None:
        cb.setChecked(checked)
    if name:
        cb.setObjectName(name)
    return cb


def _line_edit(
    text: str | None = None,
    placeholder: str | None = None,
    name: str | None = None,
) -> QLineEdit:
    edit = QLineEdit(text or "")
    if placeholder:
        edit.setPlaceholderText(placeholder)
    if name:
        edit.setObjectName(name)
    edit.setFixedHeight(22)
    return edit


def _combo(items: list[str], name: str | None = None) -> QComboBox:
    combo = QComboBox()
    combo.addItems(items)
    if name:
        combo.setObjectName(name)
    combo.setFixedHeight(22)
    return combo


def _group(title: str) -> QGroupBox:
    return QGroupBox(title)


def _group_box(
    title: str, kind: str = "vbox", spacing: int = SPACE_PANEL
) -> tuple[QGroupBox, object]:
    group = _group(title)
    if kind == "hbox":
        layout: object = _hbox(group, spacing)
    elif kind == "grid":
        layout = _grid(group, spacing)
    elif kind == "form":
        layout = QFormLayout(group)
        layout.setSpacing(spacing)
    else:
        layout = _vbox(group, spacing)
    layout.setContentsMargins(GROUP_MARGIN, GROUP_MARGIN, GROUP_MARGIN, GROUP_MARGIN)
    return group, layout


def _boxed_row(
    *widgets: QWidget,
    align: str = "left",
    top: int = SPACE_PANEL,
    bottom: int = SPACE_PANEL,
) -> QWidget:
    container = QWidget()
    layout = _vbox(container)
    layout.addSpacing(top)
    layout.addWidget(_action_row(*widgets, align=align))
    layout.addSpacing(bottom)
    return container


def _plain_text(font: QFont | None = None) -> QPlainTextEdit:
    box = QPlainTextEdit()
    if font:
        box.setFont(font)
    return box


def _section_gap(layout: QVBoxLayout, amount: int = SPACE_SECTION) -> None:
    layout.addSpacing(amount)


def _checkbox_row(*boxes: QCheckBox) -> QWidget:
    row = QWidget()
    layout = _hbox(row)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    for box in boxes:
        layout.addWidget(box)
    layout.addStretch(1)
    return row


def _action_row(
    *widgets: QWidget,
    align: str = "left",
    top: int = SPACE_PANEL,
    bottom: int = SPACE_PANEL,
) -> QWidget:
    row = QWidget()
    layout = _hbox(row)
    layout.setContentsMargins(0, top, 0, bottom)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    if align == "right":
        layout.addStretch(1)
        for widget in widgets:
            layout.addWidget(widget)
        return row
    if align == "center":
        layout.addStretch(1)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return row


def _action_status_row(
    *widgets: QWidget,
    status: QLabel,
    top: int = SPACE_PANEL,
    bottom: int = SPACE_PANEL,
) -> QWidget:
    row = QWidget()
    layout = _hbox(row)
    layout.setContentsMargins(0, top, 0, bottom)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    layout.addWidget(status)
    return row


def _controls_bar(*items: QWidget, stretch: bool = False) -> QWidget:
    bar = QWidget()
    layout = _hbox(bar)
    layout.setContentsMargins(0, CONTROL_ROW_MARGIN, 0, CONTROL_ROW_MARGIN)
    layout.setSpacing(SPACE_ROW)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    for item in items:
        layout.addWidget(item, 0, Qt.AlignmentFlag.AlignVCenter)
    if stretch:
        layout.addStretch(1)
    return bar


def _hgap(width: int) -> QWidget:
    spacer = QWidget()
    spacer.setFixedWidth(width)
    return spacer


def _table(
    columns: int,
    headers: list[str] | None = None,
    selection_mode: QTableWidget.SelectionMode = QTableWidget.SelectionMode.SingleSelection,
    select_rows: bool = True,
    name: str | None = None,
) -> QTableWidget:
    table = QTableWidget(0, columns)
    if headers:
        table.setHorizontalHeaderLabels(headers)
    if select_rows:
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(selection_mode)
    if name:
        table.setObjectName(name)
    return table


def _list(name: str | None = None) -> QListWidget:
    widget = QListWidget()
    if name:
        widget.setObjectName(name)
    return widget


def _scroll_area(name: str | None = None) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    if name:
        scroll.setObjectName(name)
    return scroll


def _splitter(orientation: Qt.Orientation, name: str | None = None) -> QSplitter:
    splitter = QSplitter(orientation)
    splitter.setChildrenCollapsible(False)
    if name:
        splitter.setObjectName(name)
    return splitter


class ScanWorker(QThread):
    line = pyqtSignal(str)
    status = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, cmds: list[list[str]], workdir: Path) -> None:
        super().__init__()
        self._cmds = cmds
        self._workdir = workdir
        self._stop_requested = False
        self._proc: Optional[subprocess.Popen[str]] = None

    def stop(self) -> None:
        self._stop_requested = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        exit_code = 0
        for idx, cmd in enumerate(self._cmds, start=1):
            if self._stop_requested:
                break
            self.status.emit(f"Running {idx}/{len(self._cmds)}...")
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(self._workdir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:
                self.line.emit(f"ERROR: {exc}")
                exit_code = 1
                break
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._stop_requested:
                    break
                self.line.emit(line.rstrip("\n"))
            self._proc.wait()
            exit_code = self._proc.returncode or 0
            if exit_code != 0 or self._stop_requested:
                break
        self.finished.emit(exit_code)


class CommandWorker(QThread):
    output = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, cmd: list[str], workdir: Path) -> None:
        super().__init__()
        self._cmd = cmd
        self._workdir = workdir

    def run(self) -> None:
        try:
            proc = subprocess.run(
                self._cmd,
                cwd=str(self._workdir),
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            self.output.emit(f"ERROR: {exc}")
            self.finished.emit(1)
            return
        if proc.stdout:
            self.output.emit(proc.stdout.strip())
        if proc.stderr:
            self.output.emit(proc.stderr.strip())
        self.finished.emit(proc.returncode)


class AuditWorker(QThread):
    output = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self._catalog = catalog

    def run(self) -> None:
        try:
            issues = self._catalog.audit_zero_tracks()
        except Exception as exc:
            self.output.emit(f"ERROR: {exc}")
            self.finished.emit(1)
            return
        if not issues:
            self.output.emit("No zero-track sets found.")
        else:
            for entry in issues:
                self.output.emit(entry)
        self.finished.emit(0)


class RamifyWorker(QThread):
    output = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, target: Path, dry: bool, inplace: bool, recursive: bool) -> None:
        super().__init__()
        self._target = target
        self._dry = dry
        self._inplace = inplace
        self._recursive = recursive

    def run(self) -> None:
        total_files = total_audio = total_flips = failed = 0
        for f in iter_targets(self._target, self._recursive):
            total_files += 1
            try:
                audio_seen, flips, wrote = process_file(f, self._inplace, self._dry)
                total_audio += audio_seen
                total_flips += flips
                action = "DRY" if self._dry else ("INPLACE" if self._inplace else "OUT")
                if wrote:
                    self.output.emit(
                        f"[{action}] {f} | AudioClips={audio_seen} | RamFlips={flips} | wrote={wrote}"
                    )
                else:
                    self.output.emit(
                        f"[{action}] {f} | AudioClips={audio_seen} | RamFlips={flips}"
                    )
            except Exception as exc:
                failed += 1
                self.output.emit(f"[FAIL] {f} | {exc}")
        self.output.emit("")
        self.output.emit(
            "Done. Files={files} Failed={failed} AudioClips={audio} RamFlips={flips}".format(
                files=total_files, failed=failed, audio=total_audio, flips=total_flips
            )
        )
        if self._dry and total_flips > 0:
            self.output.emit("Re-run with Dry run unchecked to apply changes.")
        self.finished.emit()


class TargetedSetDialog(QDialog):
    def __init__(self, items: list[dict[str, str]], include_backups: bool) -> None:
        super().__init__()
        self.setWindowTitle("Select Sets for Targeted Scan")
        self.resize(980, 640)
        self._items = items
        self._filtered: list[dict[str, str]] = []
        self._ignore_backups = not include_backups
        self._build_ui()
        self._refresh_table()

    def _build_ui(self) -> None:
        layout = _vbox(self)

        header = _hbox()
        header.setSpacing(SPACE_ROW)
        header.setContentsMargins(0, 0, 0, 0)
        header.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_label = _field_label("Search:")
        header.addWidget(header_label)
        self.search_edit = _line_edit()
        header_label.setBuddy(self.search_edit)
        self.search_edit.textChanged.connect(self._refresh_table)
        header.addWidget(self.search_edit)
        self.ignore_backups = _checkbox("Ignore backups")
        self.ignore_backups.setChecked(self._ignore_backups)
        self.ignore_backups.stateChanged.connect(self._refresh_table)
        header.addWidget(self.ignore_backups)
        layout.addLayout(header)

        self.table = _table(
            6,
            headers=["Scope", "Name", "Path", "Modified", "Tracks", "Clips"],
            selection_mode=QTableWidget.SelectionMode.ExtendedSelection,
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        self.apply_btn = _button("Use Selected", primary=True)
        self.apply_btn.clicked.connect(self.accept)
        cancel_btn = _button("Cancel")
        cancel_btn.clicked.connect(self.reject)
        footer = _action_row(self.apply_btn, cancel_btn, align="right")
        layout.addWidget(footer)

    def selected_items(self) -> list[dict[str, str]]:
        items = []
        for idx in self.table.selectionModel().selectedRows():
            row = idx.row()
            if 0 <= row < len(self._filtered):
                items.append(self._filtered[row])
        return items

    def _refresh_table(self) -> None:
        query = self.search_edit.text().strip().lower()
        ignore_backups = self.ignore_backups.isChecked()
        filtered = []
        for item in self._items:
            path = item.get("path", "")
            if ignore_backups and is_backup_path(path):
                continue
            hay = f"{item.get('scope','')} {item.get('name','')} {path}".lower()
            if query and query not in hay:
                continue
            filtered.append(item)
        self._filtered = filtered
        self.table.setRowCount(len(filtered))
        for row_idx, item in enumerate(filtered):
            values = [
                item.get("scope", ""),
                item.get("name", ""),
                item.get("path", ""),
                format_mtime(item.get("mtime")),
                str(item.get("tracks", "")),
                str(item.get("clips", "")),
            ]
            for col_idx, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, cell)
        self.table.resizeColumnsToContents()


class DashboardView(QWidget):
    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = _vbox(self)
        _panel_margins(layout)

        header = _hbox()
        title = _section_title("Dashboard")
        header.addWidget(title)
        self.scope_combo = _combo(["live_recordings", "user_library"])
        self.scope_combo.currentTextChanged.connect(self.refresh)
        _set_combo_width(self.scope_combo, padding=44)
        header.addWidget(self.scope_combo)
        header.addStretch(1)
        refresh_btn = _button("Refresh", primary=True)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)
        _section_gap(layout)

        cards = _grid()
        self.card_sets_value, self.card_sets_sub = self._stat_card(cards, "Total Sets", 0)
        self.card_set_size_value, _ = self._stat_card(cards, "Set Size", 1)
        self.card_audio_size_value, _ = self._stat_card(cards, "Audio Size", 2)
        self.card_missing_value, _ = self._stat_card(cards, "Sets Missing Refs", 3)
        layout.addLayout(cards)
        _section_gap(layout)

        activity_box, activity_layout = _group_box("Catalog Status")
        self.activity_text = _plain_text(QFont("Menlo", 11))
        self.activity_text.setReadOnly(True)
        activity_layout.addWidget(self.activity_text)
        layout.addWidget(activity_box)
        _section_gap(layout)

        backup_box, backup_layout = _group_box("Backups")
        backup_sets = _button("Backup Sets", primary=True)
        backup_sets.clicked.connect(self._backup_sets)
        backup_audio = _button("Backup Audio")
        backup_audio.clicked.connect(self._backup_audio)
        cleanup_btn = _button("Clean Catalog")
        cleanup_btn.clicked.connect(self._cleanup_catalog)
        backup_layout.addWidget(
            _boxed_row(backup_sets, backup_audio, cleanup_btn, align="left")
        )
        layout.addWidget(backup_box)
        _section_gap(layout)

        lists_layout = _grid()
        self.top_devices = _plain_text(QFont("Menlo", 11))
        self.top_plugins = _plain_text(QFont("Menlo", 11))
        self.top_chains = _plain_text(QFont("Menlo", 11))
        self.top_missing = _plain_text(QFont("Menlo", 11))
        for widget in [self.top_devices, self.top_plugins, self.top_chains, self.top_missing]:
            widget.setReadOnly(True)
            widget.setMaximumHeight(140)

        lists_layout.addWidget(_boxed("Top Devices", self.top_devices), 0, 0)
        lists_layout.addWidget(_boxed("Top Plugins", self.top_plugins), 0, 1)
        lists_layout.addWidget(_boxed("Top Chains", self.top_chains), 1, 0)
        lists_layout.addWidget(_boxed("Missing Ref Hotspots", self.top_missing), 1, 1)
        layout.addLayout(lists_layout)
        layout.addStretch(1)

    def _stat_card(self, layout: QGridLayout, title: str, col: int) -> tuple[QLabel, QLabel]:
        box, box_layout = _group_box(title)
        value = _label("-", "StatValue")
        sub = _label("", "StatSub")
        box_layout.addWidget(value)
        box_layout.addWidget(sub)
        layout.addWidget(box, 0, col)
        return value, sub

    def refresh(self) -> None:
        scope = self.scope_combo.currentText() or "live_recordings"
        focus = self.catalog.load_dashboard_focus(scope)
        total_sets = int(focus.get("set_count_total", 0))
        non_backup = int(focus.get("set_count_non_backup", 0))
        backup_sets = max(0, total_sets - non_backup)
        self.card_sets_value.setText(str(total_sets))
        self.card_sets_sub.setText(f"Non-backup: {non_backup}  Backup: {backup_sets}")
        self.card_set_size_value.setText(format_bytes(focus.get("set_bytes", 0)))
        self.card_audio_size_value.setText(format_bytes(focus.get("audio_bytes", 0)))
        self.card_missing_value.setText(str(focus.get("missing_sets", 0)))

        summary_path = self.catalog.catalog_dir / "scan_summary.json"
        summary = safe_read_json(summary_path) if summary_path.exists() else {}
        lines = []
        if summary:
            lines.append(f"Last scan: {summary.get('generated_at', '')}")
            lines.append(f"Files scanned: {summary.get('files_scanned', 0)}")
            lines.append(f"Files indexed: {summary.get('files_indexed', 0)}")
            lines.append(f"Docs parsed: {summary.get('ableton_docs_parsed', 0)}")
            lines.append(f"Refs missing: {summary.get('refs_missing', 0)}")
            lines.append(f"Duration sec: {summary.get('duration_sec', 0)}")
        else:
            lines.append("No scan summary found.")
        self.activity_text.setPlainText("\n".join(lines))

        self.top_devices.setPlainText(
            "\n".join(self.catalog.load_top_devices() or ["No data yet."])
        )
        self.top_plugins.setPlainText(
            "\n".join(self.catalog.load_top_plugins() or ["No data yet."])
        )
        self.top_chains.setPlainText(
            "\n".join(self.catalog.load_top_chains() or ["No data yet."])
        )
        self.top_missing.setPlainText(
            "\n".join(self.catalog.load_missing_refs_paths() or ["No data yet."])
        )

    def _backup_sets(self) -> None:
        self._run_backup("sets")

    def _backup_audio(self) -> None:
        self._run_backup("audio")

    def _run_backup(self, kind: str) -> None:
        scope = self.scope_combo.currentText() or "live_recordings"
        dest = QFileDialog.getExistingDirectory(self, "Choose backup folder")
        if not dest:
            return
        paths = self.catalog.list_backup_paths(scope, kind)
        copied, skipped, archive_path = backup_files(paths, Path(dest), None, kind)
        label = "sets" if kind == "sets" else "audio files"
        if copied > 0:
            archive_note = f" Archive: {archive_path.name}" if archive_path else ""
            QMessageBox.information(
                self,
                "Backup",
                f"Backed up {copied} {label}.{archive_note} Skipped {skipped} existing files.",
            )
        else:
            QMessageBox.information(
                self,
                "Backup",
                f"No {label} copied. Skipped {skipped} existing files.",
            )

    def _cleanup_catalog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Clean Catalog")
        dialog.resize(520, 360)
        layout = _vbox(dialog)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.addWidget(_label("Select items to remove from .abletools_catalog"))

        options = {
            "logs": _checkbox("Old scan logs + audit reports"),
            "xml_nodes": _checkbox("XML nodes JSONL (large)"),
            "device_params": _checkbox("Device params JSONL (large)"),
            "refs_graph": _checkbox("Refs graph JSONL"),
            "struct": _checkbox("Struct/clip/routing JSONL"),
            "scan_state": _checkbox("Scan + dir state (incremental cache)"),
        }
        defaults = {"logs": True, "xml_nodes": True, "device_params": True}
        for key, checkbox in options.items():
            checkbox.setChecked(defaults.get(key, False))
            layout.addWidget(checkbox)

        optimize_cb = _checkbox("Optimize DB after cleanup (ANALYZE + VACUUM)")
        optimize_cb.setChecked(True)
        rebuild_cb = _checkbox("Rebuild DB from remaining JSONL (overwrite)")
        layout.addWidget(optimize_cb)
        layout.addWidget(rebuild_cb)

        run_btn = _button("Clean", primary=True)
        cancel_btn = _button("Cancel")
        btns = _action_row(run_btn, cancel_btn, align="left")
        layout.addWidget(btns)

        def _run() -> None:
            selected = {k: v.isChecked() for k, v in options.items()}
            _, _, summary = run_catalog_cleanup(
                self.catalog.catalog_dir,
                selected,
                rebuild_cb.isChecked(),
                optimize_cb.isChecked(),
            )
            QMessageBox.information(
                self,
                "Clean Catalog",
                summary,
            )
            dialog.accept()
            self.refresh()

        run_btn.clicked.connect(_run)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()


class InsightsView(QWidget):
    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = _vbox(self)
        _panel_margins(layout)

        header = _hbox()
        title = _section_title("Insights")
        header.addWidget(title)
        header.addStretch(1)
        refresh_btn = _button("Refresh", primary=True)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)
        _section_gap(layout)

        self.scope_combo = _combo(["live_recordings", "user_library", "preferences"])
        self.scope_combo.currentTextChanged.connect(self.refresh)
        layout.addWidget(self.scope_combo)
        _section_gap(layout)

        self.text = _plain_text(QFont("Menlo", 11))
        self.text.setReadOnly(True)
        layout.addWidget(self.text)

    def refresh(self) -> None:
        scope = self.scope_combo.currentText() or "live_recordings"
        lines = []
        lines.append("Set Health (Worst)")
        lines.extend(self.catalog.load_set_health(scope, limit=8) or ["No data yet."])
        lines.append("")
        lines.append("Missing Ref Hotspots")
        lines.extend(self.catalog.load_missing_hotspots(scope, limit=8) or ["No data yet."])
        lines.append("")
        lines.append("Audio Footprint")
        footprint = self.catalog.load_audio_footprint(scope)
        if footprint:
            lines.append(
                f"Total media: {format_bytes(footprint.get('total_media_bytes', 0))}"
            )
            lines.append(
                f"Referenced: {format_bytes(footprint.get('referenced_media_bytes', 0))}"
            )
            lines.append(
                f"Unreferenced: {format_bytes(footprint.get('unreferenced_media_bytes', 0))}"
            )
        else:
            lines.append("No data yet.")
        lines.append("")
        lines.append("Top Device Chains")
        lines.extend(self.catalog.load_chain_fingerprints(scope, limit=8) or ["No data yet."])
        lines.append("")
        lines.append("Set Storage + Activity")
        storage = self.catalog.load_set_storage_summary(scope)
        if storage:
            lines.append(
                f"Sets: {storage.get('total_sets', 0)} "
                f"({format_bytes(storage.get('total_set_bytes', 0))})"
            )
            lines.append(
                f"Non-backup: {storage.get('non_backup_sets', 0)} "
                f"({format_bytes(storage.get('non_backup_bytes', 0))})"
            )
        else:
            lines.append("No data yet.")
        lines.extend(self.catalog.load_set_activity(scope) or [])
        lines.append("")
        lines.append("Largest Sets")
        lines.extend(self.catalog.load_largest_sets(scope, limit=8) or ["No data yet."])
        lines.append("")
        lines.append("Unreferenced Audio Hotspots")
        lines.extend(self.catalog.load_unreferenced_audio(scope, limit=8) or ["No data yet."])
        lines.append("")
        lines.append("Quality Flags")
        lines.extend(self.catalog.load_quality_issues(scope, limit=8) or ["No data yet."])
        lines.append("")
        lines.append("Recent Devices (30d)")
        lines.extend(
            self.catalog.load_recent_device_usage(scope, window_days=30, limit=8)
            or ["No data yet."]
        )
        lines.append("")
        lines.append("Top Device Pairs")
        lines.extend(self.catalog.load_device_pairs(scope, limit=8) or ["No data yet."])
        self.text.setPlainText("\n".join(lines))


class ScanView(QWidget):
    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self.targeted_items: list[dict[str, str]] = []
        self.worker: Optional[ScanWorker] = None
        self._log_file: Optional[Path] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = _vbox(self)
        _panel_margins(layout)

        self._build_header(layout)
        self._build_root_row(layout)
        layout.addSpacing(SPACE_TIGHT)
        groups_row = _hbox()
        full_group = self._build_full_group()
        targeted_group = self._build_targeted_group()
        full_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        targeted_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        groups_row.addWidget(full_group, 1)
        groups_row.addWidget(targeted_group, 1)
        groups_row.setStretch(0, 1)
        groups_row.setStretch(1, 1)
        layout.addLayout(groups_row)
        _section_gap(layout)
        self._build_buttons(layout)
        _section_gap(layout)
        self._build_log(layout)

    def _build_header(self, layout: QVBoxLayout) -> None:
        header = _hbox()
        title = _section_title("Scan")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

    def _build_root_row(self, layout: QVBoxLayout) -> None:
        root_row = _hbox()
        root_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        root_label = _field_label("Root folder:")
        self.root_value = _value_label()
        self.root_value.setMinimumWidth(320)
        self.root_value.setMaximumWidth(520)
        self.root_path = self._default_root()
        self._set_root_path(self.root_path)
        root_label.setBuddy(self.root_value)
        root_row.addWidget(root_label)
        root_row.addWidget(self.root_value)
        browse_btn = _button("Browse")
        browse_btn.clicked.connect(self._browse_root)
        root_row.addWidget(browse_btn)
        root_row.addWidget(_hgap(SPACE_ROW))
        scope_label = _field_label("Scope:")
        self.scope_combo = _combo(["live_recordings", "user_library", "preferences", "all"])
        self.scope_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        scope_label.setBuddy(self.scope_combo)
        root_row.addWidget(scope_label)
        root_row.addWidget(self.scope_combo)
        root_row.addStretch(1)
        layout.addLayout(root_row)

    def _build_full_group(self) -> QGroupBox:
        full_group, full_layout = _group_box("Full Scan", kind="grid")
        self.incremental_cb = _checkbox("Incremental (skip unchanged)")
        self.include_media_cb = _checkbox("Include media files")
        self.hash_cb = _checkbox("Compute hashes")
        self.analyze_audio_cb = _checkbox("Analyze audio")
        self.include_backups_cb = _checkbox("Include Backup folders")
        self.changed_only_cb = _checkbox("Changed-only scan")
        self.checkpoint_cb = _checkbox("Write checkpoints")
        self.resume_cb = _checkbox("Resume checkpoint")
        self.rehash_cb = _checkbox("Rehash unchanged")
        self.hash_docs_cb = _checkbox("Hash Ableton sets only")
        self.full_advanced_toggle = _checkbox("Advanced options")
        self.full_advanced_toggle.setChecked(False)
        for cb in [
            self.incremental_cb,
            self.include_media_cb,
            self.hash_cb,
            self.analyze_audio_cb,
        ]:
            cb.setChecked(cb in [self.incremental_cb, self.checkpoint_cb])
        full_layout.addWidget(self.incremental_cb, 0, 0)
        full_layout.addWidget(self.include_media_cb, 0, 1)
        full_layout.addWidget(self.hash_cb, 0, 2)
        full_layout.addWidget(self.analyze_audio_cb, 0, 3)
        full_layout.addWidget(self.full_advanced_toggle, 1, 0, 1, 2)

        self.full_advanced_box = QWidget()
        full_adv_layout = _grid(self.full_advanced_box, spacing=SPACE_PANEL)
        full_adv_layout.setVerticalSpacing(SPACE_PANEL)
        full_adv_layout.addWidget(self.include_backups_cb, 0, 0)
        full_adv_layout.addWidget(self.changed_only_cb, 0, 1)
        full_adv_layout.addWidget(self.checkpoint_cb, 0, 2)
        full_adv_layout.addWidget(self.resume_cb, 0, 3)
        full_adv_layout.addWidget(self.rehash_cb, 1, 0)
        full_adv_layout.addWidget(self.hash_docs_cb, 1, 1)
        self.full_advanced_box.setVisible(False)
        self.full_advanced_toggle.toggled.connect(self.full_advanced_box.setVisible)
        full_layout.addWidget(self.full_advanced_box, 2, 0, 1, 4)
        return full_group

    def _build_targeted_group(self) -> QGroupBox:
        targeted_group, targeted_layout = _group_box("Targeted Scan")

        select_row = _hbox()
        select_btn = _button("Select Sets", primary=True)
        select_btn.clicked.connect(self._select_sets)
        self.targeted_summary = _label("No targeted sets selected.")
        select_row.addWidget(select_btn)
        select_row.addWidget(self.targeted_summary)
        select_row.addStretch(1)
        targeted_layout.addLayout(select_row)

        self.struct_cb = _checkbox("Struct")
        self.clips_cb = _checkbox("Clips")
        self.devices_cb = _checkbox("Devices")
        self.routing_cb = _checkbox("Routing")
        self.refs_cb = _checkbox("Refs")
        for cb in [self.struct_cb, self.clips_cb, self.devices_cb, self.routing_cb, self.refs_cb]:
            cb.setChecked(True)
        checks_row = _checkbox_row(
            self.struct_cb,
            self.clips_cb,
            self.devices_cb,
            self.routing_cb,
            self.refs_cb,
        )
        targeted_layout.addWidget(checks_row)

        self.deep_snapshot_cb = _checkbox("Deep XML snapshot")
        self.xml_nodes_cb = _checkbox("XML nodes (huge)")
        self.targeted_advanced_toggle = _checkbox("Advanced options")
        self.targeted_advanced_toggle.setChecked(False)
        targeted_layout.addWidget(self.targeted_advanced_toggle)
        self.targeted_advanced_box = QWidget()
        targeted_adv_layout = _hbox(self.targeted_advanced_box)
        targeted_adv_layout.addWidget(self.deep_snapshot_cb)
        targeted_adv_layout.addWidget(self.xml_nodes_cb)
        targeted_adv_layout.addStretch(1)
        self.targeted_advanced_box.setVisible(False)
        self.targeted_advanced_toggle.toggled.connect(self.targeted_advanced_box.setVisible)
        targeted_layout.addWidget(self.targeted_advanced_box)
        return targeted_group

    def _build_buttons(self, layout: QVBoxLayout) -> None:
        self.run_full_btn = _button("Run Full Scan", primary=True)
        self.run_full_btn.clicked.connect(self._run_full)
        self.run_targeted_btn = _button("Run Targeted")
        self.run_targeted_btn.clicked.connect(self._run_targeted)
        self.cancel_btn = _button("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        self.status_label = _label("Idle")
        btn_row = _action_status_row(
            self.run_full_btn,
            self.run_targeted_btn,
            self.cancel_btn,
            status=self.status_label,
        )
        layout.addWidget(btn_row)

    def _build_log(self, layout: QVBoxLayout) -> None:
        log_container = QWidget()
        log_stack = QStackedLayout(log_container)
        log_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self._scan_gif = _image_label()
        self._scan_gif.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scan_gif.setScaledContents(False)
        gif_path = ABLETOOLS_DIR / "resources" / "scanners4-1920341542.gif"
        self._scan_movie = QMovie(str(gif_path)) if gif_path.exists() else None
        if self._scan_movie:
            self._scan_gif.setMovie(self._scan_movie)
        opacity = QGraphicsOpacityEffect(self._scan_gif)
        opacity.setOpacity(0.22)
        self._scan_gif.setGraphicsEffect(opacity)
        log_stack.addWidget(self._scan_gif)

        self._matrix = _label("")
        self._matrix.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._matrix.setFont(QFont("Menlo", 10))
        self._matrix.setStyleSheet("color: #19f5c8;")
        self._matrix_effect = QGraphicsOpacityEffect(self._matrix)
        self._matrix_effect.setOpacity(0.35)
        self._matrix.setGraphicsEffect(self._matrix_effect)
        self._matrix_timer = QTimer(self)
        self._matrix_timer.setInterval(90)
        self._matrix_timer.timeout.connect(self._tick_matrix)
        self._matrix_lines = 8
        self._matrix_cols = 64
        log_stack.addWidget(self._matrix)

        self.log = _plain_text(QFont("Menlo", 11))
        self.log.setReadOnly(True)
        self.log.setStyleSheet("background-color: rgba(11, 20, 32, 0.72);")
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_stack.addWidget(self.log)
        layout.addWidget(log_container)

    def _default_root(self) -> Path:
        return self.catalog.catalog_dir.parent

    def _browse_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Root")
        if path:
            self._set_root_path(Path(path))

    def _set_root_path(self, path: Path) -> None:
        self.root_path = path
        metrics = QFontMetrics(self.root_value.font())
        elided = metrics.elidedText(
            str(self.root_path), Qt.TextElideMode.ElideMiddle, self.root_value.maximumWidth()
        )
        self.root_value.setText(elided)
        self.root_value.setToolTip(str(self.root_path))

    def _select_sets(self) -> None:
        items = self.catalog.get_known_sets("all")
        if not items:
            QMessageBox.information(self, "Targeted Scan", "No sets found. Run a scan.")
            return
        items = _dedupe_targeted(items)
        dialog = TargetedSetDialog(items, include_backups=self.include_backups_cb.isChecked())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.targeted_items = dialog.selected_items()
        self._update_targeted_summary()

    def _update_targeted_summary(self) -> None:
        if not self.targeted_items:
            self.targeted_summary.setText("No targeted sets selected.")
            return
        counts: dict[str, int] = {}
        for item in self.targeted_items:
            counts[item.get("scope", "unknown")] = counts.get(item.get("scope", "unknown"), 0) + 1
        summary = ", ".join(f"{count} {scope}" for scope, count in counts.items())
        self.targeted_summary.setText(f"{len(self.targeted_items)} set(s) selected ({summary})")

    def _run_full(self) -> None:
        root = self.root_path
        if not root.exists():
            QMessageBox.warning(self, "Scan", f"Root folder does not exist:\n{root}")
            return
        scan_script = ABLETOOLS_DIR / "abletools_scan.py"
        if not scan_script.exists():
            QMessageBox.warning(self, "Scan", f"Missing scanner script:\n{scan_script}")
            return
        scope = self.scope_combo.currentText() or "live_recordings"
        scopes = [scope] if scope != "all" else ["live_recordings", "user_library", "preferences"]
        cmds: list[list[str]] = []
        for scope_name in scopes:
            cmd = [sys.executable, str(scan_script), str(root), "--scope", scope_name]
            cmd.extend(["--out", str(self.catalog.catalog_dir)])
            cmd.extend(["--mode", "full", "--progress", "--verbose"])
            if self.incremental_cb.isChecked():
                cmd.append("--incremental")
            if self.include_media_cb.isChecked():
                cmd.append("--include-media")
            if self.include_backups_cb.isChecked():
                cmd.append("--include-backups")
            if self.analyze_audio_cb.isChecked():
                cmd.append("--analyze-audio")
            if self.hash_cb.isChecked():
                cmd.append("--hash")
            if self.rehash_cb.isChecked():
                cmd.append("--rehash-all")
            if self.hash_docs_cb.isChecked():
                cmd.append("--hash-docs-only")
            if self.changed_only_cb.isChecked():
                cmd.append("--changed-only")
            if self.checkpoint_cb.isChecked():
                cmd.append("--checkpoint")
            if self.resume_cb.isChecked():
                cmd.append("--resume")
            cmds.append(cmd)
        self._start_worker(cmds)

    def _run_targeted(self) -> None:
        if not self.targeted_items:
            QMessageBox.information(self, "Targeted Scan", "No sets selected.")
            return
        details = []
        if self.struct_cb.isChecked():
            details.append("struct")
        if self.clips_cb.isChecked():
            details.append("clips")
        if self.devices_cb.isChecked():
            details.append("devices")
        if self.routing_cb.isChecked():
            details.append("routing")
        if self.refs_cb.isChecked():
            details.append("refs")
        if not details:
            QMessageBox.information(self, "Targeted Scan", "Select at least one detail group.")
            return
        scan_script = ABLETOOLS_DIR / "abletools_scan.py"
        cmds: list[list[str]] = []
        for item in self.targeted_items:
            path = item.get("path")
            scope = item.get("scope") or self.scope_combo.currentText()
            if not path:
                continue
            cmd = [
                sys.executable,
                str(scan_script),
                str(path),
                "--scope",
                scope,
                "--mode",
                "targeted",
                "--details",
                ",".join(details),
                "--out",
                str(self.catalog.catalog_dir),
                "--incremental",
                "--progress",
                "--verbose",
            ]
            if self.include_backups_cb.isChecked():
                cmd.append("--include-backups")
            if self.deep_snapshot_cb.isChecked():
                cmd.append("--deep-xml-snapshot")
            if self.xml_nodes_cb.isChecked():
                cmd.append("--xml-nodes")
            cmds.append(cmd)
        self._start_worker(cmds)

    def _start_worker(self, cmds: list[list[str]]) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.log.clear()
        self.status_label.setText("Running...")
        self.run_full_btn.setEnabled(False)
        self.run_targeted_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        if self._scan_movie:
            self._scan_movie.start()
        self._start_matrix()

        self.worker = ScanWorker(cmds, ABLETOOLS_DIR)
        self.worker.line.connect(self._append_log)
        self.worker.status.connect(self.status_label.setText)
        self.worker.finished.connect(self._finish_worker)
        self.worker.start()

    def _append_log(self, line: str) -> None:
        self.log.appendPlainText(line)

    def _finish_worker(self, code: int) -> None:
        self.status_label.setText("Done" if code == 0 else f"Failed ({code})")
        self.run_full_btn.setEnabled(True)
        self.run_targeted_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if self._scan_movie:
            self._scan_movie.stop()
        self._stop_matrix()

    def _cancel(self) -> None:
        if self.worker:
            self.worker.stop()
            self.status_label.setText("Cancelling...")

    def _start_matrix(self) -> None:
        if self._matrix_timer.isActive():
            return
        self._matrix.setVisible(True)
        self._tick_matrix()
        self._matrix_timer.start()

    def _stop_matrix(self) -> None:
        if self._matrix_timer.isActive():
            self._matrix_timer.stop()
        self._matrix.clear()
        self._matrix.setVisible(False)

    def _tick_matrix(self) -> None:
        chars = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        lines = []
        for _ in range(self._matrix_lines):
            line = "".join(random.choice(chars) for _ in range(self._matrix_cols))
            lines.append(line)
        self._matrix.setText("\n".join(lines))


class CatalogView(QWidget):
    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = _vbox(self)
        _panel_margins(layout)
        self._build_title(layout)
        self._build_controls(layout)
        _section_gap(layout)
        self._build_content(layout)
        self._apply_control_sizes()

    def _build_title(self, layout: QVBoxLayout) -> None:
        title_row = _hbox()
        title = _section_title("Catalog")
        title_row.addWidget(title)
        title_row.addStretch(1)
        layout.addLayout(title_row)

    def _control_label(self, text: str, buddy: QWidget | None = None) -> QLabel:
        label = _label(text)
        label.setObjectName("FieldLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        label.setFixedHeight(CONTROL_ROW_HEIGHT)
        if buddy is not None:
            label.setBuddy(buddy)
        return label

    def _build_controls(self, layout: QVBoxLayout) -> None:
        filters_label = _label("Filters", "FilterLabel")
        filters_label.setObjectName("FilterLabel")
        filters_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        filters_label.setFixedHeight(CONTROL_ROW_HEIGHT)
        filter_gap = _hgap(FILTER_LABEL_GAP)
        self.missing_cb = _checkbox("Missing refs", name="CatalogFilterMissing")
        self.devices_cb = _checkbox("Has devices", name="CatalogFilterDevices")
        self.samples_cb = _checkbox("Has samples", name="CatalogFilterSamples")
        self.backups_cb = _checkbox("Show backups", name="CatalogFilterBackups")
        for cb in [self.missing_cb, self.devices_cb, self.samples_cb, self.backups_cb]:
            cb.stateChanged.connect(self.refresh)
            cb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            cb.setFixedHeight(CONTROL_ROW_HEIGHT)
        filters_row = _checkbox_row(
            self.missing_cb, self.devices_cb, self.samples_cb, self.backups_cb
        )

        self.scope_combo = _combo(
            ["live_recordings", "user_library", "preferences", "all"],
            name="CatalogScope",
        )
        self.scope_combo.currentTextChanged.connect(self.refresh)
        _set_combo_width(self.scope_combo, padding=48)

        self.search_edit = _line_edit(placeholder="Search path or source", name="CatalogSearch")

        self.search_btn = _button("Search", primary=True)
        self.search_btn.setObjectName("CatalogSearchBtn")
        self.search_btn.clicked.connect(self.refresh)
        self.reset_btn = _button("Reset")
        self.reset_btn.setObjectName("CatalogResetBtn")
        self.reset_btn.clicked.connect(self._reset)

        scope_label = self._control_label("Scope", buddy=self.scope_combo)
        scope_label.setObjectName("CatalogScopeLabel")
        search_label = self._control_label("Search", buddy=self.search_edit)
        search_label.setObjectName("CatalogSearchLabel")
        controls_bar = _controls_bar(
            filters_label,
            filter_gap,
            filters_row,
            _hgap(SPACE_ROW),
            scope_label,
            self.scope_combo,
            search_label,
            self.search_edit,
            self.search_btn,
            self.reset_btn,
            stretch=True,
        )
        layout.addWidget(controls_bar)

    def _build_content(self, layout: QVBoxLayout) -> None:
        content_row = _hbox()

        summary_box, summary_layout = _group_box("Summary")
        summary_box.setObjectName("SummaryBox")
        summary_layout.setSpacing(SPACE_TIGHT)
        self.table = _table(10, selection_mode=QTableWidget.SelectionMode.SingleSelection, name="SummaryTable")
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.itemSelectionChanged.connect(self._update_detail)
        summary_layout.addWidget(self.table)
        content_row.addWidget(summary_box, 4)

        detail_box, detail_outer = _group_box("Details")
        detail_box.setObjectName("DetailsBox")
        detail_box.setMinimumWidth(360)
        detail_box.setMaximumWidth(420)
        detail_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        detail_outer.setSpacing(SPACE_PANEL)

        detail_scroll = _scroll_area()
        detail_outer.addWidget(detail_scroll)

        detail_container = QWidget()
        detail_layout = QFormLayout(detail_container)
        detail_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        detail_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.detail_labels: dict[str, QLabel] = {}
        for key in [
            "Name",
            "Path",
            "Scope",
            "Modified",
            "Size",
            "Ext",
            "Tracks",
            "Clips",
            "Devices",
            "Samples",
            "Missing",
            "Targeted",
        ]:
            value_label = _label("-")
            value_label.setWordWrap(True)
            value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.detail_labels[key] = value_label
            key_label = _field_label(key)
            key_label.setFixedWidth(DETAIL_LABEL_WIDTH)
            detail_layout.addRow(key_label, value_label)
        detail_scroll.setWidget(detail_container)

        self.open_path_btn = _button("Open in Finder")
        self.open_path_btn.clicked.connect(self._open_in_finder)
        self.copy_path_btn = _button("Copy Path")
        self.copy_path_btn.clicked.connect(self._copy_path)
        self.run_targeted_btn = _button("Target Scan", primary=True)
        self.run_targeted_btn.clicked.connect(self._run_targeted_for_selected)
        action_bar = _boxed_row(
            self.open_path_btn,
            self.copy_path_btn,
            self.run_targeted_btn,
            align="center",
            top=SPACE_TIGHT,
            bottom=SPACE_TIGHT,
        )
        detail_outer.addWidget(action_bar)
        content_row.addWidget(detail_box, 2)
        layout.addLayout(content_row)

    def _apply_control_sizes(self) -> None:
        self.search_edit.setFixedWidth(240)
        self.search_edit.setFixedHeight(22)
        self.scope_combo.setFixedHeight(22)
        self.search_btn.setFixedHeight(24)
        self.reset_btn.setFixedHeight(24)
        self.scope_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.search_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _reset(self) -> None:
        self.search_edit.setText("")
        self.missing_cb.setChecked(False)
        self.devices_cb.setChecked(False)
        self.samples_cb.setChecked(False)
        self.backups_cb.setChecked(False)
        self.refresh()

    def refresh(self) -> None:
        scope = self.scope_combo.currentText() or "live_recordings"
        term = self.search_edit.text().strip()
        rows = self.catalog.query_catalog(
            scope=scope,
            term=term,
            filter_missing=self.missing_cb.isChecked(),
            filter_devices=self.devices_cb.isChecked(),
            filter_samples=self.samples_cb.isChecked(),
            show_backups=self.backups_cb.isChecked(),
        )

        if scope == "preferences":
            self.table.setSortingEnabled(False)
            headers = ["Kind", "Source", "Modified"]
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            self.table.setRowCount(len(rows))
            for row_idx, row in enumerate(rows):
                values = [row.get("kind", ""), row.get("source", ""), row.get("mtime", "")]
                for col_idx, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row_idx, col_idx, item)
        else:
            headers = [
                "Name",
                "Modified",
                "Size",
                "Tracks",
                "Clips",
                "Devices",
                "Samples",
                "Missing",
                "Targeted",
                "Ext",
                "Scope",
            ]
            self.table.setSortingEnabled(False)
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            for col_idx in range(len(headers)):
                header_item = self.table.horizontalHeaderItem(col_idx)
                if not header_item:
                    continue
                if col_idx == 0:
                    header_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                else:
                    header_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
            self.table.setRowCount(len(rows))
            for row_idx, row in enumerate(rows):
                values = [
                    row.get("name", ""),
                    row.get("mtime", ""),
                    row.get("size", ""),
                    row.get("tracks", ""),
                    row.get("clips", ""),
                    row.get("devices", ""),
                    row.get("samples", ""),
                    row.get("missing", ""),
                    row.get("targeted", ""),
                    row.get("ext", ""),
                    row.get("scope", ""),
                ]
                for col_idx, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col_idx == 0:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                        )
                    else:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.table.setItem(row_idx, col_idx, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self._current_rows = rows
        self._update_detail()

    def _update_detail(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if not selected or not getattr(self, "_current_rows", None):
            for label in self.detail_labels.values():
                label.setText("-")
            return
        row = self._current_rows[selected[0].row()]
        self._set_detail_value("Name", row.get("name", row.get("kind", "-")))
        self._set_detail_value("Path", row.get("path_full", row.get("source", "-")))
        self._set_detail_value("Scope", row.get("scope", "-"))
        self._set_detail_value("Modified", row.get("mtime", "-"))
        self._set_detail_value("Size", row.get("size", "-"))
        self._set_detail_value("Ext", row.get("ext", "-"))
        self._set_detail_value("Tracks", row.get("tracks", "-"))
        self._set_detail_value("Clips", row.get("clips", "-"))
        self._set_detail_value("Devices", row.get("devices", "-"))
        self._set_detail_value("Samples", row.get("samples", "-"))
        self._set_detail_value("Missing", row.get("missing", "-"))
        self._set_detail_value("Targeted", row.get("targeted", "-"))

    def _set_detail_value(self, key: str, value: str) -> None:
        label = self.detail_labels.get(key)
        if not label:
            return
        text = value or "-"
        label.setText(text)
        label.setToolTip(text)

    def _open_in_finder(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if not selected or not getattr(self, "_current_rows", None):
            return
        row = self._current_rows[selected[0].row()]
        path = row.get("path_full")
        if not path:
            return
        open_in_finder(path)

    def _copy_path(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if not selected or not getattr(self, "_current_rows", None):
            return
        row = self._current_rows[selected[0].row()]
        path = row.get("path_full")
        if not path:
            return
        QApplication.clipboard().setText(path)

    def _run_targeted_for_selected(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if not selected or not getattr(self, "_current_rows", None):
            QMessageBox.information(self, "Targeted Scan", "Select a set first.")
            return
        row = self._current_rows[selected[0].row()]
        scope = row.get("scope", "live_recordings")
        path = row.get("path_full")
        if not path:
            QMessageBox.information(self, "Targeted Scan", "No path available for selection.")
            return
        proc = run_targeted_scan(path, scope, self.catalog.catalog_dir)
        if proc.returncode != 0:
            QMessageBox.warning(self, "Targeted Scan", proc.stderr.strip() or "Scan failed.")
            return
        QMessageBox.information(self, "Targeted Scan", "Targeted scan completed.")


class PreferencesView(QWidget):
    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self.show_raw = False
        self.sources: list[tuple[str, str, int]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = _vbox(self)
        _panel_margins(layout)

        header = _hbox()
        title = _section_title("Preferences")
        header.addWidget(title)
        header.addStretch(1)
        self.show_raw_cb = _checkbox("Show raw")
        self.show_raw_cb.stateChanged.connect(self.refresh)
        header.addWidget(self.show_raw_cb)
        refresh_btn = _button("Refresh", primary=True)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)
        _section_gap(layout)

        content_row = _hbox()
        sources_box, sources_layout = _group_box("Sources")
        sources_layout.addWidget(
            _label("Select a source to view the parsed summary and preview.", "HintText")
        )
        self.source_list = _list()
        self.source_list.setMinimumWidth(300)
        self.source_list.currentRowChanged.connect(self._on_select)
        sources_layout.addWidget(self.source_list)
        content_row.addWidget(sources_box, 2)

        right = _vbox()
        summary_box, detail_layout = _group_box("Selected Summary", kind="form")
        detail_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.detail_labels: dict[str, QLabel] = {}
        for key in ["Kind", "Source", "Modified", "Keys", "Lines", "Options", "Value keys"]:
            value_label = _label("-")
            value_label.setWordWrap(True)
            value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.detail_labels[key] = value_label
            key_label = _field_label(key)
            key_label.setFixedWidth(DETAIL_LABEL_WIDTH)
            detail_layout.addRow(key_label, value_label)
        right.addWidget(summary_box)
        right.addSpacing(SPACE_PANEL)

        payload_box, payload_layout = _group_box("Preview")
        self.payload = _plain_text(QFont("Menlo", 11))
        self.payload.setReadOnly(True)
        payload_layout.addWidget(self.payload)
        right.addWidget(payload_box, 3)
        content_row.addLayout(right, 5)
        layout.addLayout(content_row)

    def refresh(self) -> None:
        self.sources = self.catalog.get_pref_sources()
        self.source_list.clear()
        for kind, source, _ in self.sources:
            self.source_list.addItem(f"{kind} | {source}")
        if self.sources:
            self.source_list.setCurrentRow(0)
        else:
            self.payload.setPlainText("No preferences loaded.")

    def _on_select(self, index: int) -> None:
        if index < 0 or index >= len(self.sources):
            return
        kind, source, mtime = self.sources[index]
        payload_text = self.catalog.get_pref_payload(kind, source)
        if payload_text is None:
            self.payload.setPlainText("No payload found.")
            return
        if self.show_raw_cb.isChecked():
            limit = 20000
            text = payload_text
            if len(text) > limit:
                text = text[:limit] + "\n\n... (truncated)"
            self.payload.setPlainText(text)
            self._set_detail(kind, source, mtime, {})
            return
        try:
            payload = json.loads(payload_text)
        except Exception as exc:
            self.payload.setPlainText(f"Failed to parse JSON: {exc}")
            return
        self.payload.setPlainText(self._summarize_payload(kind, source, payload))
        self._set_detail(kind, source, mtime, payload)

    def _set_detail(self, kind: str, source: str, mtime: int, payload: dict) -> None:
        keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        values = payload.get("values") if isinstance(payload, dict) else {}
        lines = payload.get("lines") if isinstance(payload, dict) else []
        options = payload.get("options") if isinstance(payload, dict) else []
        self.detail_labels["Kind"].setText(kind)
        self.detail_labels["Source"].setText(source)
        self.detail_labels["Modified"].setText(format_mtime(mtime))
        self.detail_labels["Keys"].setText(", ".join(keys)[:140])
        self.detail_labels["Lines"].setText(str(len(lines)) if isinstance(lines, list) else "-")
        self.detail_labels["Options"].setText(
            str(len(options)) if isinstance(options, list) else "-"
        )
        self.detail_labels["Value keys"].setText(
            str(len(values)) if isinstance(values, dict) else "-"
        )

    def _summarize_payload(self, kind: str, source: str, payload: dict) -> str:
        lines = [f"Kind: {kind}", f"Source: {source}"]
        if isinstance(payload, dict):
            lines.append(f"Keys: {', '.join(sorted(payload.keys()))}")
            if "lines" in payload and isinstance(payload["lines"], list):
                lines.append(f"Lines: {len(payload['lines'])}")
            if "options" in payload and isinstance(payload["options"], list):
                lines.append(f"Options: {len(payload['options'])}")
            if "values" in payload and isinstance(payload["values"], dict):
                values = payload["values"]
                lines.append(f"Value keys: {len(values)}")
        return "\n".join(lines)


class ToolsView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._worker: Optional[RamifyWorker] = None
        self._build_ui()
        self._log("Ready. Tip: start with Dry run.")

    def _build_ui(self) -> None:
        layout = _vbox(self)
        _panel_margins(layout)

        header = _hbox()
        title = _section_title("Tools")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)
        _section_gap(layout)

        group, group_layout = _group_box("RAMify Ableton Sets")
        group_layout.addWidget(_label("Flip AudioClip RAM flags for faster playback."))

        target_row = _hbox()
        self.path_edit = _line_edit()
        target_row.addWidget(self.path_edit)
        file_btn = _button("Choose File")
        file_btn.clicked.connect(self._choose_file)
        target_row.addWidget(file_btn)
        folder_btn = _button("Choose Folder")
        folder_btn.clicked.connect(self._choose_folder)
        target_row.addWidget(folder_btn)
        group_layout.addLayout(target_row)

        self.dry_cb = _checkbox("Dry run (no writes)")
        self.dry_cb.setChecked(True)
        self.inplace_cb = _checkbox("In-place (create .bak)")
        self.inplace_cb.setChecked(True)
        self.recursive_cb = _checkbox("Recursive (if folder)")
        options_row = _checkbox_row(self.dry_cb, self.inplace_cb, self.recursive_cb)
        group_layout.addWidget(options_row)
        group_layout.addSpacing(SPACE_PANEL)

        self.run_btn = _button("Run RAMify", primary=True)
        self.run_btn.clicked.connect(self._run)
        clear_btn = _button("Clear Log")
        clear_btn.clicked.connect(self._clear_log)
        actions = _boxed_row(self.run_btn, clear_btn, align="left")
        group_layout.addWidget(actions)
        group_layout.addSpacing(SPACE_PANEL)

        self.log = _plain_text(QFont("Menlo", 11))
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(240)
        group_layout.addWidget(self.log)

        layout.addWidget(group)
        layout.addStretch(1)

    def _log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _clear_log(self) -> None:
        self.log.clear()

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Ableton set/clip",
            "",
            "Ableton Live (*.als *.alc);;All files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose folder containing .als/.alc files"
        )
        if path:
            self.path_edit.setText(path)

    def _run(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Missing target", "Choose a file or folder first.")
            return
        target = Path(path).expanduser()
        if not target.exists():
            QMessageBox.warning(self, "Not found", str(target))
            return
        self.run_btn.setEnabled(False)
        self._log("")
        mode = "DRY RUN" if self.dry_cb.isChecked() else (
            "IN-PLACE" if self.inplace_cb.isChecked() else "WRITE .ram.* COPIES"
        )
        self._log(f"=== Running: {mode} ===")
        self._log(f"Target: {target}")
        self._log(f"Recursive: {self.recursive_cb.isChecked()}")
        self._log("")
        worker = RamifyWorker(
            target,
            dry=self.dry_cb.isChecked(),
            inplace=self.inplace_cb.isChecked(),
            recursive=self.recursive_cb.isChecked(),
        )
        worker.output.connect(self._log)
        worker.finished.connect(self._finish)
        self._worker = worker
        worker.start()

    def _finish(self) -> None:
        self.run_btn.setEnabled(True)


class SettingsView(QWidget):
    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self._worker: Optional[CommandWorker] = None
        self._build_ui()

    def _run_analytics(self) -> None:
        db_path = ABLETOOLS_DIR / ".abletools_catalog" / "abletools_catalog.sqlite"
        script = ABLETOOLS_DIR / "abletools_analytics.py"
        if not db_path.exists():
            QMessageBox.information(self, "Analytics", "No database found yet.")
            return
        self._start_command([sys.executable, str(script), str(db_path)])

    def _audit_missing(self) -> None:
        db_path = ABLETOOLS_DIR / ".abletools_catalog" / "abletools_catalog.sqlite"
        script = ABLETOOLS_DIR / "abletools_maintenance.py"
        if not db_path.exists():
            QMessageBox.information(self, "Audit", "No database found yet.")
            return
        self._start_command([sys.executable, str(script), str(db_path), "--audit-missing"])

    def _audit_zero_tracks(self) -> None:
        db_path = self.catalog.catalog_dir / "abletools_catalog.sqlite"
        if not db_path.exists():
            QMessageBox.information(self, "Audit", "No database found yet.")
            return
        self.output.clear()
        worker = AuditWorker(self.catalog)
        worker.output.connect(self._append_output)
        worker.finished.connect(self._finish_command)
        self._worker = worker
        self._toggle_buttons(False)
        worker.start()

    def _optimize_db(self) -> None:
        db_path = ABLETOOLS_DIR / ".abletools_catalog" / "abletools_catalog.sqlite"
        script = ABLETOOLS_DIR / "abletools_maintenance.py"
        if not db_path.exists():
            QMessageBox.information(self, "Maintenance", "No database found yet.")
            return
        self._start_command(
            [sys.executable, str(script), str(db_path), "--analyze", "--optimize"]
        )

    def _start_command(self, cmd: list[str]) -> None:
        self.output.clear()
        worker = CommandWorker(cmd, ABLETOOLS_DIR)
        worker.output.connect(self._append_output)
        worker.finished.connect(self._finish_command)
        self._worker = worker
        self._toggle_buttons(False)
        worker.start()

    def _append_output(self, text: str) -> None:
        if text:
            self.output.appendPlainText(text)

    def _finish_command(self, code: int) -> None:
        self._append_output(f"Done (exit={code}).")
        self._toggle_buttons(True)

    def _toggle_buttons(self, enabled: bool) -> None:
        self.analytics_btn.setEnabled(enabled)
        self.audit_btn.setEnabled(enabled)
        self.audit_zero_btn.setEnabled(enabled)
        self.optimize_btn.setEnabled(enabled)

    def _build_ui(self) -> None:
        layout = _vbox(self)
        _panel_margins(layout)

        header = _hbox()
        title = _section_title("Settings")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)
        _section_gap(layout)

        group, group_layout = _group_box("Maintenance")
        self.analytics_btn = _button("Run Analytics", primary=True)
        self.analytics_btn.clicked.connect(self._run_analytics)
        self.audit_btn = _button("Audit Missing")
        self.audit_btn.clicked.connect(self._audit_missing)
        self.audit_zero_btn = _button("Audit Zero Tracks")
        self.audit_zero_btn.clicked.connect(self._audit_zero_tracks)
        self.optimize_btn = _button("Optimize DB")
        self.optimize_btn.clicked.connect(self._optimize_db)
        button_row = _action_row(
            self.analytics_btn,
            self.audit_btn,
            self.audit_zero_btn,
            self.optimize_btn,
            align="left",
        )
        group_layout.addWidget(button_row)
        layout.addWidget(group)
        _section_gap(layout)

        self.output = _plain_text(QFont("Menlo", 11))
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        layout.addStretch(1)


class PlaceholderView(QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        layout = _vbox(self)
        layout.addWidget(_label(label))
        layout.addStretch(1)


class GridOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("GridOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._pixmap = _svg_pixmap(ABLETOOLS_DIR / "resources" / "grid_overlay.svg", 128)

    def paintEvent(self, event) -> None:
        from PyQt6.QtGui import QPainter

        painter = QPainter(self)
        painter.setOpacity(0.12)
        if not self._pixmap.isNull():
            painter.drawTiledPixmap(self.rect(), self._pixmap)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == event.Type.Resize:
            self.resize(watched.size())
        return super().eventFilter(watched, event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Abletools (PyQt)")
        self.resize(1512, 1008)

        catalog = CatalogService(ABLETOOLS_DIR / ".abletools_catalog")

        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = _vbox(root)
        root_layout.setContentsMargins(
            ROOT_MARGIN_X, ROOT_MARGIN_TOP, ROOT_MARGIN_X, ROOT_MARGIN_BOTTOM
        )
        header = _header_bar()
        root_layout.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(DashboardView(catalog), "Dashboard")
        tabs.addTab(ScanView(catalog), "Scan")
        tabs.addTab(CatalogView(catalog), "Catalog")
        tabs.addTab(InsightsView(catalog), "Insights")
        tabs.addTab(ToolsView(), "Tools")
        tabs.addTab(PreferencesView(catalog), "Preferences")
        tabs.addTab(SettingsView(catalog), "Settings")
        root_layout.addWidget(tabs)

        overlay = GridOverlay(root)
        overlay.lower()
        overlay.resize(root.size())
        root.installEventFilter(overlay)
        self.setCentralWidget(root)


def _boxed(title: str, widget: QWidget) -> QGroupBox:
    box, layout = _group_box(title)
    layout.addWidget(widget)
    return box


def _dedupe_targeted(items: list[dict[str, str]]) -> list[dict[str, str]]:
    scope_priority = {"live_recordings": 0, "user_library": 1}
    by_path: dict[str, dict[str, str]] = {}
    for item in items:
        path_value = str(item.get("path", ""))
        if not path_value:
            continue
        existing = by_path.get(path_value)
        if not existing:
            by_path[path_value] = item
            continue
        existing_scope = existing.get("scope", "")
        incoming_scope = item.get("scope", "")
        existing_rank = scope_priority.get(existing_scope, 99)
        incoming_rank = scope_priority.get(incoming_scope, 99)
        if incoming_rank < existing_rank:
            by_path[path_value] = item
            continue
        if incoming_rank == existing_rank:
            try:
                existing_mtime = int(existing.get("mtime") or 0)
                incoming_mtime = int(item.get("mtime") or 0)
            except Exception:
                existing_mtime = 0
                incoming_mtime = 0
            if incoming_mtime > existing_mtime:
                by_path[path_value] = item
    return sorted(
        by_path.values(),
        key=lambda item: (-int(item.get("mtime") or 0), str(item.get("name", "")).lower()),
    )


def _header_bar() -> QWidget:
    bar = QWidget()
    bar.setObjectName("HeaderBar")
    layout = _hbox(bar)
    layout.setContentsMargins(HEADER_MARGIN_X, HEADER_MARGIN_Y, HEADER_MARGIN_X, HEADER_MARGIN_Y)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    brand = QWidget()
    brand_layout = _hbox(brand)
    brand_layout.setContentsMargins(0, 0, 0, 0)
    brand_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    logo_path = ABLETOOLS_DIR / "resources" / "abletools_mark.svg"
    if logo_path.exists():
        logo = _image_label()
        logo.setObjectName("HeaderLogo")
        logo.setPixmap(_svg_pixmap(logo_path, HEADER_LOGO_SIZE))
        logo.setFixedSize(HEADER_LOGO_SIZE, HEADER_LOGO_SIZE)
        logo.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        brand_layout.addWidget(logo)

    title = _label("Abletools", "appTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    title.setFixedHeight(HEADER_LOGO_SIZE)
    brand_layout.addWidget(title)

    layout.addWidget(brand)
    layout.addStretch(1)
    return bar


def _pixmap(path: Path, size: int) -> "QPixmap":
    from PyQt6.QtGui import QPixmap

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def _svg_pixmap(path: Path, size: int) -> "QPixmap":
    from PyQt6.QtGui import QPainter, QPixmap
    from PyQt6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(path))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def apply_theme(app: QApplication) -> None:
    from PyQt6.QtGui import QFont, QPalette, QColor, QIcon

    app.setFont(QFont("Avenir Next", 11))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#05070b"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e6f1ff"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0c121b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#121b26"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e6f1ff"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#121b26"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e6f1ff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#19f5c8"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#001014"))
    app.setPalette(palette)

    icon_path = ABLETOOLS_DIR / "resources" / "abletools_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    tokens = {
        "PRIMARY_ACCENT": "#19f5c8",
        "PRIMARY_ACCENT_HOVER": "#38f7d6",
        "PRIMARY_TEXT": "#e6f1ff",
        "PRIMARY_TEXT_DARK": "#001014",
        "MUTED_TEXT": "#9bb3c9",
        "PANEL_BG": "#122033",
        "INPUT_BG": "#0f1826",
        "TAB_BG": "#0c121b",
        "TAB_SELECTED_BG": "#121b26",
        "BUTTON_BG": "#121b26",
        "BUTTON_HOVER_BG": "#1b2736",
        "BORDER": "#3a6f98",
        "BORDER_HOVER": "#4b86b3",
        "APP_BG_0": "#04060a",
        "APP_BG_1": "#070b12",
        "APP_BG_2": "#0b1320",
    }
    theme_path = ABLETOOLS_DIR / "resources" / "theme.qss"
    if theme_path.exists():
        raw_qss = theme_path.read_text(encoding="utf-8")
        qss = Template(raw_qss).safe_substitute(tokens)
        app.setStyleSheet(qss)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
