import os
from pathlib import Path

import pytest

from lnmap.cli import main


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


def test_cli_index_and_list_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    main(["index", str(tmp_path)])
    capsys.readouterr()

    main(["list", str(tmp_path)])
    captured = capsys.readouterr()
    assert "[HARD]" in captured.out


def test_cli_list_json_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    main(["index", str(tmp_path)])
    capsys.readouterr()

    main(["list", "--format", "json", str(tmp_path)])
    captured = capsys.readouterr()
    assert '"type": "hard"' in captured.out


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


def test_cli_index_verbose(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    main(["index", str(tmp_path)])
    captured = capsys.readouterr()
    assert "Updated index" in captured.out


def test_cli_index_quiet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    main(["index", "--quiet", str(tmp_path)])
    captured = capsys.readouterr()
    assert captured.out == ""


def test_cli_multi_index(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    main(["index", str(tmp_path)])
    capsys.readouterr()

    main(["list", str(tmp_path)])
    captured = capsys.readouterr()
    assert "[HARD]" in captured.out
