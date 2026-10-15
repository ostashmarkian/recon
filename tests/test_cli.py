"""The recon command: what it refuses before it asks a site anything."""

from pathlib import Path

import pytest

from recon import __version__
from recon.cli import load_report, main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"recon {__version__}"


def test_a_bad_compare_file_stops_before_the_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert main(["https://shop.invalid", "--compare", str(bad)]) == 2
    assert "not a recon report" in capsys.readouterr().err


def test_load_report(tmp_path: Path) -> None:
    good, listed = tmp_path / "good.json", tmp_path / "list.json"
    good.write_text('{"began": "2026-10-15"}', encoding="utf-8")
    listed.write_text("[1, 2]", encoding="utf-8")
    assert load_report(good) == {"began": "2026-10-15"}
    assert load_report(listed) is None
    assert load_report(tmp_path / "missing.json") is None
