from __future__ import annotations

import wave
from pathlib import Path

from abletools_scan import analyze_audio, parse_ableton_doc


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
