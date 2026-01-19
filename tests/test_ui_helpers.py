from datetime import datetime

from abletools_ui import format_mtime, is_backup_path, set_detail_fields, truncate_path


class DummyLabel:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, text: str = "") -> None:
        self.text = text


def test_truncate_path_no_change() -> None:
    assert truncate_path("short", max_len=10) == "short"


def test_truncate_path_truncates() -> None:
    value = "abcdefghijklmnopqrstuvwxyz"
    expected = f"{value[:5]}…{value[-5:]}"
    assert truncate_path(value, max_len=10) == expected


def test_format_mtime_invalid() -> None:
    assert format_mtime("nope") == ""
    assert format_mtime(-1) == ""


def test_format_mtime_valid() -> None:
    ts = 1700000000
    expected = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    assert format_mtime(ts) == expected


def test_set_detail_fields() -> None:
    rows = [(DummyLabel(), DummyLabel()), (DummyLabel(), DummyLabel())]
    set_detail_fields(rows, [("Name", "Able")])
    assert rows[0][0].text == "Name:"
    assert rows[0][1].text == "Able"
    assert rows[1][0].text == ""
    assert rows[1][1].text == ""


def test_is_backup_path_backup_dir() -> None:
    assert is_backup_path("/Users/test/Music/Backup/Set.als")


def test_is_backup_path_timestamp_name() -> None:
    assert is_backup_path("/Users/test/Music/Set [2026-01-19 123456].als")
    assert is_backup_path("/Users/test/Music/Set [20260119_123456].als")
    assert not is_backup_path("/Users/test/Music/Set [notes].als")
