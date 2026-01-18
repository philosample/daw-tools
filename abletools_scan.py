#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

# ------------------------------------------------------------
# Config: file types we care about
# ------------------------------------------------------------

ABLETON_DOC_EXTS = {".als", ".alc"}
ABLETON_ARTIFACT_EXTS = {".adg", ".adv", ".agr", ".alp"}  # racks/presets/grooves/packs
MEDIA_EXTS = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".ogg"}

DEFAULT_INDEX_EXTS = sorted(ABLETON_DOC_EXTS | ABLETON_ARTIFACT_EXTS)

# Ableton docs are typically gzipped XML.
# We'll parse in a "schema-agnostic" way (heuristics) for MVP.
RE_TRACK_AUDIO = re.compile(r"<AudioTrack\b", re.IGNORECASE)
RE_TRACK_MIDI = re.compile(r"<MidiTrack\b", re.IGNORECASE)
RE_TRACK_RETURN = re.compile(r"<ReturnTrack\b", re.IGNORECASE)
RE_TRACK_MASTER = re.compile(r"<MasterTrack\b", re.IGNORECASE)

RE_CLIP_AUDIO = re.compile(r"<AudioClip\b", re.IGNORECASE)
RE_CLIP_MIDI = re.compile(r"<MidiClip\b", re.IGNORECASE)

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
    refs_total: int,
    refs_missing: int,
    top_dirs: Counter[str],
) -> Path:
    out = out_dir / "scan_summary.json"
    payload = {
        "root": str(root),
        "out": str(out_dir),
        "started_at": started_ts,
        "finished_at": finished_ts,
        "generated_at": _now_iso_local(),
        "duration_sec": float(finished_ts - started_ts),
        "files_scanned": int(scanned),
        "files_indexed": int(indexed),
        "ableton_docs_parsed": int(parsed_docs),
        "files_skipped": int(skipped),
        "ableton_sets": int(ableton_sets),
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


def read_text_maybe_gzip(path: Path, max_bytes: int = 50_000_000) -> str:
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
            return out.decode("utf-8", errors="replace")

    # plain text fallback
    return raw.decode("utf-8", errors="replace")


def classify(ext: str) -> str:
    e = ext.lower()
    if e in ABLETON_DOC_EXTS:
        return "ableton_doc"
    if e in ABLETON_ARTIFACT_EXTS:
        return "ableton_artifact"
    if e in MEDIA_EXTS:
        return "media"
    return "other"


def iter_files(root: Path) -> Iterable[Path]:
    # os.walk is faster than Path.rglob for huge trees
    for dirpath, dirnames, filenames in os.walk(root):
        # skip common trash
        dn = set(dirnames)
        for skip in [".git", ".venv", "venv", "__pycache__", ".DS_Store"]:
            if skip in dn:
                dirnames.remove(skip)
        for fn in filenames:
            yield Path(dirpath) / fn


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

    clips_audio = len(RE_CLIP_AUDIO.findall(text))
    clips_midi = len(RE_CLIP_MIDI.findall(text))

    sample_refs = sorted(set(m.group(1) for m in RE_PATHS.finditer(text)))

    # device/plugin hints: combine a few heuristics, then cap output
    hints = set()
    for m in RE_DEVICE_HINTS.finditer(text):
        v = m.group(1).strip()
        if v:
            hints.add(v)
    for m in RE_XML_ATTR_NAME.finditer(text):
        v = m.group(1).strip()
        # avoid obviously huge blobs
        if 1 <= len(v) <= 120:
            hints.add(v)

    devices = sorted(hints)[:250]

    return {
        "tracks": {
            "audio": tracks_audio,
            "midi": tracks_midi,
            "return": tracks_return,
            "master": tracks_master,
            "total": tracks_audio + tracks_midi + tracks_return + tracks_master,
        },
        "clips": {
            "audio": clips_audio,
            "midi": clips_midi,
            "total": clips_audio + clips_midi,
        },
        "sample_refs": sample_refs,
        "device_hints": devices,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="abletools-scan",
        description="Scan folders for Ableton items and catalog to JSONL.",
    )
    ap.add_argument("root", help="Root folder to scan (recursive).")
    ap.add_argument("--out", default=None, help="Output folder (default: <root>/.abletools_catalog)")
    ap.add_argument(
        "--include-media",
        action="store_true",
        help="Also index media files (wav/aif/flac/mp3/etc.)",
    )
    ap.add_argument(
        "--hash",
        action="store_true",
        help="Compute sha1 for indexed files (slower, but better dedupe)",
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

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"ERROR: root is not a folder: {root}", file=sys.stderr)
        return 2

    out_dir = Path(args.out).expanduser().resolve() if args.out else (root / ".abletools_catalog")
    ensure_dir(out_dir)

    file_index_path = out_dir / "file_index.jsonl"
    docs_path = out_dir / "ableton_docs.jsonl"
    refs_path = out_dir / "refs_graph.jsonl"
    state_path = out_dir / "scan_state.json"

    state = load_state(state_path)

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
    refs_total = 0
    refs_missing = 0

    for p in iter_files(root):
        scanned += 1
        ext = p.suffix.lower()
        if ext not in wanted_exts:
            continue

        try:
            st = p.stat()
        except FileNotFoundError:
            continue

        rel = str(p)
        size = int(st.st_size)
        mtime = int(st.st_mtime)

        prev = state.get(rel)
        current_sha1: Optional[str] = None
        sha1_error: Optional[str] = None
        if args.incremental and prev:
            if prev.get("size") == size and prev.get("mtime") == mtime:
                if args.hash and prev.get("sha1"):
                    try:
                        current_sha1 = sha1_file(p)
                    except Exception as e:
                        sha1_error = str(e)
                    else:
                        if current_sha1 == prev.get("sha1"):
                            skipped += 1
                            continue
                elif not args.hash:
                    skipped += 1
                    continue

        rec = {
            "path": rel,
            "ext": ext,
            "size": size,
            "mtime": mtime,
            "kind": classify(ext),
            "scanned_at": started,
        }

        if args.hash:
            if current_sha1 is None and sha1_error is None:
                try:
                    current_sha1 = sha1_file(p)
                except Exception as e:
                    sha1_error = str(e)
            if current_sha1 is not None:
                rec["sha1"] = current_sha1
            if sha1_error:
                rec["sha1_error"] = sha1_error

        write_jsonl(file_index_path, rec)
        indexed += 1

        by_ext[ext] += 1
        if ext in ABLETON_DOC_EXTS:
            ableton_sets += 1

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
        state[rel] = {"size": size, "mtime": mtime}
        if args.hash and "sha1" in rec:
            state[rel]["sha1"] = rec["sha1"]

        # Parse Ableton docs (.als/.alc)
        if ext in ABLETON_DOC_EXTS:
            try:
                text = read_text_maybe_gzip(p)
                summary = parse_ableton_doc(text)

                doc = {
                    "path": rel,
                    "ext": ext,
                    "kind": "ableton_doc",
                    "scanned_at": started,
                    "summary": summary,
                }
                write_jsonl(docs_path, doc)
                parsed_docs += 1

                # Emit reference edges
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

            except Exception as e:
                write_jsonl(
                    docs_path,
                    {
                        "path": rel,
                        "ext": ext,
                        "kind": "ableton_doc",
                        "scanned_at": started,
                        "error": str(e),
                    },
                )

        if args.verbose and indexed % 250 == 0:
            print(
                f"[scan] scanned={scanned} indexed={indexed} parsed_docs={parsed_docs} skipped={skipped}"
            )

    save_state(state_path, state)

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
            refs_total=refs_total,
            refs_missing=refs_missing,
            top_dirs=top_dirs,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
