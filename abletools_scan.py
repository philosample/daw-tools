#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
import time
import wave
try:
    import aifc  # Python < 3.13
except ModuleNotFoundError:  # pragma: no cover - optional in newer Pythons
    aifc = None
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
import xml.etree.ElementTree as ET

# ------------------------------------------------------------
# Config: file types we care about
# ------------------------------------------------------------

ABLETON_DOC_EXTS = {".als", ".alc"}
ABLETON_ARTIFACT_EXTS = {".adg", ".adv", ".agr", ".alp"}  # racks/presets/grooves/packs
MEDIA_EXTS = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".ogg"}

DEFAULT_INDEX_EXTS = sorted(ABLETON_DOC_EXTS | ABLETON_ARTIFACT_EXTS)
SCOPES = {"live_recordings", "user_library", "preferences"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".DS_Store"}

# Ableton docs are typically gzipped XML.
# We'll parse in a "schema-agnostic" way (heuristics) for MVP.
RE_TRACK_AUDIO = re.compile(r"<(?:\w+:)?AudioTrack\b", re.IGNORECASE)
RE_TRACK_MIDI = re.compile(r"<(?:\w+:)?MidiTrack\b", re.IGNORECASE)
RE_TRACK_RETURN = re.compile(r"<(?:\w+:)?ReturnTrack\b", re.IGNORECASE)
RE_TRACK_MASTER = re.compile(r"<(?:\w+:)?MasterTrack\b", re.IGNORECASE)
RE_TRACK_GROUP = re.compile(r"<(?:\w+:)?GroupTrack\b", re.IGNORECASE)
RE_TRACK_FOLD = re.compile(r"<(?:\w+:)?FoldedGroupTrack\b", re.IGNORECASE)
RE_TRACK_GENERIC = re.compile(r"<(?:\w+:)?Track\b", re.IGNORECASE)

RE_CLIP_AUDIO = re.compile(r"<(?:\w+:)?AudioClip\b", re.IGNORECASE)
RE_CLIP_MIDI = re.compile(r"<(?:\w+:)?MidiClip\b", re.IGNORECASE)

# Paths inside XML can show up in lots of forms; grab common absolute-ish patterns.
RE_PATHS = re.compile(
    r"""
    (                                   # capture whole path
      (?:[A-Za-z]:\\|/|\\\\)            # windows drive OR unix root OR UNC root
      [^<>"\r\n\t]+?                    # body (lazy)
      \.(?:wav|aif|aiff|flac|mp3|m4a|ogg|asd)  # extension
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Heuristic device/plugin name “hints”
RE_DEVICE_HINTS = re.compile(
    r"""
    (?:PluginName|PlugName|DeviceName|VstPlugin|AuPlugin|PluginDesc|Manufacturer)\s*=\s*"
    ([^"]+)"
    """,
    re.IGNORECASE | re.VERBOSE,
)

RE_XML_ATTR_NAME = re.compile(
    r'(?:\bName|\bDisplayName|\bShortName)\s*=\s*"([^"]+)"',
    re.IGNORECASE,
)

RE_TEMPO = re.compile(r"<Tempo[^>]*Value=\"([0-9.]+)\"", re.IGNORECASE)

MIME_CACHE: dict[str, Optional[str]] = {}

TRACK_TAGS = {
    "AudioTrack",
    "MidiTrack",
    "ReturnTrack",
    "MasterTrack",
    "GroupTrack",
    "FoldedGroupTrack",
}
CLIP_TAGS = {"AudioClip", "MidiClip"}
TRACK_META_KEYS = {
    "Name",
    "DisplayName",
    "ShortName",
    "Id",
    "TrackId",
    "Color",
    "IsFolded",
    "IsSolo",
    "IsMute",
    "IsArm",
    "GroupId",
    "TrackGroupId",
}
CLIP_META_KEYS = {
    "Name",
    "Id",
    "Length",
    "Start",
    "End",
    "LoopStart",
    "LoopEnd",
    "WarpMode",
    "IsWarped",
    "LoopOn",
}
DEVICE_META_KEYS = {
    "Name",
    "DisplayName",
    "ShortName",
    "DeviceName",
    "PluginName",
    "Manufacturer",
    "Vendor",
    "PluginDesc",
    "Id",
    "PresetName",
}
ROUTING_META_KEYS = {
    "InputRouting",
    "OutputRouting",
    "InputChannel",
    "OutputChannel",
}
CLIP_DETAIL_KEYS = {
    "WarpMode",
    "IsWarped",
    "LoopOn",
    "LoopStart",
    "LoopEnd",
    "Start",
    "End",
    "PitchCoarse",
    "PitchFine",
    "Transpose",
}
DEVICE_PARAM_KEYS = {"Name", "DisplayName", "ShortName", "Id", "Value", "Manual", "Min", "Max"}


def _now_iso_local() -> str:
    try:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def _safe_rel(root: Path, p: Path) -> str:
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except Exception:
        return str(p)


def write_scan_summary(
    *,
    out_dir: Path,
    root: Path,
    started_ts: int,
    finished_ts: int,
    scanned: int,
    indexed: int,
    parsed_docs: int,
    skipped: int,
    by_ext: Counter[str],
    ableton_sets: int,
    ableton_artifacts: int,
    total_files: Optional[int],
    refs_total: int,
    refs_missing: int,
    top_dirs: Counter[str],
    scope: str,
    mode: str,
    all_files: bool,
    skipped_dirs: int,
) -> Path:
    summary_name = "scan_summary.json" if scope == "live_recordings" else f"scan_summary_{scope}.json"
    out = out_dir / summary_name
    payload = {
        "root": str(root),
        "out": str(out_dir),
        "scope": scope,
        "mode": mode,
        "started_at": started_ts,
        "finished_at": finished_ts,
        "generated_at": _now_iso_local(),
        "duration_sec": float(finished_ts - started_ts),
        "files_scanned": int(scanned),
        "files_indexed": int(indexed),
        "ableton_docs_parsed": int(parsed_docs),
        "files_skipped": int(skipped),
        "dirs_skipped": int(skipped_dirs),
        "files_total": int(total_files or 0),
        "all_files": bool(all_files),
        "ableton_sets": int(ableton_sets),
        "ableton_artifacts": int(ableton_artifacts),
        "by_ext": {k: int(v) for k, v in by_ext.most_common()},
        "refs_total": int(refs_total),
        "refs_missing": int(refs_missing),
        "top_dirs": [{"path": k, "count": int(v)} for k, v in top_dirs.most_common(10)],
    }
    out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out


@dataclass
class ScanRecord:
    path: str
    ext: str
    size: int
    mtime: int
    kind: str


def now_ts() -> int:
    return int(time.time())


def sha1_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def hash_path(path: Path) -> str:
    return hashlib.sha1(str(path).lower().encode("utf-8", errors="ignore")).hexdigest()


def _decode_ableton_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    if "\x00" in text:
        best = text
        best_score = text.count("<")
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                candidate = raw.decode(enc, errors="ignore")
            except Exception:
                continue
            score = candidate.count("<")
            if score > best_score:
                best = candidate
                best_score = score
        text = best.replace("\x00", "")
    return text


def read_text_maybe_gzip(path: Path, max_bytes: int = 200_000_000) -> str:
    """
    Try to read as gzipped text first; fall back to plain text.
    max_bytes is a safety cap to prevent accidental huge decompressions.
    """
    raw = path.read_bytes()
    if len(raw) == 0:
        return ""

    # gzip magic: 1F 8B
    if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            out = gz.read(max_bytes + 1)
            if len(out) > max_bytes:
                raise RuntimeError(
                    f"Decompressed data exceeds max_bytes ({max_bytes}) for {path}"
                )
            return _decode_ableton_bytes(out)

    # plain text fallback
    return _decode_ableton_bytes(raw)


def classify(ext: str) -> str:
    e = ext.lower()
    if e in ABLETON_DOC_EXTS:
        return "ableton_doc"
    if e in ABLETON_ARTIFACT_EXTS:
        return "ableton_artifact"
    if e in MEDIA_EXTS:
        return "media"
    return "other"


def iter_files(
    root: Path,
    dir_state: dict[str, int],
    dir_updates: dict[str, int],
    incremental: bool,
    skipped_dirs: list[int],
    sort_entries: bool = False,
) -> Iterable[os.DirEntry]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            if incremental and current != root:
                try:
                    dir_mtime = int(current.stat().st_mtime)
                except OSError:
                    continue
                prev_mtime = dir_state.get(str(current))
                if prev_mtime is not None and prev_mtime == dir_mtime:
                    skipped_dirs[0] += 1
                    continue
                dir_updates[str(current)] = dir_mtime
            with os.scandir(current) as it:
                entries = list(it)
            if sort_entries:
                entries.sort(key=lambda e: e.name.lower())
            for entry in entries:
                    if entry.name in SKIP_DIRS:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                    except OSError:
                        continue
                    if entry.is_file(follow_symlinks=False) or entry.is_symlink():
                        yield entry
        except OSError:
            continue


def count_files(
    root: Path,
    dir_state: dict[str, int],
    incremental: bool,
    all_files: bool,
    wanted_exts: set[str],
    sort_entries: bool = False,
) -> int:
    dir_updates: dict[str, int] = {}
    skipped_dirs = [0]
    total = 0
    for entry in iter_files(
        root, dir_state, dir_updates, incremental, skipped_dirs, sort_entries=sort_entries
    ):
        p = Path(entry.path)
        ext = p.suffix.lower()
        if not all_files and ext not in wanted_exts:
            continue
        total += 1
    return total


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_ableton_doc(text: str) -> dict:
    """
    Schema-agnostic heuristics (MVP):
    - count track tags
    - count clip tags
    - extract likely sample paths
    - extract device/plugin name hints
    """
    tracks_audio = len(RE_TRACK_AUDIO.findall(text))
    tracks_midi = len(RE_TRACK_MIDI.findall(text))
    tracks_return = len(RE_TRACK_RETURN.findall(text))
    tracks_master = len(RE_TRACK_MASTER.findall(text))
    tracks_group = len(RE_TRACK_GROUP.findall(text))
    tracks_fold = len(RE_TRACK_FOLD.findall(text))

    clips_audio = len(RE_CLIP_AUDIO.findall(text))
    clips_midi = len(RE_CLIP_MIDI.findall(text))

    sample_refs = sorted(set(m.group(1) for m in RE_PATHS.finditer(text)))

    # device/plugin hints: combine a few heuristics, preserve sequence
    hints = set()
    sequence: list[str] = []
    for m in RE_DEVICE_HINTS.finditer(text):
        v = m.group(1).strip()
        if v:
            hints.add(v)
            sequence.append(v)
    for m in RE_XML_ATTR_NAME.finditer(text):
        v = m.group(1).strip()
        # avoid obviously huge blobs
        if 1 <= len(v) <= 120:
            hints.add(v)
            sequence.append(v)

    devices = sorted(hints)[:250]
    device_sequence = sequence[:500]

    tempo = None
    tempo_match = RE_TEMPO.search(text)
    if tempo_match:
        try:
            tempo = float(tempo_match.group(1))
        except ValueError:
            tempo = None

    track_total = tracks_audio + tracks_midi + tracks_return + tracks_master + tracks_group + tracks_fold
    if track_total == 0:
        # Fallback for alternate schemas to avoid false zeros.
        track_total = len(RE_TRACK_GENERIC.findall(text))

    return {
        "tracks": {
            "audio": tracks_audio,
            "midi": tracks_midi,
            "return": tracks_return,
            "master": tracks_master,
            "group": tracks_group,
            "folded_group": tracks_fold,
            "total": track_total,
        },
        "clips": {
            "audio": clips_audio,
            "midi": clips_midi,
            "total": clips_audio + clips_midi,
        },
        "sample_refs": sample_refs,
        "device_hints": devices,
        "device_sequence": device_sequence,
        "tempo": tempo,
    }


def _local_tag(tag: str) -> str:
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    if ":" in tag:
        tag = tag.split(":", 1)[1]
    return tag


def _extract_name(elem: ET.Element) -> str:
    for key in ("Name", "DisplayName", "ShortName", "DeviceName", "PluginName", "Value"):
        if key in elem.attrib and elem.attrib[key]:
            return elem.attrib[key]
    for child in elem:
        local = _local_tag(child.tag)
        if local in {"Name", "DisplayName", "ShortName"}:
            if "Value" in child.attrib and child.attrib["Value"]:
                return child.attrib["Value"]
            if child.text:
                return child.text.strip()
        if "Name" in child.attrib and child.attrib["Name"]:
            return child.attrib["Name"]
    return ""


def _extract_numeric_attr(elem: ET.Element, keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        if key in elem.attrib:
            try:
                return float(elem.attrib[key])
            except ValueError:
                return None
    return None


def _collect_meta(elem: ET.Element, keys: set[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key, val in elem.attrib.items():
        if key in keys and val:
            meta[key] = str(val)
    for child in elem.iter():
        local = _local_tag(child.tag)
        if local not in keys:
            continue
        if "Value" in child.attrib and child.attrib["Value"]:
            meta[local] = str(child.attrib["Value"])
        elif "Name" in child.attrib and child.attrib["Name"]:
            meta[local] = str(child.attrib["Name"])
        elif child.text and child.text.strip():
            meta[local] = child.text.strip()
    return meta


def parse_ableton_xml(text: str) -> dict:
    tracks: list[dict] = []
    clips: list[dict] = []
    devices: list[dict] = []
    routings: list[dict] = []
    clip_details: list[dict] = []
    device_params: list[dict] = []
    root = ET.fromstring(text)
    track_idx = 0
    clip_idx = 0
    device_idx = 0
    for elem in root.iter():
        local = _local_tag(elem.tag)
        if local in TRACK_TAGS:
            name = _extract_name(elem)
            track_type = local.replace("Track", "").lower() or "track"
            track_meta = _collect_meta(elem, TRACK_META_KEYS)
            tracks.append(
                {
                    "index": track_idx,
                    "type": track_type,
                    "name": name,
                    "is_group": local in {"GroupTrack", "FoldedGroupTrack"},
                    "is_folded": local == "FoldedGroupTrack",
                    "meta": track_meta,
                }
            )
            for child in elem.iter():
                child_local = _local_tag(child.tag)
                if child_local in CLIP_TAGS:
                    clip_name = _extract_name(child)
                    clip_type = child_local.replace("Clip", "").lower()
                    length = _extract_numeric_attr(child, ("Length", "LoopEnd", "End"))
                    clip_meta = _collect_meta(child, CLIP_META_KEYS)
                    detail_meta = _collect_meta(child, CLIP_DETAIL_KEYS)
                    clips.append(
                        {
                            "index": clip_idx,
                            "track_index": track_idx,
                            "type": clip_type,
                            "name": clip_name,
                            "length": length,
                            "meta": clip_meta,
                        }
                    )
                    if detail_meta:
                        clip_details.append(
                            {
                                "index": clip_idx,
                                "track_index": track_idx,
                                "type": clip_type,
                                "name": clip_name,
                                "details": detail_meta,
                            }
                        )
                    clip_idx += 1
                if child_local.endswith("Device") and child_local not in TRACK_TAGS:
                    device_name = _extract_name(child)
                    device_meta = _collect_meta(child, DEVICE_META_KEYS)
                    devices.append(
                        {
                            "index": device_idx,
                            "track_index": track_idx,
                            "type": child_local,
                            "name": device_name,
                            "meta": device_meta,
                        }
                    )
                    for param in child.iter():
                        param_local = _local_tag(param.tag)
                        if not param_local.endswith("Parameter"):
                            continue
                        param_meta = _collect_meta(param, DEVICE_PARAM_KEYS)
                        if not param_meta:
                            continue
                        device_params.append(
                            {
                                "device_index": device_idx,
                                "track_index": track_idx,
                                "type": param_local,
                                "name": param_meta.get("Name") or param_meta.get("DisplayName") or "",
                                "param": param_meta,
                            }
                        )
                    device_idx += 1
                if child_local in {"InputRouting", "OutputRouting"}:
                    value = child.attrib.get("Value") or child.text or ""
                    routing_meta = _collect_meta(child, ROUTING_META_KEYS)
                    routings.append(
                        {
                            "track_index": track_idx,
                            "direction": "input" if child_local == "InputRouting" else "output",
                            "value": value.strip(),
                            "meta": routing_meta,
                        }
                    )
            track_idx += 1
    return {
        "tracks": tracks,
        "clips": clips,
        "devices": devices,
        "routings": routings,
        "clip_details": clip_details,
        "device_params": device_params,
    }


def iter_ableton_xml_nodes(text: str, text_limit: int = 2000) -> Iterable[dict]:
    stack: list[str] = []
    order = 0
    for event, elem in ET.iterparse(io.StringIO(text), events=("start", "end")):
        if event == "start":
            stack.append(_local_tag(elem.tag))
            continue
        tag = _local_tag(elem.tag)
        path = "/".join(stack)
        depth = len(stack)
        attrs = {k: str(v) for k, v in elem.attrib.items()}
        raw_text = (elem.text or "").strip()
        text_len = len(raw_text)
        truncated = False
        if text_len > text_limit:
            raw_text = raw_text[:text_limit]
            truncated = True
        yield {
            "ord": order,
            "tag": tag,
            "path": path,
            "depth": depth,
            "attrs": attrs,
            "text": raw_text,
            "text_len": text_len,
            "text_truncated": truncated,
        }
        order += 1
        stack.pop()


def analyze_audio(path: Path, ext: str) -> dict:
    info = {"audio_codec": ext.lstrip(".")}
    try:
        if ext in {".wav"}:
            with wave.open(str(path), "rb") as wf:
                info.update(
                    {
                        "audio_duration": wf.getnframes() / float(wf.getframerate() or 1),
                        "audio_sample_rate": wf.getframerate(),
                        "audio_channels": wf.getnchannels(),
                        "audio_bit_depth": wf.getsampwidth() * 8,
                    }
                )
        elif ext in {".aif", ".aiff"} and aifc is not None:
            with aifc.open(str(path), "rb") as af:
                info.update(
                    {
                        "audio_duration": af.getnframes() / float(af.getframerate() or 1),
                        "audio_sample_rate": af.getframerate(),
                        "audio_channels": af.getnchannels(),
                        "audio_bit_depth": af.getsampwidth() * 8,
                    }
                )
    except Exception:
        pass
    return info


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="abletools-scan",
        description="Scan folders for Ableton items and catalog to JSONL.",
    )
    ap.add_argument("root", help="Root folder to scan (recursive).")
    ap.add_argument("--out", default=None, help="Output folder (default: <root>/.abletools_catalog)")
    ap.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        default="live_recordings",
        help="Catalog scope (default: live_recordings)",
    )
    ap.add_argument(
        "--mode",
        choices=["full", "targeted"],
        default="full",
        help="Scan mode: full = summary/hashes only, targeted = detailed per-set scan.",
    )
    ap.add_argument(
        "--details",
        default="all",
        help=(
            "Targeted detail groups (comma list): struct, clips, devices, routing, refs. "
            "Use 'all' for everything."
        ),
    )
    ap.add_argument(
        "--only-known",
        action="store_true",
        help="Limit scanning to known Ableton and media extensions.",
    )
    ap.add_argument(
        "--progress",
        action="store_true",
        help="Emit progress lines with total file counts.",
    )
    ap.add_argument(
        "--xml-nodes",
        action="store_true",
        help="Emit full XML node records for Ableton docs/artifacts.",
    )
    ap.add_argument(
        "--xml-nodes-max",
        type=int,
        default=200000,
        help="Max XML nodes to emit (0 = unlimited).",
    )
    ap.add_argument(
        "--xml-nodes-max-mb",
        type=int,
        default=512,
        help="Max XML node output size in MB (0 = unlimited).",
    )
    ap.add_argument(
        "--xml-nodes-per-doc",
        type=int,
        default=20000,
        help="Max XML nodes per document (0 = unlimited).",
    )
    ap.add_argument(
        "--hash-docs-only",
        action="store_true",
        help="Compute hashes only for Ableton docs/artifacts.",
    )
    ap.add_argument(
        "--changed-only",
        action="store_true",
        help="Only process changed files even without dir-state skipping.",
    )
    ap.add_argument(
        "--checkpoint",
        action="store_true",
        help="Write scan checkpoints to allow resuming.",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last scan checkpoint (requires deterministic order).",
    )
    ap.add_argument(
        "--deep-xml-snapshot",
        action="store_true",
        help="One-time deep snapshot: disable incremental and emit XML nodes.",
    )
    ap.add_argument(
        "--include-media",
        action="store_true",
        help="Also index media files (wav/aif/flac/mp3/etc.)",
    )
    ap.add_argument(
        "--analyze-audio",
        action="store_true",
        help="Extract basic audio metadata for wav/aif/aiff (duration, rate, channels).",
    )
    ap.add_argument(
        "--hash",
        action="store_true",
        help="Compute sha1 for indexed files (slower, but better dedupe)",
    )
    ap.add_argument(
        "--rehash-all",
        action="store_true",
        help="With --hash + --incremental, re-hash unchanged files to verify content.",
    )
    ap.add_argument(
        "--incremental",
        action="store_true",
        help="Skip unchanged files based on size+mtime (and hash if enabled)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Reserved for future parallel scan (MVP runs single-thread).",
    )
    ap.add_argument("--verbose", action="store_true", help="Verbose logs.")
    args = ap.parse_args(argv)
    if args.deep_xml_snapshot:
        args.xml_nodes = True
        args.incremental = False
        args.changed_only = False
        args.hash_docs_only = True
    if args.mode == "full" and args.deep_xml_snapshot:
        print("ERROR: deep XML snapshot is only supported in targeted mode.", file=sys.stderr)
        return 2

    root = Path(args.root).expanduser().resolve()
    target_files: Optional[list[Path]] = None
    if root.exists() and root.is_file():
        if args.mode != "targeted":
            print("ERROR: file path scans are only supported in targeted mode.", file=sys.stderr)
            return 2
        target_files = [root]
        root = root.parent
    if not root.exists() or not root.is_dir():
        print(f"ERROR: root is not a folder: {root}", file=sys.stderr)
        return 2

    out_dir = Path(args.out).expanduser().resolve() if args.out else (root / ".abletools_catalog")
    ensure_dir(out_dir)

    scope = args.scope
    suffix = "" if scope == "live_recordings" else f"_{scope}"
    file_index_path = out_dir / f"file_index{suffix}.jsonl"
    docs_path = out_dir / f"ableton_docs{suffix}.jsonl"
    struct_path = out_dir / f"ableton_struct{suffix}.jsonl"
    clip_details_path = out_dir / f"ableton_clip_details{suffix}.jsonl"
    device_params_path = out_dir / f"ableton_device_params{suffix}.jsonl"
    routing_details_path = out_dir / f"ableton_routing_details{suffix}.jsonl"
    xml_nodes_path = out_dir / f"ableton_xml_nodes{suffix}.jsonl"
    refs_path = out_dir / f"refs_graph{suffix}.jsonl"
    state_path = out_dir / f"scan_state{suffix}.json"
    dir_state_path = out_dir / f"dir_state{suffix}.json"
    per_doc_dir = out_dir / "sets" / scope

    state = load_state(state_path)
    dir_state = load_state(dir_state_path)
    dir_updates: dict[str, int] = {}
    skipped_dirs = [0]

    all_files = not args.only_known
    wanted_exts = set(DEFAULT_INDEX_EXTS)
    if args.include_media:
        wanted_exts |= MEDIA_EXTS

    scanned = 0
    indexed = 0
    parsed_docs = 0
    skipped = 0

    started = now_ts()
    by_ext: Counter[str] = Counter()
    top_dirs: Counter[str] = Counter()
    ableton_sets = 0
    ableton_artifacts = 0
    refs_total = 0
    refs_missing = 0
    xml_nodes_written = 0
    xml_nodes_bytes = 0
    xml_nodes_disabled = False
    xml_nodes_max = max(0, int(args.xml_nodes_max))
    xml_nodes_max_bytes = max(0, int(args.xml_nodes_max_mb)) * 1024 * 1024
    xml_nodes_per_doc = max(0, int(args.xml_nodes_per_doc))

    checkpoint_path = out_dir / f"scan_checkpoint{suffix}.json"
    resume_remaining = 0
    if args.resume and checkpoint_path.exists():
        try:
            resume_data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            resume_remaining = int(resume_data.get("scanned", 0))
            scanned = resume_remaining
        except Exception:
            resume_remaining = 0

    sort_entries = bool(args.checkpoint or args.resume)
    use_dir_state = args.incremental and not args.changed_only and target_files is None

    total_files = None
    detail_groups = set()
    if args.mode == "targeted":
        if args.details.strip().lower() == "all":
            detail_groups = {"struct", "clips", "devices", "routing", "refs"}
        else:
            detail_groups = {d.strip().lower() for d in args.details.split(",") if d.strip()}
    write_struct = args.mode == "targeted" and "struct" in detail_groups
    write_clips = args.mode == "targeted" and "clips" in detail_groups
    write_devices = args.mode == "targeted" and "devices" in detail_groups
    write_routing = args.mode == "targeted" and "routing" in detail_groups
    write_refs = args.mode == "targeted" and "refs" in detail_groups
    write_per_doc = args.mode == "targeted"
    if args.mode == "full":
        args.xml_nodes = False
    if args.progress:
        print("[progress] status=counting")
        if target_files:
            total_files = len(target_files)
        else:
            total_files = count_files(
                root,
                dir_state,
                use_dir_state,
                all_files,
                wanted_exts,
                sort_entries=sort_entries,
            )
        print(f"[progress] total={total_files}")

    entries = (
        target_files
        if target_files is not None
        else iter_files(
            root, dir_state, dir_updates, use_dir_state, skipped_dirs, sort_entries=sort_entries
        )
    )
    for entry in entries:
        if resume_remaining > 0:
            resume_remaining -= 1
            continue
        scanned += 1
        if isinstance(entry, os.DirEntry):
            p = Path(entry.path)
        else:
            p = Path(entry)
        ext = p.suffix.lower()
        if not all_files and ext not in wanted_exts:
            continue

        try:
            if isinstance(entry, os.DirEntry):
                st = entry.stat(follow_symlinks=False)
            else:
                st = p.stat()
        except (FileNotFoundError, OSError):
            continue

        rel = str(p)
        size = int(st.st_size)
        mtime = int(st.st_mtime)
        ctime = int(st.st_ctime)
        atime = int(st.st_atime)
        inode = int(getattr(st, "st_ino", 0))
        device = int(getattr(st, "st_dev", 0))
        mode = int(getattr(st, "st_mode", 0))
        uid = int(getattr(st, "st_uid", 0))
        gid = int(getattr(st, "st_gid", 0))
        is_symlink = entry.is_symlink() if isinstance(entry, os.DirEntry) else p.is_symlink()
        symlink_target = None
        if is_symlink:
            try:
                symlink_target = os.readlink(p)
            except OSError:
                symlink_target = None

        prev = state.get(rel)
        current_sha1: Optional[str] = None
        sha1_error: Optional[str] = None
        if (args.incremental or args.changed_only) and prev:
            if prev.get("size") == size and prev.get("mtime") == mtime and prev.get("ctime") == ctime:
                if args.hash and args.rehash_all:
                    try:
                        current_sha1 = sha1_file(p)
                    except Exception as e:
                        sha1_error = str(e)
                    else:
                        if prev.get("sha1") and current_sha1 == prev.get("sha1"):
                            skipped += 1
                            continue
                else:
                    skipped += 1
                    continue
            if args.hash_docs_only and ext in (ABLETON_DOC_EXTS | ABLETON_ARTIFACT_EXTS):
                try:
                    current_sha1 = sha1_file(p)
                except Exception as e:
                    sha1_error = str(e)
                else:
                    if prev.get("sha1") and current_sha1 == prev.get("sha1"):
                        skipped += 1
                        state[rel] = {
                            "size": size,
                            "mtime": mtime,
                            "ctime": ctime,
                            "sha1": current_sha1,
                        }
                        continue

        rec = {
            "path": rel,
            "path_hash": hash_path(p),
            "ext": ext,
            "size": size,
            "mtime": mtime,
            "ctime": ctime,
            "atime": atime,
            "inode": inode,
            "device": device,
            "mode": mode,
            "uid": uid,
            "gid": gid,
            "is_symlink": bool(is_symlink),
            "symlink_target": symlink_target,
            "name": p.name,
            "parent": str(p.parent),
            "mime": MIME_CACHE.setdefault(ext, mimetypes.guess_type(p.name)[0]),
            "kind": classify(ext),
            "scanned_at": started,
            "scope": scope,
        }

        if args.hash or (args.hash_docs_only and ext in (ABLETON_DOC_EXTS | ABLETON_ARTIFACT_EXTS)):
            if current_sha1 is None and sha1_error is None:
                try:
                    current_sha1 = sha1_file(p)
                except Exception as e:
                    sha1_error = str(e)
            if current_sha1 is not None:
                rec["sha1"] = current_sha1
            if sha1_error:
                rec["sha1_error"] = sha1_error

        if args.analyze_audio and ext in MEDIA_EXTS:
            rec.update(analyze_audio(p, ext))

        write_jsonl(file_index_path, rec)
        indexed += 1

        by_ext[ext] += 1
        if ext in ABLETON_DOC_EXTS:
            ableton_sets += 1
        elif ext in ABLETON_ARTIFACT_EXTS:
            ableton_artifacts += 1

        rel_to_root = _safe_rel(root, p)
        parts = rel_to_root.split("/")
        if len(parts) >= 2:
            bucket = "/".join(parts[:2])
        elif parts:
            bucket = parts[0]
        else:
            bucket = rel_to_root
        top_dirs[bucket] += 1

        # Update state
        state[rel] = {"size": size, "mtime": mtime, "ctime": ctime}
        if (args.hash or args.hash_docs_only) and "sha1" in rec:
            state[rel]["sha1"] = rec["sha1"]

        # Parse Ableton docs and artifacts (.als/.alc/.adg/.adv/.agr/.alp)
        if ext in (ABLETON_DOC_EXTS | ABLETON_ARTIFACT_EXTS):
            try:
                text = read_text_maybe_gzip(p)
                summary = parse_ableton_doc(text)
                struct_payload = {}
                struct_error = None
                if write_struct or write_clips or write_devices or write_routing or args.xml_nodes:
                    try:
                        struct_payload = parse_ableton_xml(text)
                    except Exception as exc:
                        struct_error = str(exc)

                doc = {
                    "path": rel,
                    "ext": ext,
                    "kind": "ableton_doc" if ext in ABLETON_DOC_EXTS else "ableton_artifact",
                    "scanned_at": started,
                    "summary": summary,
                }
                write_jsonl(docs_path, doc)
                if write_struct:
                    write_jsonl(
                        struct_path,
                        {
                            "path": rel,
                            "ext": ext,
                            "kind": "ableton_doc"
                            if ext in ABLETON_DOC_EXTS
                            else "ableton_artifact",
                            "scanned_at": started,
                            "parse_method": "xml" if not struct_error else "xml_error",
                            "error": struct_error,
                            "tracks": struct_payload.get("tracks", []),
                            "clips": struct_payload.get("clips", []),
                            "devices": struct_payload.get("devices", []),
                            "routings": struct_payload.get("routings", []),
                        },
                    )
                if write_clips:
                    for detail in struct_payload.get("clip_details", []) or []:
                        write_jsonl(
                            clip_details_path,
                            {
                                "path": rel,
                                "ext": ext,
                                "kind": "ableton_doc"
                                if ext in ABLETON_DOC_EXTS
                                else "ableton_artifact",
                                "scanned_at": started,
                                "clip_index": detail.get("index"),
                                "track_index": detail.get("track_index"),
                                "clip_type": detail.get("type"),
                                "name": detail.get("name"),
                                "details": detail.get("details") or {},
                            },
                        )
                if write_devices:
                    for param in struct_payload.get("device_params", []) or []:
                        write_jsonl(
                            device_params_path,
                            {
                                "path": rel,
                                "ext": ext,
                                "kind": "ableton_doc"
                                if ext in ABLETON_DOC_EXTS
                                else "ableton_artifact",
                                "scanned_at": started,
                                "device_index": param.get("device_index"),
                                "track_index": param.get("track_index"),
                                "param_type": param.get("type"),
                                "name": param.get("name"),
                                "param": param.get("param") or {},
                            },
                        )
                if write_routing:
                    for routing in struct_payload.get("routings", []) or []:
                        write_jsonl(
                            routing_details_path,
                            {
                                "path": rel,
                                "ext": ext,
                                "kind": "ableton_doc"
                                if ext in ABLETON_DOC_EXTS
                                else "ableton_artifact",
                                "scanned_at": started,
                                "track_index": routing.get("track_index"),
                                "direction": routing.get("direction"),
                                "value": routing.get("value"),
                                "meta": routing.get("meta") or {},
                            },
                        )
                if args.xml_nodes and not struct_error and not xml_nodes_disabled:
                    nodes_this_doc = 0
                    for node in iter_ableton_xml_nodes(text):
                        if xml_nodes_per_doc and nodes_this_doc >= xml_nodes_per_doc:
                            print(
                                f"[xml_nodes] doc cap reached ({xml_nodes_per_doc}) for {rel}",
                                file=sys.stderr,
                            )
                            break
                        if xml_nodes_max and xml_nodes_written >= xml_nodes_max:
                            xml_nodes_disabled = True
                            print("[xml_nodes] global node cap reached; disabling.", file=sys.stderr)
                            break
                        record = {
                            "path": rel,
                            "ext": ext,
                            "kind": "ableton_doc"
                            if ext in ABLETON_DOC_EXTS
                            else "ableton_artifact",
                            "scanned_at": started,
                            "ord": node["ord"],
                            "depth": node["depth"],
                            "tag": node["tag"],
                            "path_tag": node["path"],
                            "attrs": node["attrs"],
                            "text": node["text"],
                            "text_len": node["text_len"],
                            "text_truncated": node["text_truncated"],
                        }
                        payload = json.dumps(record, ensure_ascii=False)
                        payload_bytes = len(payload.encode("utf-8")) + 1
                        if xml_nodes_max_bytes and xml_nodes_bytes + payload_bytes > xml_nodes_max_bytes:
                            xml_nodes_disabled = True
                            print(
                                "[xml_nodes] max output size reached; disabling.",
                                file=sys.stderr,
                            )
                            break
                        write_jsonl(xml_nodes_path, record)
                        xml_nodes_written += 1
                        xml_nodes_bytes += payload_bytes
                        nodes_this_doc += 1
                parsed_docs += 1

                # Emit reference edges
                if write_refs:
                    for ref in summary.get("sample_refs", []):
                        ref_path = Path(ref)
                        exists = False
                        try:
                            if ref_path.is_absolute():
                                exists = ref_path.exists()
                            else:
                                exists = (root / ref_path).exists()
                        except Exception:
                            exists = False

                        refs_total += 1
                        if not exists:
                            refs_missing += 1

                        write_jsonl(
                            refs_path,
                            {
                                "src": rel,
                                "src_kind": ext.lstrip("."),
                                "ref_kind": "sample",
                                "ref_path": ref,
                                "exists": bool(exists),
                                "scanned_at": started,
                            },
                        )
                if write_per_doc:
                    ensure_dir(per_doc_dir)
                    per_doc_payload = {
                        "path": rel,
                        "path_hash": rec["path_hash"],
                        "ext": ext,
                        "scope": scope,
                        "scanned_at": started,
                        "summary": summary,
                        "tracks": struct_payload.get("tracks", []) if write_struct else [],
                        "clips": struct_payload.get("clips", []) if write_struct else [],
                        "devices": struct_payload.get("devices", []) if write_struct else [],
                        "routings": struct_payload.get("routings", []) if write_struct else [],
                        "clip_details": struct_payload.get("clip_details", []) if write_clips else [],
                        "device_params": struct_payload.get("device_params", []) if write_devices else [],
                        "refs": summary.get("sample_refs", []) if write_refs else [],
                    }
                    per_doc_path = per_doc_dir / f"{rec['path_hash']}.json"
                    per_doc_path.write_text(
                        json.dumps(per_doc_payload, ensure_ascii=False),
                        encoding="utf-8",
                    )

            except Exception as e:
                write_jsonl(
                    docs_path,
                    {
                        "path": rel,
                        "ext": ext,
                        "kind": "ableton_doc" if ext in ABLETON_DOC_EXTS else "ableton_artifact",
                        "scanned_at": started,
                        "error": str(e),
                    },
                )
                if write_struct:
                    write_jsonl(
                        struct_path,
                        {
                            "path": rel,
                            "ext": ext,
                            "kind": "ableton_doc"
                            if ext in ABLETON_DOC_EXTS
                            else "ableton_artifact",
                            "scanned_at": started,
                            "parse_method": "xml_error",
                            "error": str(e),
                            "tracks": [],
                            "clips": [],
                            "devices": [],
                            "routings": [],
                        },
                    )

        if args.verbose and indexed % 250 == 0:
            print(
                f"[scan] scanned={scanned} indexed={indexed} parsed_docs={parsed_docs} skipped={skipped}"
            )
        if args.progress and total_files:
            if scanned % 250 == 0 or scanned == total_files:
                percent = (scanned / total_files) * 100.0
                print(f"[progress] scanned={scanned} total={total_files} percent={percent:.1f}")

        if args.checkpoint and scanned % 1000 == 0:
            checkpoint_payload = {
                "scanned": scanned,
                "total_files": total_files,
                "last_path": rel,
                "updated_at": int(time.time()),
            }
            checkpoint_path.write_text(
                json.dumps(checkpoint_payload, indent=2), encoding="utf-8"
            )

    save_state(state_path, state)
    if dir_updates:
        dir_state.update(dir_updates)
        save_state(dir_state_path, dir_state)

    finished = now_ts()

    # Write machine-readable scan summary for the UI
    try:
        write_scan_summary(
            out_dir=out_dir,
            root=root,
            started_ts=started,
            finished_ts=finished,
            scanned=scanned,
            indexed=indexed,
            parsed_docs=parsed_docs,
            skipped=skipped,
            by_ext=by_ext,
            ableton_sets=ableton_sets,
            ableton_artifacts=ableton_artifacts,
            total_files=total_files,
            refs_total=refs_total,
            refs_missing=refs_missing,
            top_dirs=top_dirs,
            scope=scope,
            mode=args.mode,
            all_files=all_files,
            skipped_dirs=skipped_dirs[0],
        )
    except Exception as e:
        # Don't fail the scan if summary writing fails
        print(f"WARN: failed to write scan_summary.json: {e}", file=sys.stderr)

    print(
        f"OK: root={root}\n"
        f"out={out_dir}\n"
        f"scanned={scanned} indexed={indexed} parsed_docs={parsed_docs} skipped={skipped}\n"
        f"elapsed_sec={finished-started}"
    )
    if args.checkpoint and checkpoint_path.exists():
        try:
            checkpoint_path.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
