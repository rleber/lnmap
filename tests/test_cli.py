"""Tests for CLI command line interface functionality."""

import os
from pathlib import Path

import pytest

from lnmap.cli import main


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "lnmap" in captured.out


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "lnmap" in captured.out


def test_cli_index_and_list_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    # Run index subcommand
    main(["index", str(tmp_path)])
    capsys.readouterr()

    # Run list subcommand
    main(["list", str(tmp_path)])
    captured = capsys.readouterr()
    assert "#=" in captured.out
    assert "a.txt" in captured.out
    assert "b.txt" in captured.out


def test_cli_list_json_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    main(["index", str(tmp_path)])
    capsys.readouterr()

    main(["list", "--format", "json", str(tmp_path)])
    captured = capsys.readouterr()
    assert '"type": "hard"' in captured.out
    assert '"paths":' in captured.out


def test_cli_indexes_subcommand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)

    db_root = root / ".lnmap_index.db"
    db_root.touch()

    main(["indexes", str(sub)])
    captured = capsys.readouterr()
    assert str(db_root) in captured.out


def test_cli_list_quiet_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    # `list` with `-I` (index flag) updates index before listing
    main(["list", "-I", str(tmp_path)])
    captured = capsys.readouterr()
    assert "#=" in captured.out


def test_cli_index_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    # Initial run creates DB and scans all using index
    main(["index", str(tmp_path)])
    capsys.readouterr()

    # Add new link
    file3 = tmp_path / "c.txt"
    os.link(file1, file3)

    # Omitted -I returns cached 2 paths from initial index
    main(["list", str(tmp_path)])
    out_none = capsys.readouterr().out
    assert len(out_none.strip().split(",")) == 2

    # Explicit -I updates DB, returns updated 3 paths
    main(["list", "-I", "-q", str(tmp_path)])
    out_updated = capsys.readouterr().out
    assert len(out_updated.strip().split(",")) == 3


def test_cli_multi_index(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    sym1 = tmp_path / "s1.txt"
    sym1.symlink_to(file1)

    # Create the initial database using index
    main(["index", str(tmp_path)])
    capsys.readouterr()

    # Test include filter shortcut option `-i` for specifically hard links
    main(["list", "-i", "hard", str(tmp_path)])
    out_hard = capsys.readouterr().out
    assert "#=" in out_hard
    assert "@=" not in out_hard

    # Test include filter shortcut option `-i` for symlinks
    main(["list", "-i", "sym", str(tmp_path)])
    out_sym = capsys.readouterr().out
    assert "@=" in out_sym
    assert "#=" not in out_sym
