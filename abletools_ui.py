#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import queue
import sqlite3
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tempfile
from typing import Optional

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from abletools_prefs import get_key_paths, get_preferences_folder, suggest_scan_root
from ramify_core import iter_targets, process_file

ABLETOOLS_DIR = Path(__file__).resolve().parent

BG = "#05070b"
BG_NAV = "#060b12"
PANEL = "#0c121b"
PANEL_ALT = "#121b26"
ACCENT = "#19f5c8"
ACCENT_SOFT = "#14c5a2"
ACCENT_2 = "#ff2ed1"
TEXT = "#e6f1ff"
MUTED = "#8aa4b3"
BORDER = "#1b2a3a"
WARN = "#ff6b6b"
SUCCESS = "#7dffb2"

TITLE_FONT = ("Menlo", 16, "bold")
H2_FONT = ("Menlo", 12, "bold")
BODY_FONT = ("Menlo", 11)
MONO_FONT = ("Menlo", 10)


class AnimatedGif:
    def __init__(
        self,
        label: tk.Label,
        path: Path,
        delay_ms: int = 80,
        subsample: int = 1,
    ) -> None:
        self.label = label
        self.path = path
        self.delay_ms = delay_ms
        self.subsample = max(1, subsample)
        self.frames: list[tk.PhotoImage] = []
        self._job: Optional[str] = None
        self._idx = 0
        self._load_frames()

    def _load_frames(self) -> None:
        if not self.path.exists():
            return
        idx = 0
        while True:
            try:
                frame = tk.PhotoImage(file=str(self.path), format=f"gif -index {idx}")
            except tk.TclError:
                break
            if self.subsample > 1:
                frame = frame.subsample(self.subsample, self.subsample)
            self.frames.append(frame)
            idx += 1

    def start(self) -> None:
        if not self.frames:
            return
        self.stop()
        self._tick()

    def _tick(self) -> None:
        if not self.frames:
            return
        self.label.configure(image=self.frames[self._idx])
        self._idx = (self._idx + 1) % len(self.frames)
        self._job = self.label.after(self.delay_ms, self._tick)

    def stop(self) -> None:
        if self._job:
            self.label.after_cancel(self._job)
            self._job = None
        if self.frames:
            self.label.configure(image=self.frames[0])


class AnimatedGifCanvas:
    def __init__(
        self,
        canvas: tk.Canvas,
        path: Path,
        delay_ms: int = 80,
        subsample: int = 1,
    ) -> None:
        self.canvas = canvas
        self.path = path
        self.delay_ms = delay_ms
        self.subsample = max(1, subsample)
        self.frames: list[tk.PhotoImage] = []
        self._job: Optional[str] = None
        self._idx = 0
        self._item: Optional[int] = None
        self._overlay: Optional[int] = None
        self._load_frames()

    def _load_frames(self) -> None:
        if not self.path.exists():
            return
        idx = 0
        while True:
            try:
                frame = tk.PhotoImage(file=str(self.path), format=f"gif -index {idx}")
            except tk.TclError:
                break
            if self.subsample > 1:
                frame = frame.subsample(self.subsample, self.subsample)
            self.frames.append(frame)
            idx += 1

    def place_centered(self, width: int, height: int) -> None:
        if not self.frames:
            return
        x = max(0, width // 2)
        y = max(0, height // 2)
        if self._item is None:
            self._item = self.canvas.create_image(
                x, y, image=self.frames[0], anchor="center", tags=("bg",)
            )
        else:
            self.canvas.coords(self._item, x, y)
        if self._overlay is None:
            self._overlay = self.canvas.create_rectangle(
                0,
                0,
                width,
                height,
                fill="#000000",
                stipple="gray50",
                outline="",
                tags=("overlay",),
            )
        else:
            self.canvas.coords(self._overlay, 0, 0, width, height)
        self.canvas.tag_lower("bg")
        self.canvas.tag_raise("overlay")

    def start(self) -> None:
        if not self.frames:
            return
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width > 0 and height > 0:
            self.place_centered(width, height)
        self.stop()
        self._tick()

    def _tick(self) -> None:
        if not self.frames or self._item is None:
            return
        self.canvas.itemconfigure(self._item, image=self.frames[self._idx])
        self._idx = (self._idx + 1) % len(self.frames)
        self._job = self.canvas.after(self.delay_ms, self._tick)

    def stop(self) -> None:
        if self._job:
            self.canvas.after_cancel(self._job)
            self._job = None
        if self.frames and self._item is not None:
            self.canvas.itemconfigure(self._item, image=self.frames[0])


@dataclass
class CatalogStats:
    file_count: int = 0
    doc_count: int = 0
    refs_count: int = 0
    missing_refs: int = 0
    last_scan: str = ""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class DashboardPanel(tk.Frame):
    def __init__(self, master: tk.Misc, app: "AbletoolsUI") -> None:
        super().__init__(master, bg=BG)
        self.app = app
        self.stats = CatalogStats()

        self._build()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(16, 8))

        tk.Label(header, text="Dashboard", font=TITLE_FONT, fg=TEXT, bg=BG).pack(
            side="left"
        )
        tk.Button(
            header,
            text="Refresh",
            command=self.refresh,
            bg=ACCENT,
            fg="#001014",
            relief="flat",
            padx=14,
            pady=6,
        ).pack(side="right")

        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="x", padx=16)
        cards.columnconfigure((0, 1, 2, 3), weight=1)

        self._card_files = self._make_stat_card(cards, "Files", 0)
        self._card_docs = self._make_stat_card(cards, "Ableton Docs", 1)
        self._card_refs = self._make_stat_card(cards, "Refs", 2)
        self._card_missing = self._make_stat_card(cards, "Missing", 3)

        activity = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        activity.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            activity,
            text="Recent Activity",
            font=H2_FONT,
            fg=TEXT,
            bg=PANEL,
        ).pack(anchor="w", padx=12, pady=(10, 4))

        self.activity_text = tk.Text(
            activity,
            height=8,
            bg=PANEL,
            fg=MUTED,
            insertbackground=TEXT,
            relief="flat",
            font=MONO_FONT,
        )
        self.activity_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.activity_text.configure(state="disabled")

        analytics = tk.Frame(self, bg=BG)
        analytics.pack(fill="x", padx=16, pady=(0, 16))
        analytics.columnconfigure((0, 1, 2), weight=1)

        self.top_devices_text = self._make_analytics_box(analytics, "Top Devices", 0)
        self.top_chains_text = self._make_analytics_box(analytics, "Top FX Chains", 1)
        self.missing_paths_text = self._make_analytics_box(
            analytics, "Missing Refs Paths", 2
        )

    def _make_analytics_box(self, master: tk.Frame, title: str, col: int) -> tk.Text:
        box = tk.Frame(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        box.grid(row=0, column=col, sticky="nsew", padx=6)
        tk.Label(box, text=title, font=H2_FONT, fg=TEXT, bg=PANEL).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        text = tk.Text(
            box,
            height=6,
            bg=PANEL,
            fg=MUTED,
            insertbackground=TEXT,
            relief="flat",
            font=MONO_FONT,
        )
        text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        text.configure(state="disabled")
        return text

    def _make_stat_card(self, master: tk.Frame, title: str, col: int) -> tk.Label:
        card = tk.Frame(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=6, pady=6)

        tk.Label(card, text=title, font=H2_FONT, fg=MUTED, bg=PANEL).pack(
            anchor="w", padx=12, pady=(10, 0)
        )
        value = tk.Label(card, text="-", font=("Menlo", 20, "bold"), fg=TEXT, bg=PANEL)
        value.pack(anchor="w", padx=12, pady=(4, 12))
        return value

    def refresh(self) -> None:
        self.stats = self.app.load_catalog_stats()
        self._card_files.configure(text=str(self.stats.file_count))
        self._card_docs.configure(text=str(self.stats.doc_count))
        self._card_refs.configure(text=str(self.stats.refs_count))
        self._card_missing.configure(text=str(self.stats.missing_refs))

        summary_path = self.app.resolve_scan_summary()
        summary = _safe_read_json(summary_path) if summary_path else {}
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
        self.activity_text.configure(state="normal")
        self.activity_text.delete("1.0", "end")
        self.activity_text.insert("end", "\n".join(lines))
        self.activity_text.configure(state="disabled")

        devices = self.app.load_top_devices()
        chains = self.app.load_top_chains()
        missing_paths = self.app.load_missing_refs_paths()
        self.top_devices_text.configure(state="normal")
        self.top_devices_text.delete("1.0", "end")
        self.top_devices_text.insert("end", "\n".join(devices) if devices else "No data yet.")
        self.top_devices_text.configure(state="disabled")

        self.top_chains_text.configure(state="normal")
        self.top_chains_text.delete("1.0", "end")
        self.top_chains_text.insert("end", "\n".join(chains) if chains else "No data yet.")
        self.top_chains_text.configure(state="disabled")

        self.missing_paths_text.configure(state="normal")
        self.missing_paths_text.delete("1.0", "end")
        self.missing_paths_text.insert(
            "end", "\n".join(missing_paths) if missing_paths else "No data yet."
        )
        self.missing_paths_text.configure(state="disabled")


class CatalogPanel(tk.Frame):
    def __init__(self, master: tk.Misc, app: "AbletoolsUI") -> None:
        super().__init__(master, bg=BG)
        self.app = app
        self.search_var = tk.StringVar(value="")
        self.scope_var = tk.StringVar(value="live_recordings")
        self.filter_missing = tk.BooleanVar(value=False)
        self.filter_devices = tk.BooleanVar(value=False)
        self.filter_samples = tk.BooleanVar(value=False)
        self.visible_columns: list[str] = []
        self._sort_state: dict[str, bool] = {}
        self._last_rows: list[dict[str, str]] = []
        self._build()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(16, 8))

        tk.Label(header, text="Catalog", font=TITLE_FONT, fg=TEXT, bg=BG).pack(
            side="left"
        )

        search = tk.Frame(header, bg=BG)
        search.pack(side="right")
        scope_menu = ttk.Combobox(
            search,
            textvariable=self.scope_var,
            values=["live_recordings", "user_library", "preferences", "all"],
            state="readonly",
            width=16,
        )
        scope_menu.pack(side="left", padx=(0, 8))
        scope_menu.bind("<<ComboboxSelected>>", lambda _event: self._on_scope_change())
        search_entry = tk.Entry(
            search,
            textvariable=self.search_var,
            font=BODY_FONT,
            width=28,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )
        search_entry.pack(side="left", padx=(0, 8))
        search_entry.bind("<Return>", lambda _event: self.refresh())
        ttk.Button(
            search,
            text="Search",
            command=self.refresh,
            style="Accent.TButton",
        ).pack(side="left")
        ttk.Button(
            search,
            text="Reset",
            command=self._reset_filters,
            style="Ghost.TButton",
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            search,
            text="Columns",
            command=self._show_columns_menu,
            style="Ghost.TButton",
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            search,
            text="Full Table",
            command=self._open_full_table,
            style="Ghost.TButton",
        ).pack(side="left", padx=(8, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        filters = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        filters.grid(row=0, column=0, sticky="ns", padx=(0, 12))

        tk.Label(filters, text="Filters", font=H2_FONT, fg=TEXT, bg=PANEL).pack(
            anchor="w", padx=12, pady=(10, 6)
        )
        self.filter_buttons: dict[str, tk.Checkbutton] = {}
        self.filter_buttons["missing"] = tk.Checkbutton(
            filters,
            text="Missing refs",
            variable=self.filter_missing,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=BG_NAV,
            command=self.refresh,
        )
        self.filter_buttons["missing"].pack(anchor="w", padx=12, pady=2)
        self.filter_buttons["devices"] = tk.Checkbutton(
            filters,
            text="Has devices",
            variable=self.filter_devices,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=BG_NAV,
            command=self.refresh,
        )
        self.filter_buttons["devices"].pack(anchor="w", padx=12, pady=2)
        self.filter_buttons["samples"] = tk.Checkbutton(
            filters,
            text="Has samples",
            variable=self.filter_samples,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=BG_NAV,
            command=self.refresh,
        )
        self.filter_buttons["samples"].pack(anchor="w", padx=12, pady=(2, 12))

        center = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)

        tk.Label(center, text="Documents", font=H2_FONT, fg=TEXT, bg=PANEL).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )

        self.tree_frame = tk.Frame(center, bg=PANEL)
        self.tree_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._build_tree(self._default_columns_for_scope("live_recordings"))

        detail = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        detail.grid(row=0, column=2, sticky="ns", padx=(12, 0))
        detail.rowconfigure(1, weight=1)

        tk.Label(detail, text="Details", font=H2_FONT, fg=TEXT, bg=PANEL).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )
        self.detail_frame = tk.Frame(detail, bg=PANEL)
        self.detail_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.detail_rows: list[tuple[tk.Label, tk.Label]] = []
        for _ in range(12):
            label = tk.Label(
                self.detail_frame,
                text="",
                font=BODY_FONT,
                fg=MUTED,
                bg=PANEL,
                anchor="e",
                width=12,
            )
            value = tk.Label(
                self.detail_frame,
                text="",
                font=BODY_FONT,
                fg=TEXT,
                bg=PANEL,
                anchor="w",
            )
            row = len(self.detail_rows)
            label.grid(row=row, column=0, sticky="e", padx=(0, 6), pady=2)
            value.grid(row=row, column=1, sticky="w", pady=2)
            self.detail_rows.append((label, value))
        self._configure_filters(self.scope_var.get())

    def _reset_filters(self) -> None:
        self.search_var.set("")
        self.filter_missing.set(False)
        self.filter_devices.set(False)
        self.filter_samples.set(False)
        self.refresh()

    def _on_scope_change(self) -> None:
        scope = self.scope_var.get()
        self.app.set_current_scope(scope)
        self._set_columns_for_scope(scope)
        self._configure_filters(scope)
        self.refresh()

    def _default_columns_for_scope(self, scope: str) -> list[str]:
        if scope == "live_recordings":
            return ["name", "mtime", "path_full", "scope"]
        if scope == "user_library":
            return ["name", "mtime", "path_full", "scope"]
        if scope == "preferences":
            return ["kind", "source", "mtime", "scope"]
        return ["name", "mtime", "path_full", "scope"]

    def _optional_columns_for_scope(self, scope: str) -> list[str]:
        if scope == "live_recordings":
            return ["tracks", "clips", "devices", "samples", "missing", "ext", "size"]
        if scope == "user_library":
            return ["ext", "size", "missing"]
        if scope == "preferences":
            return []
        return ["tracks", "clips", "devices", "samples", "missing", "ext", "size"]

    def _set_columns_for_scope(self, scope: str) -> None:
        base = self._default_columns_for_scope(scope)
        self.visible_columns = base
        self._build_tree(self.visible_columns)

    def _configure_filters(self, scope: str) -> None:
        state = "normal" if scope in {"live_recordings", "all"} else "disabled"
        self._set_filter_state("missing", self.filter_missing, state)
        self._set_filter_state("devices", self.filter_devices, state)
        self._set_filter_state("samples", self.filter_samples, state)

    def _set_filter_state(self, key: str, var: tk.BooleanVar, state: str) -> None:
        if state == "disabled":
            var.set(False)
        btn = self.filter_buttons.get(key)
        if btn:
            btn.configure(state=state)

    def _show_columns_menu(self) -> None:
        scope = self.scope_var.get()
        optional = self._optional_columns_for_scope(scope)
        if not optional:
            messagebox.showinfo("Columns", "No optional columns for this scope.")
            return
        menu = tk.Menu(self, tearoff=False)
        for col in optional:
            var = tk.BooleanVar(value=col in self.visible_columns)

            def _toggle(c: str = col, v: tk.BooleanVar = var) -> None:
                if v.get():
                    if c not in self.visible_columns:
                        self.visible_columns.insert(1, c)
                else:
                    if c in self.visible_columns:
                        self.visible_columns.remove(c)
                self._build_tree(self.visible_columns)
                self.refresh()

            menu.add_checkbutton(label=col.replace("_", " ").title(), variable=var, command=_toggle)
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _full_columns_for_scope(self, scope: str) -> list[str]:
        if scope == "live_recordings":
            return [
                "name",
                "ext",
                "size",
                "mtime",
                "tracks",
                "clips",
                "devices",
                "samples",
                "missing",
                "path_full",
            ]
        if scope == "user_library":
            return ["name", "ext", "size", "mtime", "path_full"]
        if scope == "preferences":
            return ["kind", "source", "mtime"]
        return ["name", "ext", "size", "mtime", "missing", "path_full"]

    def _open_full_table(self) -> None:
        scope = self.scope_var.get()
        if not self._last_rows:
            self.refresh()
        win = tk.Toplevel(self)
        win.title("Catalog - Full Table")
        win.geometry("900x600")
        frame = tk.Frame(win, bg=BG)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            frame,
            columns=self._full_columns_for_scope(scope),
            show="headings",
            height=20,
        )
        for col in tree["columns"]:
            heading = col.replace("_", " ").title()
            tree.heading(col, text=heading, command=lambda c=col: None)
            tree.column(col, anchor="w")
        tree.pack(fill="both", expand=True)
        for values in self._last_rows:
            row_values = [values.get(col, "") for col in tree["columns"]]
            tree.insert("", "end", values=row_values)
        win.focus_set()

    def _build_tree(self, columns: list[str]) -> None:
        for child in self.tree_frame.winfo_children():
            child.destroy()
        self.visible_columns = columns
        self.tree = ttk.Treeview(
            self.tree_frame,
            columns=columns,
            show="headings",
            height=14,
        )
        for col in columns:
            heading = col.replace("_", " ").title()
            self.tree.heading(col, text=heading, command=lambda c=col: self._sort_by(c))
        widths = {
            "name": 280,
            "path_full": 0,
            "ext": 70,
            "size": 90,
            "mtime": 140,
            "tracks": 70,
            "clips": 70,
            "devices": 70,
            "samples": 70,
            "missing": 70,
            "scope": 90,
            "kind": 90,
            "source": 260,
        }
        anchors = {
            "size": "e",
            "tracks": "center",
            "clips": "center",
            "devices": "center",
            "samples": "center",
            "missing": "center",
            "ext": "center",
        }
        for col in columns:
            width = widths.get(col, 120)
            stretch = col not in {"path_full"}
            self.tree.column(col, width=width, anchor=anchors.get(col, "w"), stretch=stretch)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _sort_by(self, column: str) -> None:
        items = [(self.tree.set(k, column), k) for k in self.tree.get_children("")]
        reverse = self._sort_state.get(column, False)

        def to_number(val: str) -> float:
            try:
                return float(val)
            except Exception:
                return 0.0

        if column in {"size", "tracks", "clips"}:
            items.sort(key=lambda t: to_number(t[0]), reverse=reverse)
        elif column in {"mtime"}:
            items.sort(key=lambda t: to_number(t[0]), reverse=reverse)
        else:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)
        for index, (_, k) in enumerate(items):
            self.tree.move(k, "", index)
        self._sort_state[column] = not reverse

    def _autosize_columns(self) -> None:
        font = tkfont.Font(font=BODY_FONT)
        for col in self.visible_columns:
            if col == "path_full":
                continue
            max_width = font.measure(col.replace("_", " ").title()) + 20
            for item in self.tree.get_children("")[:200]:
                value = self.tree.set(item, col)
                max_width = max(max_width, font.measure(value) + 20)
            self.tree.column(col, width=min(max_width, 420))

    def _truncate_path(self, path: str, max_len: int = 60) -> str:
        if len(path) <= max_len:
            return path
        keep = max_len // 2
        return f"{path[:keep]}…{path[-keep:]}"

    def _set_detail_fields(self, fields: list[tuple[str, str]]) -> None:
        for idx, (label, value) in enumerate(self.detail_rows):
            if idx < len(fields):
                label.configure(text=f"{fields[idx][0]}:")
                value.configure(text=fields[idx][1])
            else:
                label.configure(text="")
                value.configure(text="")

    def _set_detail_message(self, message: str) -> None:
        self._set_detail_fields([("Info", message)])

    def refresh(self) -> None:
        if self.app.current_scope and self.scope_var.get() != "all":
            if self.scope_var.get() != self.app.current_scope:
                self.scope_var.set(self.app.current_scope)
        db_path = self.app.resolve_catalog_db_path()
        self.tree.delete(*self.tree.get_children())
        self._set_detail_message("Select an item to view details.")
        if not db_path or not db_path.exists():
            self.app.ensure_catalog_db()
            db_path = self.app.resolve_catalog_db_path()
            if not db_path or not db_path.exists():
                self._set_detail_message(
                    f"No database found at {db_path}. Run a scan to populate data."
                )
                return

        term = self.search_var.get().strip()
        scope = self.scope_var.get()
        clauses = []
        params = []
        if term:
            if scope == "preferences":
                clauses.append("(source LIKE ? OR kind LIKE ?)")
                params.extend([f"%{term}%", f"%{term}%"])
            else:
                clauses.append("path LIKE ?")
                params.append(f"%{term}%")
        if self.filter_missing.get():
            clauses.append("missing_refs = 1")
        if self.filter_devices.get():
            clauses.append("has_devices = 1")
        if self.filter_samples.get():
            clauses.append("has_samples = 1")

        where_sql = " AND ".join(clauses) if clauses else "1=1"

        if scope == "preferences":
            sql = (
                "SELECT kind, source, mtime, scanned_at "
                "FROM ableton_prefs "
                f"WHERE {where_sql} "
                "ORDER BY mtime DESC LIMIT 500"
            )
        elif scope == "user_library":
            sql = (
                "SELECT path, ext, size, mtime "
                "FROM file_index_user_library "
                "WHERE kind != 'ableton_doc' "
                f"AND {where_sql} "
                "ORDER BY mtime DESC LIMIT 500"
            )
        elif scope == "all":
            sql = (
                "SELECT path, ext, size, mtime, tracks_total, clips_total, "
                "has_devices, has_samples, missing_refs, scanned_at, scope "
                "FROM catalog_docs "
                f"WHERE {where_sql} "
                "ORDER BY scanned_at DESC LIMIT 500"
            )
        else:
            sql = (
                "SELECT path, ext, size, mtime, tracks_total, clips_total, "
                "has_devices, has_samples, missing_refs, scanned_at, scope "
                "FROM catalog_docs "
                "WHERE scope = ? AND ext IN ('.als', '.alc') AND "
                f"{where_sql} "
                "ORDER BY scanned_at DESC LIMIT 500"
            )
            params = [scope, *params]
        try:
            with sqlite3.connect(db_path) as conn:
                self._last_rows = []
                for row in conn.execute(sql, params):
                    if scope == "preferences":
                        values = {
                            "kind": row[0],
                            "source": row[1],
                            "mtime": str(row[2]),
                            "scope": "preferences",
                        }
                    elif scope == "user_library":
                        name = self._truncate_path(Path(row[0]).name)
                        values = {
                            "name": name,
                            "path_full": row[0],
                            "ext": row[1],
                            "size": str(row[2]),
                            "mtime": str(row[3]),
                            "scope": "user_library",
                        }
                    else:
                        name = self._truncate_path(Path(row[0]).name)
                        values = {
                            "name": name,
                            "path_full": row[0],
                            "ext": row[1],
                            "size": str(row[2]),
                            "mtime": str(row[3]),
                            "tracks": "" if row[4] is None else str(row[4]),
                            "clips": "" if row[5] is None else str(row[5]),
                            "devices": "yes" if row[6] else "no",
                            "samples": "yes" if row[7] else "no",
                            "missing": "yes" if row[8] else "no",
                            "scanned_at": str(row[9]),
                            "scope": row[10],
                        }
                    row_values = [values.get(col, "") for col in self.visible_columns]
                    self.tree.insert("", "end", values=row_values)
                    self._last_rows.append(values)
            self._autosize_columns()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                self._set_detail_message(
                    "Catalog not built yet. Updating database and retrying..."
                )
                self.app.refresh_catalog_db()
                return self.refresh()
            self._set_detail_message(f"Failed to load catalog: {exc}")
        except Exception as exc:
            self._set_detail_message(f"Failed to load catalog: {exc}")

    def _set_detail(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("end", text)
        self.detail_text.configure(state="disabled")

    def _on_select(self, _event: object) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        values_map = {col: values[idx] for idx, col in enumerate(self.visible_columns)}
        scope = values_map.get("scope", "live_recordings")
        path = values_map.get("path_full") or values_map.get("source") or values_map.get("name")
        suffix = "" if scope == "live_recordings" else f"_{scope}"
        db_path = self.app.resolve_catalog_db_path()
        if not db_path or not db_path.exists():
            self._set_detail_message("No database found.")
            return
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                if scope == "preferences":
                    row = conn.execute(
                        "SELECT kind, source, mtime, payload_json FROM ableton_prefs WHERE source = ?",
                        (values_map.get("source"),),
                    ).fetchone()
                    if not row:
                        self._set_detail_message("Preference not found.")
                        return
                    payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
                    fields = [
                        ("Kind", row["kind"]),
                        ("Source", self._truncate_path(row["source"], 80)),
                        ("Modified", str(row["mtime"])),
                        ("Keys", ", ".join(sorted(payload.keys()))[:80]),
                    ]
                    self._set_detail_fields(fields)
                    return

                doc = conn.execute(
                    f"SELECT * FROM ableton_docs{suffix} WHERE path = ?", (path,)
                ).fetchone()
                try:
                    file_row = conn.execute(
                        f"SELECT ext, size, mtime, audio_duration, audio_sample_rate, audio_channels "
                        f"FROM file_index{suffix} WHERE path = ?",
                        (path,),
                    ).fetchone()
                except sqlite3.OperationalError:
                    file_row = conn.execute(
                        f"SELECT ext, size, mtime FROM file_index{suffix} WHERE path = ?",
                        (path,),
                    ).fetchone()
                samples = conn.execute(
                    f"SELECT COUNT(*) FROM doc_sample_refs{suffix} WHERE doc_path = ?",
                    (path,),
                ).fetchone()[0]
                devices = conn.execute(
                    f"SELECT COUNT(*) FROM doc_device_hints{suffix} WHERE doc_path = ?",
                    (path,),
                ).fetchone()[0]
                missing = conn.execute(
                    f"SELECT COUNT(*) FROM refs_graph{suffix} WHERE src = ? AND ref_exists = 0",
                    (path,),
                ).fetchone()[0]
        except Exception as exc:
            self._set_detail_message(f"Failed to load details: {exc}")
            return

        if not doc and scope == "user_library":
            fields = [
                ("Path", self._truncate_path(path, 80)),
                ("Type", values_map.get("ext", "")),
                ("Size", values_map.get("size", "")),
                ("Modified", values_map.get("mtime", "")),
            ]
            self._set_detail_fields(fields)
            return

        if not doc:
            self._set_detail_message("Document not found in database.")
            return

        audio_duration = ""
        audio_rate = ""
        audio_channels = ""
        if file_row and "audio_duration" in file_row.keys():
            audio_duration = file_row["audio_duration"] or ""
            audio_rate = file_row["audio_sample_rate"] or ""
            audio_channels = file_row["audio_channels"] or ""

        fields = [
            ("Path", self._truncate_path(doc["path"], 80)),
            ("Ext", file_row["ext"] if file_row else ""),
            ("Size", str(file_row["size"] if file_row else "")),
            ("Modified", str(file_row["mtime"] if file_row else "")),
            ("Tracks", str(doc["tracks_total"])),
            ("Clips", str(doc["clips_total"])),
            ("Devices", str(devices)),
            ("Samples", str(samples)),
            ("Missing", str(missing)),
            ("Tempo", str(doc["tempo"])),
            ("Audio dur", str(audio_duration)),
            ("Audio rate", str(audio_rate)),
        ]
        self._set_detail_fields(fields)


class ScanPanel(ttk.LabelFrame):
    def __init__(self, master: tk.Misc, app: "AbletoolsUI") -> None:
        super().__init__(master, text="Scan & Catalog", padding=10)
        self.app = app

        self.root_var = tk.StringVar(value=str(self.app.default_scan_root()))
        self.incremental_var = tk.BooleanVar(value=True)
        self.include_media_var = tk.BooleanVar(value=False)
        self.hash_var = tk.BooleanVar(value=False)
        self.rehash_var = tk.BooleanVar(value=False)
        self.scope_var = tk.StringVar(value="live_recordings")
        self.all_files_var = tk.BooleanVar(value=True)
        self.analyze_audio_var = tk.BooleanVar(value=False)
        self.log_visible = tk.BooleanVar(value=False)

        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue[str] = queue.Queue()
        self._stop_requested = False

        self._build_ui()
        self._pump_queue()

    def _build_ui(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, columnspan=3, sticky="we", pady=(0, 6))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Root folder:").grid(row=0, column=0, sticky="w")
        self.root_entry = ttk.Entry(header, textvariable=self.root_var, width=60)
        self.root_entry.grid(row=0, column=1, sticky="we", padx=(8, 8))
        ttk.Button(header, text="Browse...", command=self._browse, style="Ghost.TButton").grid(
            row=0, column=2, sticky="e"
        )

        self.gif = AnimatedGif(tk.Label(header), Path(), delay_ms=80)

        opts = ttk.Frame(self)
        opts.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(opts, text="Scope:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        scope_menu = ttk.Combobox(
            opts,
            textvariable=self.scope_var,
            values=["live_recordings", "user_library", "preferences", "all"],
            state="readonly",
            width=16,
        )
        scope_menu.grid(row=0, column=1, sticky="w", padx=(0, 14))
        scope_menu.bind("<<ComboboxSelected>>", self._on_scope_change)

        ttk.Checkbutton(
            opts,
            text="Incremental (skip unchanged)",
            variable=self.incremental_var,
        ).grid(row=0, column=2, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts,
            text="Include media files",
            variable=self.include_media_var,
        ).grid(row=0, column=3, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts,
            text="Compute hashes (slow)",
            variable=self.hash_var,
        ).grid(row=0, column=4, sticky="w")
        ttk.Checkbutton(
            opts,
            text="Rehash unchanged",
            variable=self.rehash_var,
        ).grid(row=0, column=5, sticky="w", padx=(14, 0))
        ttk.Checkbutton(
            opts,
            text="All files",
            variable=self.all_files_var,
        ).grid(row=0, column=6, sticky="w", padx=(14, 0))
        ttk.Checkbutton(
            opts,
            text="Analyze audio",
            variable=self.analyze_audio_var,
        ).grid(row=0, column=7, sticky="w", padx=(14, 0))

        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, columnspan=3, sticky="we", pady=(10, 0))

        self.start_btn = ttk.Button(
            btns, text="Start Scan", command=self.start_scan, style="Accent.TButton"
        )
        self.start_btn.pack(side="left")

        self.cancel_btn = ttk.Button(
            btns,
            text="Cancel",
            command=self.cancel_scan,
            state="disabled",
            style="Ghost.TButton",
        )
        self.cancel_btn.pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(btns, textvariable=self.status_var).pack(side="left", padx=(12, 0))

        self.progress = ttk.Progressbar(btns, mode="indeterminate", length=200)
        self.progress.pack(side="left", padx=(12, 0))

        self.log_toggle = ttk.Button(
            btns, text="Show Log", command=self._toggle_log, style="Ghost.TButton"
        )
        self.log_toggle.pack(side="right")
        self.log_open_btn = ttk.Button(
            btns, text="Open Log", command=self._open_log, style="Ghost.TButton"
        )
        self.log_open_btn.pack(side="right", padx=(0, 8))

        self.log_frame = tk.Frame(self, bg=PANEL)
        self.log_frame.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        self.log_frame.grid_remove()

        self.log_text = tk.Text(
            self.log_frame,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=MONO_FONT,
            wrap="none",
        )
        self.log_scroll = tk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_scroll.pack(side="right", fill="y")
        self.log_text.bind("<Key>", lambda _event: "break")
        self.log_text.bind("<Control-v>", lambda _event: "break")
        self.log_text.bind("<Command-v>", lambda _event: "break")

        self._log_file = None
        self._log_file_path: Optional[Path] = None

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

    def _toggle_log(self) -> None:
        if self.log_visible.get():
            self.log_frame.grid_remove()
            self.log_visible.set(False)
            self.log_toggle.configure(text="Show Log")
        else:
            self.log_frame.grid()
            self.log_visible.set(True)
            self.log_toggle.configure(text="Hide Log")
            self.update_idletasks()

    def _browse(self) -> None:
        p = filedialog.askdirectory(
            initialdir=self.root_var.get() or str(self.app.default_scan_root())
        )
        if p:
            self.root_var.set(p)

    def _open_log(self) -> None:
        if not self._log_file_path or not self._log_file_path.exists():
            messagebox.showinfo("Scan Log", "No log file available yet.")
            return
        try:
            self.app.tk.call("exec", "open", str(self._log_file_path))
        except Exception:
            messagebox.showwarning("Scan Log", str(self._log_file_path))

    def _on_scope_change(self, _event: object) -> None:
        scope = self.scope_var.get()
        self.app.set_current_scope(scope)
        if scope == "user_library":
            root = self.app.user_library_root()
        elif scope == "preferences":
            root = self.app.preferences_root()
        elif scope == "all":
            root = Path(self.root_var.get()).expanduser()
            if not root.exists():
                root = self.app.default_scan_root()
        else:
            root = self.app.default_scan_root()
        if root:
            self.root_var.set(str(root))

    def _append_log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{stamp}] {line.rstrip('\n')}"
        self.log_text.insert("end", formatted + "\n")
        self.log_text.see("end")
        if self._log_file:
            self._log_file.write(formatted + "\n")
            self._log_file.flush()

    def _enqueue(self, s: str) -> None:
        self._q.put(s)

    def _pump_queue(self) -> None:
        try:
            while True:
                s = self._q.get_nowait()
                self._append_log(s)
        except queue.Empty:
            pass
        self.after(100, self._pump_queue)

    def _scan_thread(self, cmds: list[list[str]], cwd: Path) -> None:
        try:
            rc = 0
            for cmd in cmds:
                if self._stop_requested:
                    break
                self._enqueue("-----")
                self._enqueue(f"$ {' '.join(cmd)}")
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                )

                assert self._proc.stdout is not None
                for line in self._proc.stdout:
                    self._enqueue(line.rstrip("\n"))
                    if self._stop_requested:
                        break

                try:
                    rc = self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    rc = self._proc.wait(timeout=5)
                if rc != 0:
                    break

            if self._stop_requested:
                self._enqueue("Scan cancelled.")
                self.status_var.set("Cancelled")
            elif rc == 0:
                self._enqueue("Scan complete")
                self._enqueue("Updating catalog DB...")
                self._build_db()
                self.status_var.set("Done")
                self.app.set_active_root(Path(self.root_var.get()))
                self.app.set_current_scope(self.scope_var.get())
                self.app.refresh_dashboard()
            else:
                self._enqueue(f"Scan failed (exit={rc})")
                self.status_var.set("Error")

        except Exception as e:
            self._enqueue(f"ERROR: {e}")
            self.status_var.set("Error")
        finally:
            self._proc = None
            self._stop_requested = False
            self._set_running(False)

    def _build_db(self) -> None:
        catalog_dir = self.app.catalog_dir()
        db_script = self.app.abletools_dir / "abletools_catalog_db.py"
        if not db_script.exists():
            self._enqueue("WARN: abletools_catalog_db.py missing; DB not updated.")
            return
        self._enqueue(f"DB update: {db_script}")
        cmd = [sys.executable, str(db_script), str(catalog_dir), "--append"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.app.abletools_dir),
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            self._enqueue(f"DB update failed: {exc}")
            return
        if proc.stdout:
            self._enqueue(proc.stdout.strip())
        if proc.returncode != 0:
            self._enqueue(proc.stderr.strip() or "DB update failed.")
            return

        analytics = self.app.abletools_dir / "abletools_analytics.py"
        db_path = self.app.resolve_catalog_db_path()
        if analytics.exists() and db_path:
            try:
                proc = subprocess.run(
                    [sys.executable, str(analytics), str(db_path)],
                    cwd=str(self.app.abletools_dir),
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    self._enqueue(proc.stderr.strip() or "Analytics update failed.")
            except Exception as exc:
                self._enqueue(f"Analytics update failed: {exc}")

    def _set_running(self, running: bool) -> None:
        def _apply() -> None:
            self.start_btn.configure(state="disabled" if running else "normal")
            self.cancel_btn.configure(state="normal" if running else "disabled")
            if running:
                self.progress.start(10)
                self.gif.start()
            else:
                self.progress.stop()
                self.gif.stop()
                if self._log_file:
                    self._log_file.close()
                    self._log_file = None

        self.after(0, _apply)

    def start_scan(self) -> None:
        if self._proc is not None:
            return

        root = Path(self.root_var.get()).expanduser()
        if not root.exists() or not root.is_dir():
            messagebox.showerror("Scan", f"Root folder does not exist:\n{root}")
            return

        scan_script = self.app.scan_script_path()
        if not scan_script.exists():
            messagebox.showerror("Scan", f"Missing scanner script:\n{scan_script}")
            return

        scopes = [self.scope_var.get()]
        if scopes[0] == "all":
            scopes = ["live_recordings", "user_library", "preferences"]

        cmds: list[list[str]] = []
        for scope in scopes:
            cmd = [sys.executable, str(scan_script), str(root)]
            cmd.extend(["--scope", scope])
            cmd.extend(["--out", str(self.app.catalog_dir())])
            if self.incremental_var.get():
                cmd.append("--incremental")
            if self.include_media_var.get():
                cmd.append("--include-media")
            if self.analyze_audio_var.get():
                cmd.append("--analyze-audio")
            if self.hash_var.get():
                cmd.append("--hash")
                if self.rehash_var.get():
                    cmd.append("--rehash-all")
            if not self.all_files_var.get():
                cmd.append("--only-known")
            cmd.append("--verbose")
            cmds.append(cmd)

        self.status_var.set("Running...")
        self._set_running(True)

        if self.log_visible.get():
            self.log_text.delete("1.0", "end")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.app.catalog_dir() / f"scan_log_{timestamp}.txt"
        try:
            self._log_file = log_path.open("w", encoding="utf-8")
            self._log_file_path = log_path
        except Exception:
            self._log_file = None
            self._log_file_path = None
        self._enqueue(f"Logging to: {log_path}")

        t = threading.Thread(
            target=self._scan_thread, args=(cmds, self.app.abletools_dir), daemon=True
        )
        t.start()

    def cancel_scan(self) -> None:
        if self._proc is None:
            return
        self._stop_requested = True
        try:
            self._proc.terminate()
        except Exception:
            pass


class ScanView(tk.Frame):
    def __init__(self, master: tk.Misc, app: "AbletoolsUI") -> None:
        super().__init__(master, bg=BG)
        self.app = app
        self._build()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text="Scan", font=TITLE_FONT, fg=TEXT, bg=BG).pack(
            side="left"
        )
        tk.Label(
            header,
            text="Automate catalog updates with live stats.",
            font=BODY_FONT,
            fg=MUTED,
            bg=BG,
        ).pack(side="left", padx=(12, 0))

        panel = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        panel.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.scan_panel = ScanPanel(panel, self.app)
        self.scan_panel.pack(fill="both", expand=True)


class RamifyPanel(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg=BG)
        self.path_var = tk.StringVar(value="")
        self.dry_var = tk.BooleanVar(value=True)
        self.inplace_var = tk.BooleanVar(value=True)
        self.rec_var = tk.BooleanVar(value=False)
        self._build()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text="Tools", font=TITLE_FONT, fg=TEXT, bg=BG).pack(
            side="left"
        )
        tk.Label(
            header,
            text="Automations and utilities.",
            font=BODY_FONT,
            fg=MUTED,
            bg=BG,
        ).pack(side="left", padx=(12, 0))

        card = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        tool_header = tk.Frame(card, bg=PANEL)
        tool_header.pack(fill="x", padx=16, pady=(12, 2))
        tool_title = tk.Frame(tool_header, bg=PANEL)
        tool_title.pack(side="left")

        tk.Label(
            tool_title,
            text="RAMify Ableton Sets",
            font=H2_FONT,
            fg=TEXT,
            bg=PANEL,
        ).pack(anchor="w")
        tk.Label(
            tool_title,
            text="Flip AudioClip RAM flags for faster playback.",
            font=BODY_FONT,
            fg=MUTED,
            bg=PANEL,
        ).pack(anchor="w")

        ram_gif_slot = tk.Label(tool_header, bg=PANEL, width=120, height=70)
        ram_gif_slot.pack(side="right")
        ram_gif_path = ABLETOOLS_DIR / "resources" / "ram.gif"
        self.ram_gif = AnimatedGif(ram_gif_slot, ram_gif_path, delay_ms=70, subsample=2)
        if self.ram_gif.frames:
            ram_gif_slot.configure(image=self.ram_gif.frames[0])

        target_row = tk.Frame(card, bg=PANEL)
        target_row.pack(fill="x", padx=16, pady=(10, 4))

        tk.Entry(
            target_row,
            textvariable=self.path_var,
            font=BODY_FONT,
            bg=PANEL_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        ).pack(side="left", fill="x", expand=True)

        ttk.Button(
            target_row,
            text="Choose File",
            command=self.choose_file,
            style="Accent.TButton",
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            target_row,
            text="Choose Folder",
            command=self.choose_folder,
            style="Ghost.TButton",
        ).pack(side="left", padx=(8, 0))

        opts = tk.Frame(card, bg=PANEL)
        opts.pack(fill="x", padx=16, pady=(6, 0))
        tk.Checkbutton(
            opts,
            text="Dry run (no writes)",
            variable=self.dry_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=BG_NAV,
        ).pack(side="left")
        tk.Checkbutton(
            opts,
            text="In-place (create .bak)",
            variable=self.inplace_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=BG_NAV,
        ).pack(side="left", padx=(18, 0))
        tk.Checkbutton(
            opts,
            text="Recursive (if folder)",
            variable=self.rec_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=BG_NAV,
        ).pack(side="left", padx=(18, 0))

        actions = tk.Frame(card, bg=PANEL)
        actions.pack(fill="x", padx=16, pady=(10, 0))
        self.run_btn = ttk.Button(
            actions,
            text="Run RAMify",
            command=self.run_clicked,
            style="Accent.TButton",
        )
        self.run_btn.pack(side="left")
        ttk.Button(
            actions,
            text="Clear Log",
            command=self.clear_log,
            style="Ghost.TButton",
        ).pack(side="left", padx=(8, 0))

        self.log = tk.Text(
            card,
            wrap="word",
            bg=PANEL_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            height=14,
            font=MONO_FONT,
        )
        self.log.pack(fill="both", expand=True, padx=16, pady=(12, 16))

        self._log("Ready. Tip: start with Dry run")

    def _log(self, msg: str) -> None:
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def clear_log(self) -> None:
        self.log.delete("1.0", "end")

    def choose_file(self) -> None:
        p = filedialog.askopenfilename(
            title="Choose Ableton set/clip",
            filetypes=[("Ableton Live", "*.als *.alc"), ("All files", "*.*")],
        )
        if p:
            self.path_var.set(p)

    def choose_folder(self) -> None:
        p = filedialog.askdirectory(title="Choose folder containing .als/.alc files")
        if p:
            self.path_var.set(p)

    def run_clicked(self) -> None:
        p = self.path_var.get().strip()
        if not p:
            messagebox.showerror(
                "Missing target", "Choose a .als/.alc file or a folder first."
            )
            return

        target = Path(p).expanduser()
        if not target.exists():
            messagebox.showerror("Not found", str(target))
            return

        dry = bool(self.dry_var.get())
        inplace = bool(self.inplace_var.get())
        recursive = bool(self.rec_var.get())

        mode = "DRY RUN" if dry else ("IN-PLACE" if inplace else "WRITE .ram.* COPIES")

        self.run_btn.configure(state="disabled")
        self.ram_gif.start()
        self._log("")
        self._log(f"=== Running: {mode} ===")
        self._log(f"Target: {target}")
        self._log(f"Recursive: {recursive}")
        self._log("")

        def worker() -> None:
            try:
                total_files = total_audio = total_flips = failed = 0
                for f in iter_targets(target, recursive):
                    total_files += 1
                    try:
                        audio_seen, flips, wrote = process_file(f, inplace, dry)
                        total_audio += audio_seen
                        total_flips += flips
                        action = "DRY" if dry else ("INPLACE" if inplace else "OUT")
                        if wrote:
                            self.after(
                                0,
                                self._log,
                                f"[{action}] {f} | AudioClips={audio_seen} | RamFlips={flips} | wrote={wrote}",
                            )
                        else:
                            self.after(
                                0,
                                self._log,
                                f"[{action}] {f} | AudioClips={audio_seen} | RamFlips={flips}",
                            )
                    except Exception as e:
                        failed += 1
                        self.after(0, self._log, f"[FAIL] {f} | {e}")

                self.after(0, self._log, "")
                self.after(
                    0,
                    self._log,
                    f"Done. Files={total_files} Failed={failed} AudioClips={total_audio} RamFlips={total_flips}",
                )
                if dry and total_flips > 0:
                    self.after(
                        0,
                        self._log,
                        "Re-run with Dry run unchecked to apply changes (in-place creates .bak).",
                    )
            except Exception:
                tb = traceback.format_exc()
                self.after(0, self._log, tb)
            finally:
                self.after(0, self._finish_run)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_run(self) -> None:
        self.run_btn.configure(state="normal")
        self.ram_gif.stop()


class SettingsPanel(tk.Frame):
    def __init__(self, master: tk.Misc, app: "AbletoolsUI") -> None:
        super().__init__(master, bg=BG)
        self.app = app
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text="Settings", font=TITLE_FONT, fg=TEXT, bg=BG).pack(
            side="left"
        )

        card = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        tk.Label(
            card,
            text="Maintenance",
            font=H2_FONT,
            fg=TEXT,
            bg=PANEL,
        ).pack(anchor="w", padx=16, pady=(16, 8))

        btns = tk.Frame(card, bg=PANEL)
        btns.pack(anchor="w", padx=16, pady=(0, 16))
        ttk.Button(
            btns,
            text="Run Analytics",
            style="Accent.TButton",
            command=self.app.run_analytics,
        ).pack(side="left")
        ttk.Button(
            btns,
            text="Optimize DB",
            style="Ghost.TButton",
            command=self.app.run_maintenance,
        ).pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="")
        tk.Label(
            card,
            textvariable=self.status_var,
            font=BODY_FONT,
            fg=MUTED,
            bg=PANEL,
        ).pack(anchor="w", padx=16, pady=(0, 16))


class PreferencesPanel(tk.Frame):
    def __init__(self, master: tk.Misc, app: "AbletoolsUI") -> None:
        super().__init__(master, bg=BG)
        self.app = app
        self.show_raw_var = tk.BooleanVar(value=False)
        self._build()

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text="Preferences", font=TITLE_FONT, fg=TEXT, bg=BG).pack(
            side="left"
        )
        ttk.Checkbutton(
            header,
            text="Show raw",
            variable=self.show_raw_var,
            command=self.refresh,
            style="Ghost.TButton",
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            header,
            text="Refresh",
            command=self.refresh,
            style="Accent.TButton",
        ).pack(side="right")

        self.status_var = tk.StringVar(value="")
        tk.Label(
            self,
            textvariable=self.status_var,
            font=BODY_FONT,
            fg=WARN,
            bg=BG,
        ).pack(anchor="w", padx=16, pady=(0, 6))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        tk.Label(left, text="Sources", font=H2_FONT, fg=TEXT, bg=PANEL).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )
        self.sources = ttk.Treeview(left, columns=("kind", "source"), show="headings")
        self.sources.heading("kind", text="Kind")
        self.sources.heading("source", text="Source")
        self.sources.column("kind", width=90, anchor="center")
        self.sources.column("source", width=420)
        self.sources.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.sources.bind("<<TreeviewSelect>>", self._on_select)

        right = tk.Frame(
            body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        tk.Label(right, text="Parsed JSON", font=H2_FONT, fg=TEXT, bg=PANEL).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )
        self.payload = tk.Text(
            right,
            bg=PANEL,
            fg=MUTED,
            insertbackground=TEXT,
            relief="flat",
            font=MONO_FONT,
        )
        self.payload.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.payload.configure(state="disabled")

    def refresh(self) -> None:
        self.sources.delete(*self.sources.get_children())
        self._set_payload("No preferences loaded.")
        self._set_status("")
        db_path = self.app.resolve_prefs_db_path()
        if not db_path or not db_path.exists():
            self._set_payload("Database not found. Run a scan or prefs refresh.")
            return
        try:
            with sqlite3.connect(db_path) as conn:
                for row in conn.execute(
                    "SELECT kind, source, mtime FROM ableton_prefs ORDER BY mtime DESC"
                ):
                    self.sources.insert("", "end", values=(row[0], row[1]))
        except sqlite3.OperationalError as exc:
            self._set_payload(f"Preferences table missing: {exc}")
            self._set_status(str(exc))
            self.app.log_ui_error(f"prefs refresh: {exc}")
            return
        except Exception as exc:
            self._set_payload(f"Failed to load preferences: {exc}")
            self._set_status(str(exc))
            self.app.log_ui_error(f"prefs refresh: {exc}")
            return

        items = self.sources.get_children()
        if items:
            self.sources.selection_set(items[0])
            self._on_select(None)

    def _set_payload(self, text: str) -> None:
        self.payload.configure(state="normal")
        self.payload.delete("1.0", "end")
        self.payload.insert("end", text)
        self.payload.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _on_select(self, _event: object) -> None:
        selection = self.sources.selection()
        if not selection:
            return
        values = self.sources.item(selection[0], "values")
        if not values:
            return
        kind, source = values[0], values[1]
        db_path = self.app.resolve_prefs_db_path()
        if not db_path or not db_path.exists():
            self._set_payload("Database not found.")
            return
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT payload_json FROM ableton_prefs WHERE kind = ? AND source = ?",
                    (kind, source),
                ).fetchone()
        except Exception as exc:
            self._set_payload(f"Failed to load payload: {exc}")
            self._set_status(str(exc))
            self.app.log_ui_error(f"prefs select: {exc}")
            return
        if not row:
            self._set_payload("No payload found.")
            return
        payload_text = row[0]
        if self.show_raw_var.get():
            limit = 20000
            if len(payload_text) > limit:
                payload_text = (
                    payload_text[:limit]
                    + "\n\n... (truncated, enable export if you need full payload)"
                )
            self._set_payload(payload_text)
            return
        try:
            payload = json.loads(payload_text)
        except Exception as exc:
            self._set_payload(f"Failed to parse JSON: {exc}")
            self._set_status(str(exc))
            self.app.log_ui_error(f"prefs parse: {exc}")
            return

        summary = self._summarize_payload(kind, source, payload)
        self._set_payload(summary)

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

                key_fields = [
                    "UserLibraryPath",
                    "LibraryPath",
                    "ProjectPath",
                    "LastProjectPath",
                    "PacksFolder",
                    "VstPlugInCustomFolder",
                    "Vst3PlugInCustomFolder",
                    "AuPlugInCustomFolder",
                ]
                for key in key_fields:
                    if key in values and values[key]:
                        first_val = values[key][0]
                        if self._looks_like_path(first_val):
                            lines.append(f"{key}: {first_val}")

                hints = []
                for key in values:
                    if "Folder" in key or "Path" in key:
                        for val in values.get(key, []):
                            if self._looks_like_path(val):
                                hints.append(val)
                    if len(hints) >= 5:
                        break
                if hints:
                    lines.append("Example paths:")
                    lines.extend(f" - {item}" for item in hints[:5])

        return "\n".join(lines)

    def _looks_like_path(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        if not value or any(ord(ch) < 32 for ch in value):
            return False
        if not (value.startswith("/") or value.startswith("~") or value[1:3] == ":\\"):
            return False
        path = Path(value).expanduser()
        return path.exists()

class AbletoolsUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Abletools")
        self.geometry("1080x720")
        self.configure(bg=BG)

        self.abletools_dir = ABLETOOLS_DIR
        self.active_root: Optional[Path] = None
        self.current_scope = "live_recordings"
        self.log_path: Optional[Path] = None
        self.logger = self._setup_logging()

        self._nav_buttons: dict[str, tk.Button] = {}
        self._views: dict[str, tk.Frame] = {}
        self._icon_img: Optional[tk.PhotoImage] = None

        self._style()
        self._build()
        self._set_app_icon()
        self._refresh_prefs_cache()
        self._init_active_root()
        self._scan_app_log()

    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("TFrame", background=BG)
        style.configure("TLabelFrame", background=PANEL, foreground=TEXT, borderwidth=1)
        style.configure("TLabelFrame.Label", background=PANEL, foreground=TEXT)
        style.configure(
            "TButton",
            font=BODY_FONT,
            foreground=TEXT,
            background=PANEL_ALT,
            borderwidth=1,
            focusthickness=1,
            focuscolor=ACCENT_SOFT,
        )
        style.map(
            "TButton",
            background=[("active", "#1b2736")],
            foreground=[("active", TEXT)],
        )
        style.configure(
            "Accent.TButton",
            foreground="#001014",
            background=ACCENT,
            borderwidth=1,
            focusthickness=1,
            focuscolor=ACCENT_2,
            padding=(10, 6),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_2)],
            foreground=[("active", "#001014")],
        )
        style.configure(
            "Ghost.TButton",
            foreground=TEXT,
            background=BG_NAV,
            borderwidth=1,
            focusthickness=1,
            focuscolor=ACCENT_SOFT,
            padding=(10, 6),
        )
        style.map(
            "Ghost.TButton",
            background=[("active", "#0f1a26")],
            foreground=[("active", TEXT)],
        )
        style.configure(
            "Nav.TButton",
            foreground=MUTED,
            background=BG_NAV,
            borderwidth=1,
            focusthickness=1,
            focuscolor=ACCENT_SOFT,
            padding=(6, 10),
        )
        style.map(
            "Nav.TButton",
            background=[("active", "#0f1a26")],
            foreground=[("active", TEXT)],
        )
        style.configure(
            "NavActive.TButton",
            foreground="#001014",
            background=ACCENT_2,
            borderwidth=1,
            focusthickness=1,
            focuscolor=ACCENT,
            padding=(6, 10),
        )
        style.map(
            "NavActive.TButton",
            background=[("active", ACCENT)],
            foreground=[("active", "#001014")],
        )
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map(
            "TCheckbutton",
            foreground=[("active", TEXT)],
            background=[("active", PANEL)],
        )

    def _build(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        nav = tk.Frame(self, bg=BG_NAV, width=84)
        nav.grid(row=0, column=0, sticky="ns")
        nav.grid_propagate(False)

        main = tk.Frame(self, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self._build_nav(nav)
        self._build_topbar(main)

        content = tk.Frame(main, bg=BG)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._views["dashboard"] = DashboardPanel(content, self)
        self._views["scan"] = ScanView(content, self)
        self._views["catalog"] = CatalogPanel(content, self)
        self._views["tools"] = RamifyPanel(content)
        self._views["preferences"] = PreferencesPanel(content, self)
        self._views["settings"] = SettingsPanel(content, self)

        for view in self._views.values():
            view.grid(row=0, column=0, sticky="nsew")

        self.show_view("dashboard")

    def _build_nav(self, nav: tk.Frame) -> None:
        logo = self._load_nav_logo(target_width=96)
        if logo is not None:
            tk.Label(nav, image=logo, bg=BG_NAV).pack(pady=(14, 12))
        else:
            tk.Label(
                nav, text="A", font=("Menlo", 18, "bold"), fg=ACCENT, bg=BG_NAV
            ).pack(pady=(16, 4))
            tk.Label(
                nav,
                text="core",
                font=("Menlo", 9, "bold"),
                fg=ACCENT_2,
                bg=BG_NAV,
            ).pack(pady=(0, 12))

        tk.Frame(nav, bg=ACCENT_SOFT, height=2).pack(fill="x", padx=10, pady=(0, 10))

        for key, label in [
            ("dashboard", "Dash"),
            ("scan", "Scan"),
            ("catalog", "Catalog"),
            ("tools", "Tools"),
            ("preferences", "Prefs"),
            ("settings", "Settings"),
        ]:
            btn = ttk.Button(
                nav,
                text=label.upper(),
                command=lambda k=key: self.show_view(k),
                style="Nav.TButton",
            )
            btn.pack(fill="x", padx=8, pady=4)
            self._nav_buttons[key] = btn

    def _build_topbar(self, main: tk.Frame) -> None:
        top = tk.Frame(main, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        tk.Label(top, text="Abletools", font=TITLE_FONT, fg=TEXT, bg=BG).grid(
            row=0, column=0, sticky="w", padx=16, pady=10
        )

        self.active_root_var = tk.StringVar(value="No active root")
        tk.Label(top, textvariable=self.active_root_var, font=BODY_FONT, fg=MUTED, bg=BG).grid(
            row=0, column=1, sticky="w"
        )

        ttk.Button(
            top,
            text="DB Folder",
            command=self._open_db_location,
            style="Ghost.TButton",
        ).grid(row=0, column=2, padx=8)
        ttk.Button(
            top,
            text="Scan Tab",
            command=lambda: self.show_view("scan"),
            style="Accent.TButton",
        ).grid(row=0, column=3, padx=(0, 16))

        tk.Frame(top, bg=ACCENT_SOFT, height=2).grid(
            row=1, column=0, columnspan=4, sticky="ew"
        )

    def _set_app_icon(self) -> None:
        icon_path = ABLETOOLS_DIR / "resources" / "abletools_icon.png"
        fallback_path = (
            ABLETOOLS_DIR
            / "resources"
            / "ChatGPT Image Jan 18, 2026, 02_19_59 AM.png"
        )
        path = icon_path if icon_path.exists() else fallback_path
        if not path.exists():
            return
        try:
            self._icon_img = tk.PhotoImage(file=str(path))
            self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _load_logo(self, target_width: int) -> Optional[tk.PhotoImage]:
        if not hasattr(self, "_logo_cache"):
            self._logo_cache = {}
        cache_key = f"w{target_width}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        png_path = ABLETOOLS_DIR / "resources" / "abletools_logo.png"
        svg_path = ABLETOOLS_DIR / "resources" / "abletools_logo.svg"
        img = None

        if png_path.exists():
            img = tk.PhotoImage(file=str(png_path))
        elif svg_path.exists():
            try:
                import cairosvg  # type: ignore

                png_bytes = cairosvg.svg2png(bytestring=svg_path.read_bytes())
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    tmp.write(png_bytes)
                    tmp.flush()
                    img = tk.PhotoImage(file=tmp.name)
            except Exception:
                img = None

        if img is None and png_path.exists():
            img = tk.PhotoImage(file=str(png_path))

        if img is None:
            return None

        width = max(1, img.width())
        scale = max(1, width // target_width)
        if scale > 1:
            img = img.subsample(scale, scale)

        self._logo_cache[cache_key] = img
        return img

    def _load_nav_logo(self, target_width: int) -> Optional[tk.PhotoImage]:
        if not hasattr(self, "_logo_cache"):
            self._logo_cache = {}
        cache_key = f"nav{target_width}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        mark_path = ABLETOOLS_DIR / "resources" / "abletools_mark.png"
        if not mark_path.exists():
            return None
        img = tk.PhotoImage(file=str(mark_path))

        width = max(1, img.width())
        scale = max(1, width // target_width)
        if scale > 1:
            img = img.subsample(scale, scale)

        self._logo_cache[cache_key] = img
        return img

    def show_view(self, name: str) -> None:
        view = self._views.get(name)
        if not view:
            return
        self._log_event("NAV", f"show_view={name}")
        view.tkraise()
        for key, btn in self._nav_buttons.items():
            if key == name:
                btn.configure(style="NavActive.TButton")
            else:
                btn.configure(style="Nav.TButton")

        if name == "dashboard":
            self.refresh_dashboard()
        elif name == "catalog":
            catalog = self._views.get("catalog")
            if isinstance(catalog, CatalogPanel):
                catalog.refresh()
        elif name == "preferences":
            prefs = self._views.get("preferences")
            if isinstance(prefs, PreferencesPanel):
                try:
                    prefs.refresh()
                except Exception as exc:
                    messagebox.showerror("Preferences", f"Failed to load: {exc}")
                    self._log_event("ERROR", f"preferences refresh: {exc}")

    def refresh_dashboard(self) -> None:
        dashboard = self._views.get("dashboard")
        if isinstance(dashboard, DashboardPanel):
            dashboard.refresh()

    def scan_script_path(self) -> Path:
        return self.abletools_dir / "abletools_scan.py"

    def catalog_dir(self) -> Path:
        return self.abletools_dir / ".abletools_catalog"

    def default_scan_root(self) -> Path:
        cache_dir = self.catalog_dir()
        suggested = suggest_scan_root(cache_dir)
        if suggested:
            return suggested
        return self.abletools_dir.parent

    def user_library_root(self) -> Optional[Path]:
        cache_dir = self.catalog_dir()
        key_paths = get_key_paths(cache_dir)
        for key in ("UserLibraryPath", "LibraryPath"):
            for val in key_paths.get(key, []):
                path = Path(val).expanduser()
                if path.exists() and path.is_dir():
                    return path
        return None

    def preferences_root(self) -> Optional[Path]:
        cache_dir = self.catalog_dir()
        return get_preferences_folder(cache_dir)

    def set_active_root(self, root: Path) -> None:
        self.active_root = root
        self.active_root_var.set(f"Active root: {root}")

    def set_current_scope(self, scope: str) -> None:
        if scope in {"live_recordings", "user_library", "preferences", "all"}:
            self.current_scope = scope

    def resolve_db_path(self) -> Optional[Path]:
        if self.active_root:
            return self.active_root / ".abletools_catalog" / "abletools_catalog.sqlite"
        return self.catalog_dir() / "abletools_catalog.sqlite"

    def resolve_catalog_db_path(self) -> Optional[Path]:
        return self.catalog_dir() / "abletools_catalog.sqlite"

    def resolve_prefs_db_path(self) -> Optional[Path]:
        return self.catalog_dir() / "abletools_catalog.sqlite"

    def resolve_scan_summary(self) -> Optional[Path]:
        if self.active_root:
            return self.active_root / ".abletools_catalog" / "scan_summary.json"
        fallback = self.abletools_dir / ".abletools_catalog" / "scan_summary.json"
        return fallback if fallback.exists() else None

    def load_catalog_stats(self) -> CatalogStats:
        db_path = self.resolve_catalog_db_path()
        stats = CatalogStats(last_scan=_now_iso())
        if not db_path or not db_path.exists():
            return stats
        try:
            with sqlite3.connect(db_path) as conn:
                stats.file_count = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM file_index "
                    "UNION ALL SELECT COUNT(*) FROM file_index_user_library "
                    "UNION ALL SELECT COUNT(*) FROM file_index_preferences)"
                ).fetchone()[0] or 0
                stats.doc_count = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM ableton_docs "
                    "UNION ALL SELECT COUNT(*) FROM ableton_docs_user_library "
                    "UNION ALL SELECT COUNT(*) FROM ableton_docs_preferences)"
                ).fetchone()[0] or 0
                stats.refs_count = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM refs_graph "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_user_library "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_preferences)"
                ).fetchone()[0] or 0
                stats.missing_refs = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM refs_graph WHERE ref_exists = 0 "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_user_library WHERE ref_exists = 0 "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_preferences WHERE ref_exists = 0)"
                ).fetchone()[0] or 0
        except Exception:
            return stats
        return stats

    def load_top_devices(self, limit: int = 8) -> list[str]:
        db_path = self.resolve_catalog_db_path()
        if not db_path or not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT device_name, usage_count FROM device_usage "
                    "WHERE scope != 'preferences' "
                    "ORDER BY usage_count DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [f"{name} ({count})" for name, count in rows]
        except Exception:
            return []

    def load_top_chains(self, limit: int = 6) -> list[str]:
        db_path = self.resolve_catalog_db_path()
        if not db_path or not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT chain, usage_count FROM device_chain_stats "
                    "WHERE scope != 'preferences' "
                    "ORDER BY usage_count DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [f"{chain} ({count})" for chain, count in rows]
        except Exception:
            return []

    def load_missing_refs_paths(self, limit: int = 6) -> list[str]:
        db_path = self.resolve_catalog_db_path()
        if not db_path or not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT ref_parent, missing_count FROM missing_refs_by_path "
                    "WHERE scope != 'preferences' "
                    "ORDER BY missing_count DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [f"{path} ({count})" for path, count in rows]
        except Exception:
            return []

    def _open_db_location(self) -> None:
        db_path = self.resolve_catalog_db_path()
        if not db_path or not db_path.exists():
            messagebox.showinfo("Database", "No database found yet.")
            return
        folder = db_path.parent
        try:
            self.tk.call("exec", "open", str(folder))
        except Exception:
            messagebox.showwarning("Could not open folder", str(folder))

    def refresh_catalog_db(self) -> None:
        catalog_dir = self.catalog_dir()
        db_script = self.abletools_dir / "abletools_catalog_db.py"
        if not db_script.exists():
            messagebox.showerror("Catalog", "Database script not found.")
            self._log_event("ERROR", "refresh_catalog_db: script missing")
            return
        catalog_dir.mkdir(parents=True, exist_ok=True)
        self._log_event("DB", f"refresh_catalog_db: {catalog_dir}")
        try:
            proc = subprocess.run(
                [sys.executable, str(db_script), str(catalog_dir), "--append"],
                cwd=str(self.abletools_dir),
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            messagebox.showerror("Catalog", f"Failed to update DB:\n{exc}")
            self._log_event("ERROR", f"refresh_catalog_db: {exc}")
            return
        if proc.returncode != 0:
            messagebox.showerror(
                "Catalog", proc.stderr.strip() or "Database update failed."
            )
            self._log_event("ERROR", f"refresh_catalog_db: {proc.stderr.strip()}")

    def run_analytics(self) -> None:
        db_path = self.resolve_catalog_db_path()
        if not db_path or not db_path.exists():
            messagebox.showinfo("Analytics", "No database found yet.")
            self._log_event("ANALYTICS", "db missing")
            return
        self.refresh_catalog_db()
        analytics = self.abletools_dir / "abletools_analytics.py"
        if not analytics.exists():
            messagebox.showerror("Analytics", f"Missing analytics script:\n{analytics}")
            self._log_event("ERROR", f"run_analytics: script missing {analytics}")
            return
        try:
            proc = subprocess.run(
                [sys.executable, str(analytics), str(db_path)],
                cwd=str(self.abletools_dir),
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            messagebox.showerror("Analytics", f"Failed to run analytics:\n{exc}")
            self._log_event("ERROR", f"run_analytics: {exc}")
            return
        if proc.returncode != 0:
            messagebox.showerror("Analytics", proc.stderr.strip() or "Analytics failed.")
            self._log_event("ERROR", f"run_analytics: {proc.stderr.strip()}")
            return
        self._log_event("ANALYTICS", "completed")
        messagebox.showinfo("Analytics", "Analytics updated.")
        self.refresh_dashboard()

    def run_maintenance(self) -> None:
        db_path = self.resolve_catalog_db_path()
        if not db_path or not db_path.exists():
            messagebox.showinfo("Maintenance", "No database found yet.")
            self._log_event("MAINTENANCE", "db missing")
            return
        maintenance = self.abletools_dir / "abletools_maintenance.py"
        if not maintenance.exists():
            messagebox.showerror("Maintenance", f"Missing maintenance script:\n{maintenance}")
            self._log_event("ERROR", f"run_maintenance: script missing {maintenance}")
            return
        try:
            proc = subprocess.run(
                [sys.executable, str(maintenance), str(db_path), "--analyze", "--optimize"],
                cwd=str(self.abletools_dir),
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            messagebox.showerror("Maintenance", f"Failed to run maintenance:\n{exc}")
            self._log_event("ERROR", f"run_maintenance: {exc}")
            return
        if proc.returncode != 0:
            messagebox.showerror("Maintenance", proc.stderr.strip() or "Maintenance failed.")
            self._log_event("ERROR", f"run_maintenance: {proc.stderr.strip()}")
            return
        self._log_event("MAINTENANCE", "completed")
        messagebox.showinfo("Maintenance", "Database optimized.")

    def _refresh_prefs_cache(self) -> None:
        catalog_dir = self.abletools_dir / ".abletools_catalog"
        db_script = self.abletools_dir / "abletools_catalog_db.py"
        if not db_script.exists():
            return
        catalog_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.resolve_prefs_db_path()
        cmd = [
            sys.executable,
            str(db_script),
            str(catalog_dir),
            "--append",
            "--prefs-only",
            "--db",
            str(db_path),
        ]
        try:
            subprocess.run(
                cmd,
                cwd=str(self.abletools_dir),
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

    def ensure_catalog_db(self) -> None:
        catalog_dir = self.catalog_dir()
        db_path = self.resolve_catalog_db_path()
        if not db_path:
            return
        if db_path.exists():
            return
        db_script = self.abletools_dir / "abletools_catalog_db.py"
        if not db_script.exists():
            return
        catalog_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            str(db_script),
            str(catalog_dir),
            "--append",
            "--prefs-only",
            "--db",
            str(db_path),
        ]
        try:
            subprocess.run(
                cmd,
                cwd=str(self.abletools_dir),
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            self.log_ui_error(f"ensure_catalog_db: {exc}")

    def _init_active_root(self) -> None:
        if self.active_root is None:
            self.set_active_root(self.default_scan_root())

    def log_ui_error(self, message: str) -> None:
        self._log_event("UI_ERROR", message)

    def _setup_logging(self) -> logging.Logger:
        cache_dir = self.catalog_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = cache_dir / "abletools.log"
        logger = logging.getLogger("abletools")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.FileHandler(self.log_path, encoding="utf-8")
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.info("App start")
        return logger

    def _log_event(self, kind: str, message: str) -> None:
        if self.logger:
            self.logger.info("%s: %s", kind, message)

    def _scan_app_log(self) -> None:
        if not self.log_path or not self.log_path.exists():
            return
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        recent = [line for line in lines[-200:] if "ERROR" in line or "UI_ERROR" in line]
        if recent:
            self._log_event("LOG_SCAN", f"Found {len(recent)} recent error lines.")


if __name__ == "__main__":
    AbletoolsUI().mainloop()
