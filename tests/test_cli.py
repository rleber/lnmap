import os
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


def test_cli_init(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    sym1 = tmp_path / "s1.txt"
    sym1.symlink_to(file1)

    db_path = tmp_path / DEFAULT_DB_NAME
    assert not db_path.exists()

    # Run `init` -> creates DB, outputs nothing to stdout
    main(["init", str(tmp_path)])
    out = capsys.readouterr().out
    assert out == ""
    assert db_path.exists()

    # Verify initialized contents via `list` with default update=none
    main(["list", str(tmp_path)])
    list_out = capsys.readouterr().out
    lines = [line for line in list_out.strip().split("\n") if line]
    assert len(lines) == 2

    # Add a new link and run `init` again to overwrite/refresh
    file3 = tmp_path / "c.txt"
    os.link(file1, file3)

    main(["init", str(tmp_path)])
    assert capsys.readouterr().out == ""

    # `list` should now reflect 3 hard link paths
    main(["list", str(tmp_path)])
    list_out2 = capsys.readouterr().out
    hard_line = next(line for line in list_out2.strip().split("\n") if "#=" in line)
    assert len(hard_line.split(",")) == 3


def test_cli_global_db_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    custom_db = tmp_path / "custom.db"
    assert not custom_db.exists()

    # Specified before subcommand
    main(["--db-path", str(custom_db), "init", str(tmp_path)])
    capsys.readouterr()
    assert custom_db.exists()

    # Specified after subcommand
    main(["list", "--db-path", str(custom_db), str(tmp_path)])
    out = capsys.readouterr().out
    assert "#=" in out


def test_cli_update_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    # Initial run creates DB and scans all
    main(["list", str(tmp_path)])
    capsys.readouterr()

    # Add new link
    file3 = tmp_path / "c.txt"
    os.link(file1, file3)

    # Omitted --update defaults to "none" (returns cached 2 paths)
    main(["list", str(tmp_path)])
    out_none = capsys.readouterr().out
    assert len(out_none.strip().split(",")) == 2

    # Explicit --update all (returns updated 3 paths)
    main(["list", "--update", "all", str(tmp_path)])
    out_all = capsys.readouterr().out
    assert len(out_all.strip().split(",")) == 3

    # Explicit --update hard
    main(["list", "-u", "hard", str(tmp_path)])
    out_hard = capsys.readouterr().out
    assert len(out_hard.strip().split(",")) == 3

    # Bare -u / --update without a value raises SystemExit (usage error)
    with pytest.raises(SystemExit) as exc_info:
        main(["list", "-u"])

    assert exc_info.value.code != 0
    err_out = capsys.readouterr().err
    assert "expected one argument" in err_out or "usage:" in err_out


def test_cli_multi_update(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    sym1 = tmp_path / "s1.txt"
    sym1.symlink_to(file1)

    main(["list", str(tmp_path)])
    capsys.readouterr()

    file3 = tmp_path / "c.txt"
    os.link(file1, file3)

    sym2 = tmp_path / "s2.txt"
    sym2.symlink_to(file1)

    # Test comma-separated --update hard,sym
    main(["list", "--update", "hard,sym", str(tmp_path)])
    out = capsys.readouterr().out
    lines = [line for line in out.strip().split("\n") if line]
    assert len(lines) == 2
