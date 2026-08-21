"""Tests for CLI subcommands, flags, and formatting in lnmap.

Verifies CLI behavior for list, index, and indexes subcommands, output formatting (text and JSON),
and flag handling.
"""

import os
from datetime import datetime
from pathlib import Path

import pytest

from lnmap import DEFAULT_DB_NAME, Link, __version__
from lnmap.cli import format_path, main, print_links


def test_format_path() -> None:
    assert format_path(Path("/simple/path.txt")) == "/simple/path.txt"
    assert (
        format_path(Path("/path with spaces/file.txt"))
        == '"/path with spaces/file.txt"'
    )
    assert format_path(Path('/path/with"quotes".txt')) == '"/path/with\\"quotes\\".txt"'
    assert format_path(Path("/path/with$var.txt")) == '"/path/with\\$var.txt"'


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert f"lnmap {__version__}" in captured.out


def test_cli_no_subcommand_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage: lnmap" in captured.out
    assert "Available subcommands" in captured.out


def test_print_links_alias_format(capsys: pytest.CaptureFixture[str]) -> None:
    target = Path("/tmp/target.txt")
    alias_path = Path("/tmp/alias.txt")

    link = Link(link_type="alias", key=target, paths=(alias_path,))

    print_links([link], output_format="text")
    captured_text = capsys.readouterr().out
    assert captured_text.strip() == "/tmp/target.txt a= /tmp/alias.txt"

    print_links([link], output_format="json")
    captured_json = capsys.readouterr().out
    assert '"type": "alias"' in captured_json
    assert '"target": "/tmp/target.txt"' in captured_json


def test_cli_index(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    sym1 = tmp_path / "s1.txt"
    sym1.symlink_to(file1)

    db_path = tmp_path / DEFAULT_DB_NAME
    assert not db_path.exists()

    # Run `index` -> creates DB, outputs progress to stderr by default
    main(["index", str(tmp_path)])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Scanning complete." in captured.err
    assert db_path.exists()

    # Verify initialized contents via `list` with default index=none
    main(["list", str(tmp_path)])
    list_out = capsys.readouterr().out
    lines = [line for line in list_out.strip().split("\n") if line]
    assert len(lines) == 2

    # Add a new link and run `index` with `-q` / `--quiet` to suppress progress
    file3 = tmp_path / "c.txt"
    os.link(file1, file3)

    main(["index", "-q", str(tmp_path)])
    captured_quiet = capsys.readouterr()
    assert captured_quiet.out == ""
    assert "Scanning complete." not in captured_quiet.err

    # `list` should now reflect 3 hard link paths
    main(["list", str(tmp_path)])
    list_out2 = capsys.readouterr().out
    hard_line = next(line for line in list_out2.strip().split("\n") if "#=" in line)
    assert len(hard_line.split(",")) == 3


def test_cli_list_quiet_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    # `list` with `--index all` outputs progress by default
    main(["list", "--index", "all", str(tmp_path)])
    captured = capsys.readouterr()
    assert "Scanning complete." in captured.err

    # `list` with `--index all -q` suppresses progress
    main(["list", "--index", "all", "-q", str(tmp_path)])
    captured_quiet = capsys.readouterr()
    assert "Scanning complete." not in captured_quiet.err


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

    # Omitted --index defaults to "none" (returns cached 2 paths from initial index)
    main(["list", str(tmp_path)])
    out_none = capsys.readouterr().out
    assert len(out_none.strip().split(",")) == 2

    # Explicit --index all (updates DB, returns updated 3 paths)
    main(["list", "--index", "all", "-q", str(tmp_path)])
    out_all = capsys.readouterr().out
    assert len(out_all.strip().split(",")) == 3

    # Explicit --index hard
    main(["list", "-i", "hard", "-q", str(tmp_path)])
    out_hard = capsys.readouterr().out
    assert len(out_hard.strip().split(",")) == 3

    # Bare -i / --index without a value raises SystemExit (usage error)
    with pytest.raises(SystemExit) as exc_info:
        main(["list", "-i"])

    assert exc_info.value.code != 0
    err_out = capsys.readouterr().err
    assert "expected one argument" in err_out or "usage:" in err_out


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

    file3 = tmp_path / "c.txt"
    os.link(file1, file3)

    sym2 = tmp_path / "s2.txt"
    sym2.symlink_to(file1)

    # Test comma-separated --index hard,sym updates and shows both
    main(["list", "--index", "hard,sym", "-q", str(tmp_path)])
    out = capsys.readouterr().out
    lines = [line for line in out.strip().split("\n") if line]
    assert len(lines) == 2


def test_cli_indexes_subcommand_with_timestamp(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Set up directory structure: /root/sub1/sub2
    root = tmp_path / "root"
    sub1 = root / "sub1"
    sub2 = sub1 / "sub2"
    sub2.mkdir(parents=True)

    db_root = root / DEFAULT_DB_NAME
    db_root.touch()

    db_sub2 = sub2 / DEFAULT_DB_NAME
    db_sub2.touch()

    # Run indexes subcommand
    main(["indexes", str(sub2)])
    out = capsys.readouterr().out
    lines = [line for line in out.strip().split("\n") if line]

    assert len(lines) == 2

    # Each line should match "YYYY-MM-DD HH:MM:SS  <path>"
    for line in lines:
        parts = line.split("  ", 1)
        assert len(parts) == 2
        timestamp_str, path_str = parts[0], parts[1]

        # Validate ISO-like datetime format
        parsed_dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        assert parsed_dt is not None

        unquoted_path = path_str.strip('"')
        assert unquoted_path in (str(db_sub2.resolve()), str(db_root.resolve()))


def test_cli_indexes_invalid_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(SystemExit) as exc_info:
        main(["indexes", str(non_existent)])

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: Target path" in err
