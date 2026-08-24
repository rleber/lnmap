import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from lnmap import Link
from lnmap.cli import app, format_links_as_yaml


@pytest.fixture
def runner() -> CliRunner:
    """Fixture providing Typer CLI runner instance."""
    return CliRunner()


@pytest.fixture
def sample_links() -> list[Link]:
    return [
        Link(
            link_type="hard",
            key="123456",
            paths=["/tmp/a.txt", "/tmp/b.txt"],
        ),
        Link(
            link_type="sym",
            key="/tmp/target.txt",
            paths=["/tmp/link.txt"],
        ),
    ]


def test_format_links_as_yaml(runner: CliRunner, sample_links: list[Link]) -> None:
    output = format_links_as_yaml(sample_links)

    # Verify YAML content structure
    assert "- type: hard" in output
    assert "key: '123456'" in output or "key: 123456" in output
    assert "paths:\n  - /tmp/a.txt\n  - /tmp/b.txt" in output

    # Verify round-trip parsing validity
    parsed = yaml.safe_load(output)
    assert len(parsed) == 2
    assert parsed[0]["type"] == "hard"
    assert parsed[0]["paths"] == ["/tmp/a.txt", "/tmp/b.txt"]
    assert parsed[1]["type"] == "sym"


def test_cli_help(
    runner: CliRunner,
) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Scans, maps, and caches filesystem links" in result.stdout


def test_cli_version(
    runner: CliRunner,
) -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "lnmap" in result.stdout


def test_cli_index_and_list_text(runner: CliRunner, tmp_path: Path) -> None:
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


def test_cli_list_json_format(runner: CliRunner, tmp_path: Path) -> None:
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


def test_cli_indexes_subcommand(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)

    db_root = root / ".lnmap_index.db"
    db_root.touch()

    result = runner.invoke(app, ["indexes", str(sub)])
    assert result.exit_code == 0
    assert str(db_root) in result.stdout


def test_cli_index_verbose(runner: CliRunner, tmp_path: Path) -> None:
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


def test_cli_index_quiet(runner: CliRunner, tmp_path: Path) -> None:
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


def test_cli_multi_index(runner: CliRunner, tmp_path: Path) -> None:
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


@pytest.fixture
def mock_db_dir(tmp_path: Path) -> Path:
    """Creates a temporary directory with an initialized SQLite db matching lnmap schema."""
    base_dir = tmp_path / "app"
    base_dir.mkdir()
    db_path = base_dir / ".lnmap_index.db"

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE hard_links (inode INTEGER NOT NULL, path TEXT NOT NULL);"
        )
        cursor.execute(
            "CREATE TABLE sym_links (target TEXT NOT NULL, path TEXT NOT NULL);"
        )
        cursor.execute(
            "CREATE TABLE alias_links (target TEXT NOT NULL, path TEXT NOT NULL);"
        )

        cursor.executemany(
            "INSERT INTO hard_links VALUES (?, ?);",
            [
                (1001, str(base_dir / "hard1.txt")),
                (1001, str(base_dir / "hard2.txt")),
            ],
        )
        cursor.executemany(
            "INSERT INTO sym_links VALUES (?, ?);",
            [
                (str(base_dir / "targets" / "doc.pdf"), str(base_dir / "sym1.pdf")),
            ],
        )
        conn.commit()

    return base_dir


def test_cli_list_path_regex_option(runner: CliRunner, mock_db_dir: Path) -> None:
    """Verify --path / -P passes regex dict key 'path' to LinkMapper.find_links."""
    with patch("lnmap.LinkMapper.find_links") as mock_find_links:
        mock_find_links.return_value = []

        result = runner.invoke(app, ["list", str(mock_db_dir), "--path", r"\.pdf$"])

        assert result.exit_code == 0
        mock_find_links.assert_called_once()
        _, kwargs = mock_find_links.call_args
        assert kwargs.get("regexps") == {"path": r"\.pdf$"}


def test_cli_list_target_regex_option(runner: CliRunner, mock_db_dir: Path) -> None:
    """Verify --target / -T passes regex dict key 'target' to LinkMapper.find_links."""
    with patch("lnmap.LinkMapper.find_links") as mock_find_links:
        mock_find_links.return_value = []

        result = runner.invoke(app, ["list", str(mock_db_dir), "-T", r".*doc.*"])

        assert result.exit_code == 0
        mock_find_links.assert_called_once()
        _, kwargs = mock_find_links.call_args
        assert kwargs.get("regexps") == {"target": r".*doc.*"}


def test_cli_list_inode_regex_option(runner: CliRunner, mock_db_dir: Path) -> None:
    """Verify --inode / -I passes regex dict key 'inode' to LinkMapper.find_links."""
    with patch("lnmap.LinkMapper.find_links") as mock_find_links:
        mock_find_links.return_value = []

        result = runner.invoke(app, ["list", str(mock_db_dir), "--inode", r"^100\d$"])

        assert result.exit_code == 0
        mock_find_links.assert_called_once()
        _, kwargs = mock_find_links.call_args
        assert kwargs.get("regexps") == {"inode": r"^100\d$"}


def test_cli_list_combined_regex_options(runner: CliRunner, mock_db_dir: Path) -> None:
    """Verify multi-option regex evaluation mapping (inode, target, path)."""
    with patch("lnmap.LinkMapper.find_links") as mock_find_links:
        mock_find_links.return_value = []

        result = runner.invoke(
            app,
            [
                "list",
                str(mock_db_dir),
                "--inode",
                "1001",
                "--target",
                "doc",
                "--path",
                "sym",
            ],
        )

        assert result.exit_code == 0
        mock_find_links.assert_called_once()
        _, kwargs = mock_find_links.call_args
        assert kwargs.get("regexps") == {
            "inode": "1001",
            "target": "doc",
            "path": "sym",
        }


def test_cli_list_regex_exception_handling(
    runner: CliRunner, mock_db_dir: Path
) -> None:
    """Verify ValueError thrown by LinkMapper regex validation bubbles up properly."""
    with patch("lnmap.LinkMapper.find_links") as mock_find_links:
        mock_find_links.side_effect = ValueError("Search expression is too long")

        result = runner.invoke(app, ["list", str(mock_db_dir), "--path", "a" * 201])

        assert result.exit_code != 0
        assert isinstance(result.exception, ValueError)
