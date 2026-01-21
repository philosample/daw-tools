from __future__ import annotations

import json
import random
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

from abletools_catalog_ops import backup_files, cleanup_catalog_dir
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


def _set_combo_width(combo: QComboBox, padding: int = 28, minimum: int | None = None) -> None:
    metrics = QFontMetrics(combo.font())
    widest = 0
    for idx in range(combo.count()):
        widest = max(widest, metrics.horizontalAdvance(combo.itemText(idx)))
    width = widest + padding
    if minimum is not None:
        width = max(width, minimum)
    combo.setFixedWidth(width)


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

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.setContentsMargins(0, 0, 0, 0)
        header.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(self._refresh_table)
        header.addWidget(self.search_edit)
        self.ignore_backups = QCheckBox("Ignore backups")
        self.ignore_backups.setChecked(self._ignore_backups)
        self.ignore_backups.stateChanged.connect(self._refresh_table)
        header.addWidget(self.ignore_backups)
        layout.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Scope", "Name", "Path", "Modified", "Tracks", "Clips"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.apply_btn = QPushButton("Use Selected")
        self.apply_btn.clicked.connect(self.accept)
        footer.addWidget(self.apply_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)
        layout.addLayout(footer)

        self._refresh_table()

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
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["live_recordings", "user_library"])
        self.scope_combo.currentTextChanged.connect(self.refresh)
        _set_combo_width(self.scope_combo, padding=26)
        header.addWidget(self.scope_combo)
        header.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("Primary")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        self.card_sets_value, self.card_sets_sub = self._stat_card(cards, "Total Sets", 0)
        self.card_set_size_value, _ = self._stat_card(cards, "Set Size", 1)
        self.card_audio_size_value, _ = self._stat_card(cards, "Audio Size", 2)
        self.card_missing_value, _ = self._stat_card(cards, "Sets Missing Refs", 3)
        layout.addLayout(cards)

        activity_box = QGroupBox("Catalog Status")
        activity_layout = QVBoxLayout(activity_box)
        self.activity_text = QPlainTextEdit()
        self.activity_text.setReadOnly(True)
        self.activity_text.setFont(QFont("Menlo", 11))
        activity_layout.addWidget(self.activity_text)
        layout.addWidget(activity_box)

        backup_box = QGroupBox("Backups")
        backup_layout = QHBoxLayout(backup_box)
        backup_sets = QPushButton("Backup Sets")
        backup_sets.setObjectName("Primary")
        backup_sets.clicked.connect(self._backup_sets)
        backup_layout.addWidget(backup_sets)
        backup_audio = QPushButton("Backup Audio")
        backup_audio.clicked.connect(self._backup_audio)
        backup_layout.addWidget(backup_audio)
        cleanup_btn = QPushButton("Clean Catalog")
        cleanup_btn.clicked.connect(self._cleanup_catalog)
        backup_layout.addWidget(cleanup_btn)
        backup_layout.addStretch(1)
        layout.addWidget(backup_box)

        lists_layout = QGridLayout()
        lists_layout.setHorizontalSpacing(12)
        lists_layout.setVerticalSpacing(12)
        self.top_devices = QPlainTextEdit()
        self.top_plugins = QPlainTextEdit()
        self.top_chains = QPlainTextEdit()
        self.top_missing = QPlainTextEdit()
        for widget in [self.top_devices, self.top_plugins, self.top_chains, self.top_missing]:
            widget.setReadOnly(True)
            widget.setFont(QFont("Menlo", 11))
            widget.setMaximumHeight(140)

        lists_layout.addWidget(_boxed("Top Devices", self.top_devices), 0, 0)
        lists_layout.addWidget(_boxed("Top Plugins", self.top_plugins), 0, 1)
        lists_layout.addWidget(_boxed("Top Chains", self.top_chains), 1, 0)
        lists_layout.addWidget(_boxed("Missing Ref Hotspots", self.top_missing), 1, 1)
        layout.addLayout(lists_layout)
        layout.addStretch(1)

        self.refresh()

    def _stat_card(self, layout: QGridLayout, title: str, col: int) -> tuple[QLabel, QLabel]:
        box = QGroupBox(title)
        box_layout = QVBoxLayout(box)
        value = QLabel("-")
        value.setObjectName("StatValue")
        sub = QLabel("")
        sub.setObjectName("StatSub")
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
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select items to remove from .abletools_catalog"))

        options = {
            "logs": QCheckBox("Old scan logs + audit reports"),
            "xml_nodes": QCheckBox("XML nodes JSONL (large)"),
            "device_params": QCheckBox("Device params JSONL (large)"),
            "refs_graph": QCheckBox("Refs graph JSONL"),
            "struct": QCheckBox("Struct/clip/routing JSONL"),
            "scan_state": QCheckBox("Scan + dir state (incremental cache)"),
        }
        defaults = {"logs": True, "xml_nodes": True, "device_params": True}
        for key, checkbox in options.items():
            checkbox.setChecked(defaults.get(key, False))
            layout.addWidget(checkbox)

        optimize_cb = QCheckBox("Optimize DB after cleanup (ANALYZE + VACUUM)")
        optimize_cb.setChecked(True)
        rebuild_cb = QCheckBox("Rebuild DB from remaining JSONL (overwrite)")
        layout.addWidget(optimize_cb)
        layout.addWidget(rebuild_cb)

        btns = QHBoxLayout()
        run_btn = QPushButton("Clean")
        run_btn.setObjectName("Primary")
        cancel_btn = QPushButton("Cancel")
        btns.addWidget(run_btn)
        btns.addWidget(cancel_btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        def _run() -> None:
            selected = {k: v.isChecked() for k, v in options.items()}
            removed, bytes_freed = cleanup_catalog_dir(self.catalog.catalog_dir, selected)
            maintenance_msg = ""
            if rebuild_cb.isChecked():
                script = ABLETOOLS_DIR / "abletools_catalog_db.py"
                proc = subprocess.run(
                    [sys.executable, str(script), str(self.catalog.catalog_dir), "--overwrite", "--vacuum"],
                    cwd=str(ABLETOOLS_DIR),
                    capture_output=True,
                    text=True,
                )
                maintenance_msg = " Rebuilt DB." if proc.returncode == 0 else f" Rebuild failed: {proc.stderr.strip()}"
            elif optimize_cb.isChecked():
                script = ABLETOOLS_DIR / "abletools_maintenance.py"
                proc = subprocess.run(
                    [sys.executable, str(script), str(self.catalog.catalog_dir / "abletools_catalog.sqlite"), "--analyze", "--optimize", "--vacuum"],
                    cwd=str(ABLETOOLS_DIR),
                    capture_output=True,
                    text=True,
                )
                maintenance_msg = " Optimized DB." if proc.returncode == 0 else f" Optimize failed: {proc.stderr.strip()}"
            QMessageBox.information(
                self,
                "Clean Catalog",
                f"Removed {removed} files, freed {format_bytes(bytes_freed)}.{maintenance_msg}",
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
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Insights")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("Primary")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["live_recordings", "user_library", "preferences"])
        self.scope_combo.currentTextChanged.connect(self.refresh)
        layout.addWidget(self.scope_combo)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Menlo", 11))
        layout.addWidget(self.text)

        self.refresh()

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

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Scan")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        root_row = QHBoxLayout()
        root_row.setSpacing(8)
        root_row.addWidget(QLabel("Root folder:"))
        self.root_edit = QLineEdit(str(self._default_root()))
        root_row.addWidget(self.root_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_root)
        root_row.addWidget(browse_btn)
        layout.addLayout(root_row)

        scope_row = QHBoxLayout()
        scope_row.setSpacing(8)
        scope_row.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["live_recordings", "user_library", "preferences", "all"])
        scope_row.addWidget(self.scope_combo)
        scope_row.addStretch(1)
        layout.addLayout(scope_row)

        full_group = QGroupBox("Full Scan")
        full_layout = QGridLayout(full_group)
        full_layout.setHorizontalSpacing(12)
        full_layout.setVerticalSpacing(8)
        self.incremental_cb = QCheckBox("Incremental (skip unchanged)")
        self.include_media_cb = QCheckBox("Include media files")
        self.hash_cb = QCheckBox("Compute hashes")
        self.analyze_audio_cb = QCheckBox("Analyze audio")
        self.include_backups_cb = QCheckBox("Include Backup folders")
        self.changed_only_cb = QCheckBox("Changed-only scan")
        self.checkpoint_cb = QCheckBox("Write checkpoints")
        self.resume_cb = QCheckBox("Resume checkpoint")
        self.rehash_cb = QCheckBox("Rehash unchanged")
        self.hash_docs_cb = QCheckBox("Hash Ableton sets only")
        self.full_advanced_toggle = QCheckBox("Advanced options")
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
        full_adv_layout = QGridLayout(self.full_advanced_box)
        full_adv_layout.setContentsMargins(0, 0, 0, 0)
        full_adv_layout.setHorizontalSpacing(12)
        full_adv_layout.setVerticalSpacing(8)
        full_adv_layout.addWidget(self.include_backups_cb, 0, 0)
        full_adv_layout.addWidget(self.changed_only_cb, 0, 1)
        full_adv_layout.addWidget(self.checkpoint_cb, 0, 2)
        full_adv_layout.addWidget(self.resume_cb, 0, 3)
        full_adv_layout.addWidget(self.rehash_cb, 1, 0)
        full_adv_layout.addWidget(self.hash_docs_cb, 1, 1)
        self.full_advanced_box.setVisible(False)
        self.full_advanced_toggle.toggled.connect(self.full_advanced_box.setVisible)
        full_layout.addWidget(self.full_advanced_box, 2, 0, 1, 4)
        layout.addWidget(full_group)

        targeted_group = QGroupBox("Targeted Scan")
        targeted_layout = QGridLayout(targeted_group)
        targeted_layout.setHorizontalSpacing(12)
        targeted_layout.setVerticalSpacing(8)
        select_btn = QPushButton("Select Sets")
        select_btn.setObjectName("Primary")
        select_btn.clicked.connect(self._select_sets)
        targeted_layout.addWidget(select_btn, 0, 0)
        self.targeted_summary = QLabel("No targeted sets selected.")
        targeted_layout.addWidget(self.targeted_summary, 0, 1, 1, 3)

        self.struct_cb = QCheckBox("Struct")
        self.clips_cb = QCheckBox("Clips")
        self.devices_cb = QCheckBox("Devices")
        self.routing_cb = QCheckBox("Routing")
        self.refs_cb = QCheckBox("Refs")
        for cb in [self.struct_cb, self.clips_cb, self.devices_cb, self.routing_cb, self.refs_cb]:
            cb.setChecked(True)
        targeted_layout.addWidget(self.struct_cb, 1, 0)
        targeted_layout.addWidget(self.clips_cb, 1, 1)
        targeted_layout.addWidget(self.devices_cb, 1, 2)
        targeted_layout.addWidget(self.routing_cb, 1, 3)
        targeted_layout.addWidget(self.refs_cb, 1, 4)

        self.deep_snapshot_cb = QCheckBox("Deep XML snapshot")
        self.xml_nodes_cb = QCheckBox("XML nodes (huge)")
        self.targeted_advanced_toggle = QCheckBox("Advanced options")
        self.targeted_advanced_toggle.setChecked(False)
        targeted_layout.addWidget(self.targeted_advanced_toggle, 2, 0, 1, 2)
        self.targeted_advanced_box = QWidget()
        targeted_adv_layout = QGridLayout(self.targeted_advanced_box)
        targeted_adv_layout.setContentsMargins(0, 0, 0, 0)
        targeted_adv_layout.setHorizontalSpacing(12)
        targeted_adv_layout.setVerticalSpacing(8)
        targeted_adv_layout.addWidget(self.deep_snapshot_cb, 0, 0)
        targeted_adv_layout.addWidget(self.xml_nodes_cb, 0, 1)
        self.targeted_advanced_box.setVisible(False)
        self.targeted_advanced_toggle.toggled.connect(self.targeted_advanced_box.setVisible)
        targeted_layout.addWidget(self.targeted_advanced_box, 3, 0, 1, 4)
        layout.addWidget(targeted_group)

        btn_row = QHBoxLayout()
        self.run_full_btn = QPushButton("Run Full Scan")
        self.run_full_btn.setObjectName("Primary")
        self.run_full_btn.clicked.connect(self._run_full)
        btn_row.addWidget(self.run_full_btn)
        self.run_targeted_btn = QPushButton("Run Targeted")
        self.run_targeted_btn.clicked.connect(self._run_targeted)
        btn_row.addWidget(self.run_targeted_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        self.status_label = QLabel("Idle")
        btn_row.addWidget(self.status_label)
        layout.addLayout(btn_row)

        log_container = QWidget()
        log_stack = QStackedLayout(log_container)
        log_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self._scan_gif = QLabel()
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

        self._matrix = QLabel()
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

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("background-color: rgba(11, 20, 32, 0.72);")
        self.log.setFont(QFont("Menlo", 11))
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_stack.addWidget(self.log)
        layout.addWidget(log_container)

    def _default_root(self) -> Path:
        return self.catalog.catalog_dir.parent

    def _browse_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Root")
        if path:
            self.root_edit.setText(path)

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
        root = Path(self.root_edit.text()).expanduser()
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
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Catalog")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        def _control_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            label.setFixedHeight(36)
            return label

        controls_bar = QWidget()
        controls_row = QHBoxLayout(controls_bar)
        controls_row.setContentsMargins(0, 4, 0, 4)
        controls_row.setSpacing(12)
        controls_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        filters_label = QLabel("Filters")
        filters_label.setObjectName("FilterLabel")
        filters_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        filters_label.setFixedHeight(36)
        controls_row.addWidget(filters_label, 0, Qt.AlignmentFlag.AlignVCenter)
        controls_row.addSpacing(1)
        self.missing_cb = QCheckBox("Missing refs")
        self.missing_cb.setObjectName("CatalogFilterMissing")
        self.devices_cb = QCheckBox("Has devices")
        self.devices_cb.setObjectName("CatalogFilterDevices")
        self.samples_cb = QCheckBox("Has samples")
        self.samples_cb.setObjectName("CatalogFilterSamples")
        self.backups_cb = QCheckBox("Show backups")
        self.backups_cb.setObjectName("CatalogFilterBackups")
        for cb in [self.missing_cb, self.devices_cb, self.samples_cb, self.backups_cb]:
            cb.stateChanged.connect(self.refresh)
            cb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            cb.setFixedHeight(36)
            controls_row.addWidget(cb, 0, Qt.AlignmentFlag.AlignVCenter)
        controls_row.addStretch(1)

        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("CatalogScope")
        self.scope_combo.addItems(["live_recordings", "user_library", "preferences", "all"])
        self.scope_combo.currentTextChanged.connect(self.refresh)
        _set_combo_width(self.scope_combo, padding=26)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("CatalogSearch")
        self.search_edit.setPlaceholderText("Search path or source")

        search_btn = QPushButton("Search")
        search_btn.setObjectName("CatalogSearchBtn")
        search_btn.setObjectName("Primary")
        search_btn.clicked.connect(self.refresh)
        reset_btn = QPushButton("Reset")
        reset_btn.setObjectName("CatalogResetBtn")
        reset_btn.clicked.connect(self._reset)

        scope_label = _control_label("Scope")
        scope_label.setObjectName("CatalogScopeLabel")
        controls_row.addWidget(scope_label, 0, Qt.AlignmentFlag.AlignVCenter)
        controls_row.addWidget(self.scope_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        search_label = _control_label("Search")
        search_label.setObjectName("CatalogSearchLabel")
        controls_row.addWidget(search_label, 0, Qt.AlignmentFlag.AlignVCenter)
        controls_row.addWidget(self.search_edit, 0, Qt.AlignmentFlag.AlignVCenter)
        controls_row.addWidget(search_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        controls_row.addWidget(reset_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(controls_bar)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(12)

        summary_box = QGroupBox("Summary")
        summary_box.setObjectName("SummaryBox")
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setSpacing(8)
        self.table = QTableWidget(0, 10)
        self.table.setObjectName("SummaryTable")
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.itemSelectionChanged.connect(self._update_detail)
        summary_layout.addWidget(self.table)
        content_row.addWidget(summary_box, 4)

        detail_box = QGroupBox("Details")
        detail_box.setObjectName("DetailsBox")
        detail_box.setMinimumWidth(360)
        detail_box.setMaximumWidth(420)
        detail_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        detail_outer = QVBoxLayout(detail_box)
        detail_outer.setContentsMargins(12, 12, 12, 12)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
            label = QLabel("-")
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.detail_labels[key] = label
            detail_layout.addRow(key, label)
        detail_scroll.setWidget(detail_container)

        action_bar = QWidget()
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(0, 8, 0, 0)
        action_layout.addStretch(1)
        self.open_path_btn = QPushButton("Open in Finder")
        self.open_path_btn.clicked.connect(self._open_in_finder)
        action_layout.addWidget(self.open_path_btn)
        self.copy_path_btn = QPushButton("Copy Path")
        self.copy_path_btn.clicked.connect(self._copy_path)
        action_layout.addWidget(self.copy_path_btn)
        self.run_targeted_btn = QPushButton("Target Scan")
        self.run_targeted_btn.setObjectName("Primary")
        self.run_targeted_btn.clicked.connect(self._run_targeted_for_selected)
        action_layout.addWidget(self.run_targeted_btn)
        action_layout.addStretch(1)
        detail_outer.addWidget(action_bar)
        content_row.addWidget(detail_box, 2)
        layout.addLayout(content_row)

        self.search_edit.setFixedWidth(240)
        self.search_edit.setFixedHeight(22)
        self.scope_combo.setFixedHeight(22)
        search_btn.setFixedHeight(24)
        reset_btn.setFixedHeight(24)
        self.scope_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.search_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        search_btn.setFixedHeight(32)
        reset_btn.setFixedHeight(32)

        self.refresh()

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
        subprocess.run(["open", path])

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
        scan_script = ABLETOOLS_DIR / "abletools_scan.py"
        cmd = [
            sys.executable,
            str(scan_script),
            str(path),
            "--scope",
            scope,
            "--mode",
            "targeted",
            "--details",
            "struct,clips,devices,routing,refs",
            "--out",
            str(self.catalog.catalog_dir),
            "--incremental",
            "--progress",
            "--verbose",
        ]
        proc = subprocess.run(cmd, cwd=str(ABLETOOLS_DIR), capture_output=True, text=True)
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
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Preferences")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.show_raw_cb = QCheckBox("Show raw")
        self.show_raw_cb.stateChanged.connect(self.refresh)
        header.addWidget(self.show_raw_cb)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("Primary")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.source_list = QListWidget()
        self.source_list.setMinimumWidth(320)
        self.source_list.currentRowChanged.connect(self._on_select)
        splitter.addWidget(self.source_list)

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        detail_box = QGroupBox("Details")
        detail_layout = QFormLayout(detail_box)
        detail_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.detail_labels: dict[str, QLabel] = {}
        for key in ["Kind", "Source", "Modified", "Keys", "Lines", "Options", "Value keys"]:
            label = QLabel("-")
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.detail_labels[key] = label
            detail_layout.addRow(key, label)
        right.addWidget(detail_box)
        self.payload = QPlainTextEdit()
        self.payload.setReadOnly(True)
        self.payload.setFont(QFont("Menlo", 11))
        right.addWidget(self.payload, 3)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        layout.addWidget(splitter)

        self.refresh()

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
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Tools")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        group = QGroupBox("RAMify Ableton Sets")
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(QLabel("Flip AudioClip RAM flags for faster playback."))

        target_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        target_row.addWidget(self.path_edit)
        file_btn = QPushButton("Choose File")
        file_btn.clicked.connect(self._choose_file)
        target_row.addWidget(file_btn)
        folder_btn = QPushButton("Choose Folder")
        folder_btn.clicked.connect(self._choose_folder)
        target_row.addWidget(folder_btn)
        group_layout.addLayout(target_row)

        options_row = QHBoxLayout()
        self.dry_cb = QCheckBox("Dry run (no writes)")
        self.dry_cb.setChecked(True)
        self.inplace_cb = QCheckBox("In-place (create .bak)")
        self.inplace_cb.setChecked(True)
        self.recursive_cb = QCheckBox("Recursive (if folder)")
        options_row.addWidget(self.dry_cb)
        options_row.addWidget(self.inplace_cb)
        options_row.addWidget(self.recursive_cb)
        options_row.addStretch(1)
        group_layout.addLayout(options_row)

        actions = QHBoxLayout()
        self.run_btn = QPushButton("Run RAMify")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._run)
        actions.addWidget(self.run_btn)
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self._clear_log)
        actions.addWidget(clear_btn)
        actions.addStretch(1)
        group_layout.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Menlo", 11))
        self.log.setMinimumHeight(240)
        group_layout.addWidget(self.log)

        layout.addWidget(group)
        layout.addStretch(1)
        self._log("Ready. Tip: start with Dry run.")

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
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        group = QGroupBox("Maintenance")
        group_layout = QHBoxLayout(group)
        group_layout.setSpacing(12)
        self.analytics_btn = QPushButton("Run Analytics")
        self.analytics_btn.setObjectName("Primary")
        self.analytics_btn.clicked.connect(self._run_analytics)
        group_layout.addWidget(self.analytics_btn)
        self.audit_btn = QPushButton("Audit Missing")
        self.audit_btn.clicked.connect(self._audit_missing)
        group_layout.addWidget(self.audit_btn)
        self.audit_zero_btn = QPushButton("Audit Zero Tracks")
        self.audit_zero_btn.clicked.connect(self._audit_zero_tracks)
        group_layout.addWidget(self.audit_zero_btn)
        self.optimize_btn = QPushButton("Optimize DB")
        self.optimize_btn.clicked.connect(self._optimize_db)
        group_layout.addWidget(self.optimize_btn)
        group_layout.addStretch(1)
        layout.addWidget(group)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Menlo", 11))
        layout.addWidget(self.output)
        layout.addStretch(1)

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


class PlaceholderView(QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))
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
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 8, 12, 12)
        root_layout.setSpacing(12)
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
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
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
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(18, 12, 18, 12)
    layout.setSpacing(12)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    brand = QWidget()
    brand_layout = QHBoxLayout(brand)
    brand_layout.setContentsMargins(0, 0, 0, 0)
    brand_layout.setSpacing(10)
    brand_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    logo_path = ABLETOOLS_DIR / "resources" / "abletools_mark.svg"
    if logo_path.exists():
        logo = QLabel()
        logo.setObjectName("HeaderLogo")
        logo.setPixmap(_svg_pixmap(logo_path, 44))
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        brand_layout.addWidget(logo)

    title = QLabel("Abletools")
    title.setObjectName("appTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    title.setFixedHeight(44)
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

    app.setStyleSheet(
        """
        QWidget {
            color: #e6f1ff;
        }
        #AppRoot {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #04060a,
                stop:0.5 #070b12,
                stop:1 #0b1320
            );
        }
        #HeaderBar {
            border-bottom: 2px solid #3a6f98;
            min-height: 64px;
        }
        QTabWidget::pane {
            border: 2px solid #3a6f98;
            border-radius: 8px;
            background: #122033;
        }
        QTabBar::tab {
            background: #0c121b;
            padding: 12px 20px;
            min-height: 36px;
            min-width: 92px;
            font-size: 13px;
            border: 2px solid #3a6f98;
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin-right: 6px;
        }
        QTabBar::tab:selected {
            background: #121b26;
            color: #19f5c8;
            border-bottom: 3px solid #19f5c8;
        }
        QPushButton {
            background: #121b26;
            border: 2px solid #3a6f98;
            border-radius: 6px;
            padding: 7px 12px;
        }
        QPushButton:hover {
            background: #1b2736;
            border-color: #4b86b3;
        }
        QPushButton#Primary {
            background: #19f5c8;
            color: #001014;
            border-color: #19f5c8;
        }
        QPushButton#Primary:hover {
            background: #38f7d6;
        }
        QGroupBox {
            border: 2px solid #3a6f98;
            border-radius: 8px;
            margin-top: 8px;
            background: #122033;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px 0 4px;
            color: #9bb3c9;
        }
        QGroupBox#SummaryBox, QGroupBox#DetailsBox {
            background: #122033;
        }
        QLabel#FilterLabel {
            font-size: 12px;
            font-weight: 600;
            color: #9bb3c9;
            padding-right: 4px;
        }
        QLabel#FieldLabel {
            font-size: 12px;
            font-weight: 600;
            color: #9bb3c9;
            padding-right: 6px;
        }
        QLabel#CatalogScopeLabel, QLabel#CatalogSearchLabel {
            font-size: 12px;
            font-weight: 600;
            color: #9bb3c9;
            padding-right: 4px;
        }
        QComboBox#CatalogScope, QLineEdit#CatalogSearch {
            min-height: 22px;
            padding: 2px 6px;
            margin-top: 0px;
        }
        QLabel#FilterLabel,
        QCheckBox#CatalogFilterMissing,
        QCheckBox#CatalogFilterDevices,
        QCheckBox#CatalogFilterSamples,
        QCheckBox#CatalogFilterBackups {
            padding-top: 0px;
        }
        QCheckBox {
            padding-right: 2px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            margin-right: 4px;
        }
        QCheckBox::indicator:checked {
            background: #19f5c8;
            border-color: #19f5c8;
        }
        QCheckBox {
            spacing: 4px;
        }
        QPushButton#CatalogSearchBtn, QPushButton#CatalogResetBtn {
            padding: 4px 10px;
            min-height: 22px;
        }
        QLabel#StatValue {
            font-size: 20px;
            font-weight: 700;
            color: #e6f1ff;
        }
        QLabel#StatSub {
            font-size: 11px;
            color: #9bb3c9;
        }
        QLineEdit, QPlainTextEdit, QListWidget, QTableWidget {
            background: #0f1826;
            border: 2px solid #3a6f98;
            border-radius: 6px;
            padding: 6px 8px;
        }
        QLineEdit, QComboBox {
            min-height: 32px;
            font-size: 12px;
        }
        QPlainTextEdit, QTableWidget, QListWidget {
            font-size: 12px;
        }
        QComboBox {
            background: #0f1826;
            border: 2px solid #3a6f98;
            border-radius: 6px;
            padding: 4px 8px;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border-color: #19f5c8;
        }
        QHeaderView::section {
            background: #121b26;
            border: 2px solid #3a6f98;
            padding: 8px;
            font-size: 11px;
        }
        QTableWidget {
            gridline-color: #3a6f98;
        }
        QTableWidget::item {
            padding: 6px;
        }
        QTableWidget#SummaryTable {
            border: none;
        }
        QListWidget::item {
            padding: 6px 8px;
        }
        QCheckBox {
            spacing: 6px;
            font-size: 12px;
            font-family: "Avenir Next";
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 2px solid #3a6f98;
            background: #0f1826;
        }
        QCheckBox::indicator:checked {
            background: #19f5c8;
            border-color: #19f5c8;
        }
        QCheckBox::indicator:hover {
            border-color: #4b86b3;
        }
        QScrollArea {
            border: none;
        }
        QScrollBar:vertical {
            background: #3a6f98;
            width: 12px;
            margin: 2px 2px 2px 0;
        }
        QScrollBar::handle:vertical {
            background: #3a6f98;
            border-radius: 5px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover {
            background: #19f5c8;
        }
        QScrollBar:horizontal {
            background: #3a6f98;
            height: 12px;
            margin: 0 2px 2px 2px;
        }
        QScrollBar::handle:horizontal {
            background: #3a6f98;
            border-radius: 5px;
            min-width: 24px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #19f5c8;
        }
        QSplitter::handle {
            background: #3a6f98;
        }
        QSplitter::handle:hover {
            background: #19f5c8;
        }
        QLabel#appTitle {
            font-size: 24px;
            font-weight: 700;
            color: #19f5c8;
            padding-top: 2px;
            letter-spacing: 0.5px;
        }
        QLabel#HeaderLogo {
            padding-top: 1px;
        }
        QLabel#SectionTitle {
            font-size: 16px;
            font-weight: 600;
        }
        """
    )


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
