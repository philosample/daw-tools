from __future__ import annotations

import json
from pathlib import Path

from abletools_prefs import load_plugin_payloads, parse_preferences


def test_parse_preferences_values(tmp_path: Path) -> None:
    prefs = tmp_path / "Preferences.cfg"
    prefs.write_text("UserLibraryPath=/Users/test/Music\nProjectPath=/Users/test/Live")
    data = parse_preferences(prefs)
    assert data["values"]["UserLibraryPath"][0] == "/Users/test/Music"


def test_load_plugin_payloads(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "Plugins"
    bundle = plugin_dir / "TestFX.component"
    info = bundle / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_bytes(
        b"""
        <?xml version=\"1.0\" encoding=\"UTF-8\"?>
        <!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
        <plist version=\"1.0\">
        <dict>
            <key>CFBundleName</key><string>TestFX</string>
            <key>CFBundleIdentifier</key><string>com.example.testfx</string>
            <key>CFBundleShortVersionString</key><string>1.2.3</string>
            <key>CFBundleGetInfoString</key><string>ExampleCo</string>
        </dict>
        </plist>
        """
    )

    prefs = tmp_path / "Preferences.cfg"
    prefs.write_text(f"AuPlugInCustomFolder={plugin_dir}\n")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = {
        "prefs_path": str(prefs),
        "options_path": "",
        "updated_at": 0,
        "prefs_mtime": int(prefs.stat().st_mtime),
    }
    (cache_dir / "prefs_cache.json").write_text(json.dumps(cache))

    payloads = load_plugin_payloads(cache_dir)
    assert payloads
    plugins = payloads[0]["plugins"]
    assert any(p["name"] == "TestFX" for p in plugins)
