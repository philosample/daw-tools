from __future__ import annotations

import json
import os
import plistlib
import re
import time
from pathlib import Path
from typing import Any

CACHE_FILENAME = "prefs_cache.json"
PLUGIN_EXTS = {".component", ".vst", ".vst3"}


def _prefs_root() -> Path:
    return Path.home() / "Library" / "Preferences" / "Ableton"


def _load_cache(cache_dir: Path) -> dict:
    cache_path = cache_dir / CACHE_FILENAME
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache_dir: Path, data: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / CACHE_FILENAME
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _find_latest(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    candidates = list(root.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _search_preferences() -> dict:
    root = _prefs_root()
    prefs = _find_latest(root, "Live */Preferences.cfg") or _find_latest(
        root, "Live*/Preferences.cfg"
    )
    options = None
    if prefs and prefs.parent.exists():
        options = _find_latest(prefs.parent, "Options.txt")
    if not options:
        options = _find_latest(root, "Live */Options.txt") or _find_latest(
            root, "Live*/Options.txt"
        )
    return {
        "prefs_path": str(prefs) if prefs else "",
        "options_path": str(options) if options else "",
    }


def discover_preferences(cache_dir: Path) -> dict:
    cache = _load_cache(cache_dir)
    prefs_path = Path(cache.get("prefs_path", "")) if cache.get("prefs_path") else None
    options_path = (
        Path(cache.get("options_path", "")) if cache.get("options_path") else None
    )

    if prefs_path and prefs_path.exists():
        return cache

    found = _search_preferences()
    prefs_path = Path(found.get("prefs_path", "")) if found.get("prefs_path") else None
    options_path = (
        Path(found.get("options_path", "")) if found.get("options_path") else None
    )
    cache = {
        "prefs_path": str(prefs_path) if prefs_path else "",
        "options_path": str(options_path) if options_path else "",
        "updated_at": int(time.time()),
    }
    if prefs_path and prefs_path.exists():
        cache["prefs_mtime"] = int(prefs_path.stat().st_mtime)
    if options_path and options_path.exists():
        cache["options_mtime"] = int(options_path.stat().st_mtime)
    _save_cache(cache_dir, cache)
    return cache


def get_preferences_folder(cache_dir: Path) -> Path | None:
    cache = discover_preferences(cache_dir)
    prefs_path = Path(cache.get("prefs_path", "")) if cache.get("prefs_path") else None
    if prefs_path and prefs_path.exists():
        return prefs_path.parent
    return None


def get_key_paths(cache_dir: Path) -> dict[str, list[str]]:
    cache = discover_preferences(cache_dir)
    prefs_path = Path(cache.get("prefs_path", "")) if cache.get("prefs_path") else None
    if not prefs_path or not prefs_path.exists():
        return {}
    data = parse_preferences(prefs_path)
    values = data.get("values", {})
    keys = [
        "UserLibraryPath",
        "LibraryPath",
        "ProjectPath",
        "LastProjectPath",
        "PacksFolder",
        "VstPlugInCustomFolder",
        "Vst3PlugInCustomFolder",
        "AuPlugInCustomFolder",
    ]
    return {k: values.get(k, []) for k in keys if values.get(k)}


def _default_plugin_dirs() -> list[Path]:
    return [
        Path("/Library/Audio/Plug-Ins/Components"),
        Path("/Library/Audio/Plug-Ins/VST"),
        Path("/Library/Audio/Plug-Ins/VST3"),
        Path.home() / "Library" / "Audio" / "Plug-Ins" / "Components",
        Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST",
        Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST3",
    ]


def _parse_kv(line: str) -> tuple[str | None, str | None]:
    if "=" in line:
        key, value = line.split("=", 1)
        return key.strip(), value.strip()
    if "\t" in line:
        key, value = line.split("\t", 1)
        return key.strip(), value.strip()
    return None, None


def parse_preferences(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = []
    values: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append({"raw": raw, "kind": "blank"})
            continue
        if line.startswith("#") or line.startswith("//"):
            lines.append({"raw": raw, "kind": "comment"})
            continue
        key, value = _parse_kv(line)
        if key:
            values.setdefault(key, []).append(value or "")
            lines.append({"raw": raw, "kind": "kv", "key": key, "value": value})
        else:
            lines.append({"raw": raw, "kind": "text"})
    return {"raw": text, "lines": lines, "values": values}


def parse_options(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    options = []
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
        if line.startswith("-"):
            options.append(line)
    return {"raw": text, "options": options, "lines": lines}


def load_prefs_payloads(cache_dir: Path) -> list[dict[str, Any]]:
    cache = discover_preferences(cache_dir)
    payloads: list[dict[str, Any]] = []
    now_ts = int(time.time())

    prefs_path = Path(cache.get("prefs_path", "")) if cache.get("prefs_path") else None
    if prefs_path and prefs_path.exists():
        payloads.append(
            {
                "kind": "preferences",
                "source": str(prefs_path),
                "mtime": int(prefs_path.stat().st_mtime),
                "scanned_at": now_ts,
                "payload": parse_preferences(prefs_path),
            }
        )

    options_path = (
        Path(cache.get("options_path", "")) if cache.get("options_path") else None
    )
    if options_path and options_path.exists():
        payloads.append(
            {
                "kind": "options",
                "source": str(options_path),
                "mtime": int(options_path.stat().st_mtime),
                "scanned_at": now_ts,
                "payload": parse_options(options_path),
            }
        )

    return payloads


def _scan_plugin_dir(path: Path) -> list[dict[str, Any]]:
    plugins: list[dict[str, Any]] = []
    if not path.exists() or not path.is_dir():
        return plugins
    try:
        with os.scandir(path) as it:
            for entry in it:
                p = Path(entry.path)
                if p.suffix.lower() not in PLUGIN_EXTS:
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    continue
                info_plist = p / "Contents" / "Info.plist"
                meta: dict[str, Any] = {
                    "path": str(p),
                    "format": p.suffix.lower().lstrip("."),
                    "name": p.stem,
                }
                if info_plist.exists():
                    try:
                        data = plistlib.loads(info_plist.read_bytes())
                        meta.update(
                            {
                                "name": data.get("CFBundleName") or meta["name"],
                                "bundle_id": data.get("CFBundleIdentifier"),
                                "version": data.get("CFBundleShortVersionString")
                                or data.get("CFBundleVersion"),
                                "vendor": data.get("CFBundleGetInfoString"),
                            }
                        )
                    except Exception:
                        pass
                plugins.append(meta)
    except OSError:
        return plugins
    return plugins


def load_plugin_payloads(cache_dir: Path) -> list[dict[str, Any]]:
    cache = discover_preferences(cache_dir)
    prefs_path = Path(cache.get("prefs_path", "")) if cache.get("prefs_path") else None
    plugin_dirs = set(_default_plugin_dirs())
    if prefs_path and prefs_path.exists():
        data = parse_preferences(prefs_path)
        values = data.get("values", {})
        for key in (
            "VstPlugInCustomFolder",
            "Vst3PlugInCustomFolder",
            "AuPlugInCustomFolder",
        ):
            for val in values.get(key, []):
                if not val:
                    continue
                plugin_dirs.add(Path(val).expanduser())

    plugins: list[dict[str, Any]] = []
    for p in sorted(plugin_dirs):
        plugins.extend(_scan_plugin_dir(p))

    if not plugins:
        return []
    return [
        {
            "scope": "preferences",
            "scanned_at": int(time.time()),
            "plugins": plugins,
        }
    ]


def suggest_scan_root(cache_dir: Path) -> Path | None:
    cache = discover_preferences(cache_dir)
    prefs_path = Path(cache.get("prefs_path", "")) if cache.get("prefs_path") else None
    if not prefs_path or not prefs_path.exists():
        return None

    data = parse_preferences(prefs_path)
    values = data.get("values", {})
    raw = data.get("raw", "")
    candidates = []

    for key, vals in values.items():
        for val in vals:
            if "Live Recordings" in val:
                candidates.append(val)

    for key in ("UserLibraryPath", "LibraryPath", "ProjectPath", "LastProjectPath"):
        for val in values.get(key, []):
            candidates.append(val)

    if raw:
        for match in re.findall(r"(/Volumes/[^\\s\"']+|/Users/[^\\s\"']+)", raw):
            if "Live Recordings" in match:
                candidates.append(match)
            elif "Ableton" in match and "Live" in match:
                candidates.append(match)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists() and path.is_dir():
            return path
    return None
