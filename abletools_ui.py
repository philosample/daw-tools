#!/usr/bin/env python3
from __future__ import annotations

import gzip
import os
import queue
import shutil
import subprocess
import sys
import threading
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


SUPPORTED_EXTS = {".als", ".alc"}
ABLETOOLS_DIR = Path(__file__).resolve().parent


def is_gzip(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B


def read_als_like(path: Path) -> bytes:
    raw = path.read_bytes()
    return gzip.decompress(raw) if is_gzip(raw) else raw


def write_als_like(path: Path, xml_bytes: bytes) -> None:
    path.write_bytes(gzip.compress(xml_bytes))


def ensure_backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def iter_targets(root: Path, recursive: bool):
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_EXTS:
            yield root
        return
    if root.is_dir():
        if recursive:
            yield from (
                p
                for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
            )
        else:
            yield from (
                p
                for p in root.glob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
            )
        return
    raise FileNotFoundError(f"Not found: {root}")


def flip_ram_flags(xml_bytes: bytes):
    """
    Flip <Ram Value="..."> under <AudioClip> to true.
    Returns (new_xml_bytes, audio_clips_seen, ram_flips_done)
    """
    root = ET.fromstring(xml_bytes)

    def local(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    audio_clips_seen = 0
    flips = 0

    for elem in root.iter():
        if local(elem.tag) != "AudioClip":
            continue
        audio_clips_seen += 1
        for sub in elem.iter():
            if local(sub.tag) != "Ram":
                continue
            v = sub.attrib.get("Value")
            if v is None:
                continue
            if v.lower() != "true":
                sub.set("Value", "true")
                flips += 1

    new_xml = ET.tostring(root, encoding="utf-8", method="xml")
    return new_xml, audio_clips_seen, flips


def process_one(path: Path, in_place: bool, dry_run: bool):
    xml = read_als_like(path)
    new_xml, audio_seen, flips = flip_ram_flags(xml)

    if flips == 0 or dry_run:
        return audio_seen, flips, None  # None = no write

    if in_place:
        ensure_backup(path)
        write_als_like(path, new_xml)
        return audio_seen, flips, str(path)
    else:
        out = path.with_name(path.stem + ".ram" + path.suffix)
        write_als_like(out, new_xml)
        return audio_seen, flips, str(out)


class ScanPanel(ttk.LabelFrame):
    """
    Scan & Catalog panel:
    - Runs abletools_scan.py as a subprocess
    - Streams stdout/stderr into a log box
    - Supports cancel
    """

    def __init__(self, master, abletools_dir: str):
        super().__init__(master, text="Scan & Catalog", padding=10)
        self.abletools_dir = Path(abletools_dir)

        # Default scan root to the parent folder of the tool dir (more useful than scanning the tool itself)
        self.root_var = tk.StringVar(value=str(self.abletools_dir.parent))
        self.incremental_var = tk.BooleanVar(value=True)
        self.include_media_var = tk.BooleanVar(value=False)
        self.hash_var = tk.BooleanVar(value=False)

        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue[str] = queue.Queue()
        self._stop_requested = False

        self._build_ui()
        self._pump_queue()

    def _build_ui(self):
        # Row 0: root path + browse
        ttk.Label(self, text="Root folder:").grid(row=0, column=0, sticky="w")
        self.root_entry = ttk.Entry(self, textvariable=self.root_var, width=60)
        self.root_entry.grid(row=0, column=1, sticky="we", padx=(8, 8))
        ttk.Button(self, text="Browse…", command=self._browse).grid(
            row=0, column=2, sticky="e"
        )

        # Row 1: options
        opts = ttk.Frame(self)
        opts.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        ttk.Checkbutton(
            opts,
            text="Incremental (skip unchanged)",
            variable=self.incremental_var,
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts,
            text="Include media files",
            variable=self.include_media_var,
        ).grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts,
            text="Compute hashes (slow)",
            variable=self.hash_var,
        ).grid(row=0, column=2, sticky="w")

        # Row 2: buttons + status
        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, columnspan=3, sticky="we", pady=(10, 0))

        self.start_btn = ttk.Button(btns, text="Start Scan", command=self.start_scan)
        self.start_btn.pack(side="left")

        self.cancel_btn = ttk.Button(
            btns, text="Cancel", command=self.cancel_scan, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(btns, textvariable=self.status_var).pack(side="left", padx=(12, 0))

        # Row 3: log output
        # Keep this smaller so it doesn't crowd the main RAMify log in a 920x560 window.
        self.log = tk.Text(self, height=10, wrap="word")
        self.log.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        self.log.configure(state="disabled")

        # Grid stretch
        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

    def _browse(self):
        p = filedialog.askdirectory(
            initialdir=self.root_var.get() or str(self.abletools_dir.parent)
        )
        if p:
            self.root_var.set(p)

    def _append_log(self, line: str):
        self.log.configure(state="normal")
        self.log.insert("end", line)
        if not line.endswith("\n"):
            self.log.insert("end", "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _enqueue(self, s: str):
        self._q.put(s)

    def _pump_queue(self):
        # Pull queued log lines into the UI
        try:
            while True:
                s = self._q.get_nowait()
                self._append_log(s)
        except queue.Empty:
            pass
        self.after(100, self._pump_queue)

    def _scan_thread(self, cmd: list[str], cwd: Path):
        try:
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

            rc = self._proc.wait(timeout=5)
            if self._stop_requested:
                self._enqueue("Scan cancelled.")
                self.status_var.set("Cancelled")
            elif rc == 0:
                self._enqueue("Scan complete ✅")
                self.status_var.set("Done")
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

    def _set_running(self, running: bool):
        # UI-safe toggle (must be called from UI thread)

        def _apply():
            self.start_btn.configure(state="disabled" if running else "normal")
            self.cancel_btn.configure(state="normal" if running else "disabled")

        self.after(0, _apply)

    def start_scan(self):
        if self._proc is not None:
            return

        root = Path(self.root_var.get()).expanduser()
        if not root.exists() or not root.is_dir():
            messagebox.showerror("Scan", f"Root folder does not exist:\n{root}")
            return

        scan_script = self.abletools_dir / "abletools_scan.py"
        if not scan_script.exists():
            messagebox.showerror("Scan", f"Missing scanner script:\n{scan_script}")
            return

        cmd = [sys.executable, str(scan_script), str(root)]
        if self.incremental_var.get():
            cmd.append("--incremental")
        if self.include_media_var.get():
            cmd.append("--include-media")
        if self.hash_var.get():
            cmd.append("--hash")
        cmd.append("--verbose")

        self.status_var.set("Running…")
        self._set_running(True)

        t = threading.Thread(
            target=self._scan_thread, args=(cmd, self.abletools_dir), daemon=True
        )
        t.start()

    def cancel_scan(self):
        if self._proc is None:
            return
        self._stop_requested = True
        try:
            self._proc.terminate()
        except Exception:
            pass


class AbletoolsUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Abletools – RAMify Ableton Sets")
        self.geometry("920x560")

        self.path_var = tk.StringVar(value="")
        self.dry_var = tk.BooleanVar(value=True)
        self.inplace_var = tk.BooleanVar(value=True)
        self.rec_var = tk.BooleanVar(value=False)

        self._build()

    def _build(self):
        pad = 10

        header = tk.Frame(self)
        header.pack(fill="x", padx=pad, pady=(pad, 0))

        tk.Label(header, text="Target (.als/.alc file or folder):").pack(anchor="w")

        row = tk.Frame(header)
        row.pack(fill="x", pady=(6, 0))

        tk.Entry(row, textvariable=self.path_var).pack(
            side="left", fill="x", expand=True
        )
        tk.Button(row, text="Choose File…", command=self.choose_file).pack(
            side="left", padx=(8, 0)
        )
        tk.Button(row, text="Choose Folder…", command=self.choose_folder).pack(
            side="left", padx=(8, 0)
        )

        opts = tk.Frame(self)
        opts.pack(fill="x", padx=pad, pady=(pad, 0))

        tk.Checkbutton(opts, text="Dry run (no writes)", variable=self.dry_var).pack(
            side="left"
        )
        tk.Checkbutton(
            opts, text="In-place (create .bak)", variable=self.inplace_var
        ).pack(side="left", padx=(18, 0))
        tk.Checkbutton(opts, text="Recursive (if folder)", variable=self.rec_var).pack(
            side="left", padx=(18, 0)
        )

        actions = tk.Frame(self)
        actions.pack(fill="x", padx=pad, pady=(pad, 0))

        self.run_btn = tk.Button(actions, text="Run", command=self.run_clicked, width=12)
        self.run_btn.pack(side="left")

        tk.Button(actions, text="Clear Log", command=self.clear_log).pack(
            side="left", padx=(8, 0)
        )
        tk.Button(
            actions, text="Open Target Folder", command=self.open_target_folder
        ).pack(side="left", padx=(8, 0))

        # Log box
        log_frame = tk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=pad, pady=(pad, 6))

        self.log = tk.Text(log_frame, wrap="word")
        self.log.configure(height=14)
        self.log.pack(side="left", fill="both", expand=True)

        # Scrollbar: build the log fully BEFORE adding the scan panel below
        sb = tk.Scrollbar(log_frame, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set)

        # -------------------------------------------------
        # Scan & Catalog panel (runs abletools_scan.py)
        # -------------------------------------------------
        sep = ttk.Separator(self, orient="horizontal")
        sep.pack(fill="x", padx=pad, pady=(0, pad))

        scan_container = ttk.Frame(self)
        scan_container.pack(fill="both", expand=False, padx=pad, pady=(0, pad))

        self.scan_panel = ScanPanel(scan_container, str(ABLETOOLS_DIR))
        self.scan_panel.pack(fill="both", expand=True)

        self._log("Ready. Tip: start with Dry run ✅")

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def clear_log(self):
        self.log.delete("1.0", "end")

    def choose_file(self):
        p = filedialog.askopenfilename(
            title="Choose Ableton set/clip",
            filetypes=[("Ableton Live", "*.als *.alc"), ("All files", "*.*")],
        )
        if p:
            self.path_var.set(p)

    def choose_folder(self):
        p = filedialog.askdirectory(title="Choose folder containing .als/.alc files")
        if p:
            self.path_var.set(p)

    def open_target_folder(self):
        p = self.path_var.get().strip()
        if not p:
            messagebox.showinfo("No target", "Choose a file or folder first.")
            return
        path = Path(p).expanduser()
        folder = path if path.is_dir() else path.parent
        try:
            # macOS: "open" via subprocess-free Tk call
            self.tk.call("exec", "open", str(folder))
        except Exception:
            messagebox.showwarning("Could not open folder", str(folder))

    def run_clicked(self):
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

        # Guardrail: if dry run is on, in-place/out doesn't matter
        if dry:
            mode = "DRY RUN"
        else:
            mode = "IN-PLACE" if inplace else "WRITE .ram.* COPIES"

        self.run_btn.configure(state="disabled")
        self._log("")
        self._log(f"=== Running: {mode} ===")
        self._log(f"Target: {target}")
        self._log(f"Recursive: {recursive}")
        self._log("")

        def worker():
            try:
                total_files = total_audio = total_flips = failed = 0
                for f in iter_targets(target, recursive):
                    total_files += 1
                    try:
                        audio_seen, flips, wrote = process_one(f, inplace, dry)
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
                self.after(0, lambda: self.run_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    AbletoolsUI().mainloop()
