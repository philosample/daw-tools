from __future__ import annotations

import wave
from pathlib import Path

from abletools_scan import (
    analyze_audio,
    iter_ableton_xml_nodes,
    iter_files,
    parse_ableton_doc,
    parse_ableton_xml,
)


def test_parse_ableton_doc_counts() -> None:
    text = """
    <AudioTrack></AudioTrack>
    <MidiTrack></MidiTrack>
    <ReturnTrack></ReturnTrack>
    <MasterTrack></MasterTrack>
    <AudioClip></AudioClip>
    <MidiClip></MidiClip>
    <DeviceName="Echo" />
    <DeviceName="EQ Eight" />
    <Tempo Value="128.0" />
    /Users/test/Music/sample.wav
    """
    summary = parse_ableton_doc(text)
    assert summary["tracks"]["total"] == 4
    assert summary["clips"]["total"] == 2
    assert summary["device_hints"]
    assert summary["tempo"] == 128.0
    assert summary["sample_refs"]


def test_analyze_audio_wav(tmp_path: Path) -> None:
    path = tmp_path / "test.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00" * 48000)

    info = analyze_audio(path, ".wav")
    assert info["audio_channels"] == 2
    assert info["audio_sample_rate"] == 48000
    assert info["audio_bit_depth"] == 16
    assert info["audio_duration"]


def test_parse_ableton_xml_structured() -> None:
    text = """
    <Ableton>
      <AudioTrack Name=\"Track 1\">
        <AudioClip Name=\"Clip A\" Length=\"4.0\" />
        <DeviceChain>
          <Device Name=\"Echo\" />
          <PluginDevice DeviceName=\"EQ Eight\" />
        </DeviceChain>
        <InputRouting Value=\"In 1\" />
        <OutputRouting Value=\"Master\" />
      </AudioTrack>
    </Ableton>
    """
    summary = parse_ableton_xml(text)
    assert summary["tracks"]
    assert summary["tracks"][0]["name"] == "Track 1"
    assert summary["clips"]
    assert summary["devices"]
    assert summary["device_params"] == []
    assert isinstance(summary["clip_details"], list)


def test_iter_ableton_xml_nodes() -> None:
    text = "<Ableton><AudioTrack Name=\"Track 1\"><AudioClip Name=\"Clip A\" /></AudioTrack></Ableton>"
    nodes = list(iter_ableton_xml_nodes(text))
    assert nodes
    assert any(node["tag"] == "AudioTrack" for node in nodes)


def test_iter_files_skips_backup_dir(tmp_path: Path) -> None:
    backup_dir = tmp_path / "Backup"
    backup_dir.mkdir()
    (backup_dir / "skip.als").write_text("test", encoding="utf-8")
    (tmp_path / "Set [2026-01-19 123456].als").write_text("test", encoding="utf-8")
    (tmp_path / "keep.als").write_text("test", encoding="utf-8")
    dir_state: dict[str, int] = {}
    dir_updates: dict[str, int] = {}
    skipped_dirs = [0]
    paths = [
        Path(entry.path).name
        for entry in iter_files(tmp_path, dir_state, dir_updates, False, skipped_dirs)
    ]
    assert "keep.als" in paths
    assert "skip.als" not in paths
    assert "Set [2026-01-19 123456].als" not in paths


def test_iter_files_include_backups(tmp_path: Path) -> None:
    backup_dir = tmp_path / "Backup"
    backup_dir.mkdir()
    (backup_dir / "keep.als").write_text("test", encoding="utf-8")
    (tmp_path / "Set [2026-01-19 123456].als").write_text("test", encoding="utf-8")
    dir_state: dict[str, int] = {}
    dir_updates: dict[str, int] = {}
    skipped_dirs = [0]
    paths = [
        Path(entry.path).name
        for entry in iter_files(
            tmp_path, dir_state, dir_updates, False, skipped_dirs, skip_backups=False
        )
    ]
    assert "keep.als" in paths
    assert "Set [2026-01-19 123456].als" in paths
