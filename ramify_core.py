from __future__ import annotations

import gzip
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Tuple

SUPPORTED_EXTS = {".als", ".alc"}


def is_gzip(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B


def read_als_like(path: Path) -> bytes:
    raw = path.read_bytes()
    if is_gzip(raw):
        return gzip.decompress(raw)
    return raw


def write_als_like(path: Path, xml_bytes: bytes) -> None:
    path.write_bytes(gzip.compress(xml_bytes))


def iter_targets(root: Path, recursive: bool) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_EXTS:
            yield root
        return

    if root.is_dir():
        if recursive:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                    yield p
        else:
            for p in root.glob("*"):
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                    yield p
        return

    raise FileNotFoundError(f"Not found: {root}")


def flip_ram_flags(xml_bytes: bytes) -> Tuple[bytes, int, int]:
    """
    Returns (new_xml_bytes, audio_clips_seen, ram_flips_done)
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed: {e}") from e

    audio_clips_seen = 0
    flips = 0

    def local(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

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


def ensure_backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def process_file(path: Path, in_place: bool, dry_run: bool) -> Tuple[int, int, str | None]:
    xml_bytes = read_als_like(path)
    new_xml, audio_seen, flips = flip_ram_flags(xml_bytes)

    if flips == 0 or dry_run:
        return audio_seen, flips, None

    if in_place:
        ensure_backup(path)
        write_als_like(path, new_xml)
        return audio_seen, flips, str(path)

    out = path.with_name(path.stem + ".ram" + path.suffix)
    write_als_like(out, new_xml)
    return audio_seen, flips, str(out)
