import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lnmap.cli import app

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Scans, maps, and caches filesystem links" in result.stdout


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "lnmap" in result.stdout


def test_cli_index_and_list_text(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    list_result = runner.invoke(app, ["list", str(tmp_path)])
    assert list_result.exit_code == 0
    assert "[hard]" in list_result.stdout


def test_cli_list_json_format(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    list_result = runner.invoke(app, ["list", "--format", "json", str(tmp_path)])
    assert list_result.exit_code == 0
    assert '"type": "hard"' in list_result.stdout


def test_cli_indexes_subcommand(tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)

    db_root = root / ".lnmap_index.db"
    db_root.touch()

    result = runner.invoke(app, ["indexes", str(sub)])
    assert result.exit_code == 0
    assert str(db_root) in result.stdout


def test_cli_index_verbose(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    result = runner.invoke(app, ["index", str(tmp_path)])
    assert result.exit_code == 0
    assert "Updated index" in result.stdout


def test_cli_index_quiet(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    result = runner.invoke(app, ["index", "--quiet", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_cli_multi_index(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported")

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    list_result = runner.invoke(app, ["list", str(tmp_path)])
    assert list_result.exit_code == 0
    assert "[hard]" in list_result.stdout
