import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from conftest import make_hardlink
from typer.testing import CliRunner

from lnmap import Link, LinkMapper
from lnmap.cli import app
from lnmap.support.link_types import ValidTypes, parse_link_types
from lnmap.support.output import format_links_as_yaml
from lnmap.support.progress import PROGRESS_INTERVAL, loud_logger

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS-specific behavior"
)


@pytest.fixture
def runner() -> CliRunner:
    """Fixture providing Typer CLI runner instance."""
    return CliRunner()


@pytest.fixture
def sample_links() -> list[Link]:
    return [
        Link(
            link_type="hard",
            inode=123456,
            paths=["/tmp/a.txt", "/tmp/b.txt"],
        ),
        Link(
            link_type="sym",
            target=Path("/tmp/target.txt"),
            paths=["/tmp/link.txt"],
        ),
    ]


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


# --- Tests for support functions (formatting, parsing, logging) ---


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


def test_parse_link_types_defaults_to_all_when_none() -> None:
    assert parse_link_types(None) == {"hard", "sym", "alias"}


def test_parse_link_types_all_choice_expands_to_all_types() -> None:
    assert parse_link_types([ValidTypes.ALL]) == {"hard", "sym", "alias"}


def test_parse_link_types_explicit_subset() -> None:
    result = parse_link_types([ValidTypes.HARDLINK, ValidTypes.SYMLINK])
    assert result == {"hard", "sym"}


def test_loud_logger_prints_only_on_progress_interval(capsys) -> None:
    loud_logger(1)
    loud_logger(PROGRESS_INTERVAL - 1)
    assert capsys.readouterr().err == ""

    loud_logger(PROGRESS_INTERVAL)
    assert f"{PROGRESS_INTERVAL:,}" in capsys.readouterr().err


# --- Tests for global CLI behavior ---


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


# --- Tests for the `index` command ---


def test_cli_index_and_list_text(runner: CliRunner, tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    list_result = runner.invoke(app, ["list", str(tmp_path)])
    assert list_result.exit_code == 0
    assert "[hard]" in list_result.stdout


def test_cli_index_verbose(runner: CliRunner, tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    result = runner.invoke(app, ["index", str(tmp_path)])
    assert result.exit_code == 0
    assert "Updated index" in result.stdout


def test_cli_index_quiet(runner: CliRunner, tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    result = runner.invoke(app, ["index", "--quiet", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout == ""


@darwin_only
def test_cli_index_creates_config_file_if_missing(
    runner: CliRunner, tmp_path: Path, isolated_lnmap_config: Path
) -> None:
    """Running `index` must create the lnmap config file as a side effect,
    even though the user never ran `init` explicitly."""
    assert not isolated_lnmap_config.exists()

    result = runner.invoke(app, ["index", str(tmp_path)])

    assert result.exit_code == 0
    assert isolated_lnmap_config.exists()


# --- Tests for the `list` command ---


def test_cli_list_json_format(runner: CliRunner, tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    list_result = runner.invoke(app, ["list", "--format", "json", str(tmp_path)])
    assert list_result.exit_code == 0
    assert '"type": "hard"' in list_result.stdout


def test_cli_list_yaml_format(runner: CliRunner, tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    list_result = runner.invoke(app, ["list", "--format", "yaml", str(tmp_path)])
    assert list_result.exit_code == 0
    assert "type: hard" in list_result.stdout


def test_cli_list_type_filter(runner: CliRunner, tmp_path: Path) -> None:
    """--type/-t restricts results to the requested link kind(s)."""
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    target = tmp_path / "target.txt"
    target.write_text("data2")
    sym = tmp_path / "link.txt"
    try:
        sym.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this OS")

    runner.invoke(app, ["index", str(tmp_path)])

    result = runner.invoke(app, ["list", "--type", "hard", str(tmp_path)])

    assert result.exit_code == 0
    assert "[hard]" in result.stdout
    assert "[sym]" not in result.stdout


def test_cli_list_force_index_reindexes_before_search(
    runner: CliRunner, tmp_path: Path
) -> None:
    """--index forces a reindex before searching, even with no prior index."""
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    result = runner.invoke(app, ["list", "--index", str(tmp_path)])

    assert result.exit_code == 0
    assert "[hard]" in result.stdout


def test_cli_list_force_index_short_flag(runner: CliRunner, tmp_path: Path) -> None:
    """-F is the short flag for force-reindex, freeing -I for --inode."""
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    result = runner.invoke(app, ["list", "-F", str(tmp_path)])

    assert result.exit_code == 0
    assert "[hard]" in result.stdout


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


def test_cli_list_inode_short_flag(runner: CliRunner, mock_db_dir: Path) -> None:
    """-I is the short flag for --inode, now that force-reindex uses -F."""
    with patch("lnmap.LinkMapper.find_links") as mock_find_links:
        mock_find_links.return_value = []

        result = runner.invoke(app, ["list", str(mock_db_dir), "-I", r"^100\d$"])

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


def test_cli_list_text_no_links_found(runner: CliRunner, tmp_path: Path) -> None:
    runner.invoke(app, ["index", str(tmp_path)])
    result = runner.invoke(app, ["list", str(tmp_path)])
    assert result.exit_code == 0
    assert "No links found." in result.stdout


def test_cli_list_text_quiet_no_links_found_prints_nothing(
    runner: CliRunner, tmp_path: Path
) -> None:
    runner.invoke(app, ["index", str(tmp_path)])
    result = runner.invoke(app, ["list", "--quiet", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_cli_list_regex_exception_handling(
    runner: CliRunner, mock_db_dir: Path
) -> None:
    """Verify ValueError thrown by LinkMapper regex validation bubbles up properly."""
    with patch("lnmap.LinkMapper.find_links") as mock_find_links:
        mock_find_links.side_effect = ValueError("Search expression is too long")

        result = runner.invoke(app, ["list", str(mock_db_dir), "--path", "a" * 201])

        assert result.exit_code != 0
        assert isinstance(result.exception, ValueError)


# --- Tests for the `group` command ---


def test_cli_group_subcommand(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("data")
    sym1 = tmp_path / "sym1.txt"
    sym2 = tmp_path / "sym2.txt"
    try:
        sym1.symlink_to(target)
        sym2.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this OS")

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    group_result = runner.invoke(app, ["group", str(sym1), str(tmp_path)])

    assert group_result.exit_code == 0
    assert "[sym]" in group_result.stdout
    assert str(sym2) in group_result.stdout


def test_cli_group_subcommand_force_index(runner: CliRunner, tmp_path: Path) -> None:
    """group --index forces a reindex before searching, even with no prior index."""
    target = tmp_path / "target.txt"
    target.write_text("data")
    sym1 = tmp_path / "sym1.txt"
    sym2 = tmp_path / "sym2.txt"
    try:
        sym1.symlink_to(target)
        sym2.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this OS")

    result = runner.invoke(app, ["group", "--index", str(sym1), str(tmp_path)])

    assert result.exit_code == 0
    assert str(sym2) in result.stdout


# --- Tests for the `indexes` command ---


def test_cli_indexes_subcommand(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)

    db_root = root / ".lnmap_index.db"
    db_root.touch()

    result = runner.invoke(app, ["indexes", str(sub)])
    assert result.exit_code == 0
    assert str(db_root) in result.stdout


def test_cli_indexes_subcommand_multiple_indexes(
    runner: CliRunner, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    mid = root / "mid"
    sub = mid / "sub"
    sub.mkdir(parents=True)

    root_db = root / ".lnmap_index.db"
    mid_db = mid / ".lnmap_index.db"
    root_db.touch()
    mid_db.touch()

    result = runner.invoke(app, ["indexes", str(sub)])

    assert result.exit_code == 0
    assert str(root_db) in result.stdout
    assert str(mid_db) in result.stdout


def test_cli_indexes_subcommand_no_indexes_found(
    runner: CliRunner, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["indexes", str(tmp_path)])
    assert result.exit_code == 0
    assert "No index files found." in result.stdout


# --- Tests for the `init` command ---


def test_cli_init_creates_config_file(
    runner: CliRunner, isolated_lnmap_config: Path
) -> None:
    assert not isolated_lnmap_config.exists()

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert isolated_lnmap_config.exists()
    assert "Created config file" in result.stdout


def test_cli_init_does_not_overwrite_existing_config(
    runner: CliRunner, isolated_lnmap_config: Path
) -> None:
    """Running init twice must not clobber a config the user already edited."""
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0

    isolated_lnmap_config.write_text(yaml.dump({"protected_dirs": ["Custom/Dir"]}))

    second = runner.invoke(app, ["init"])

    assert second.exit_code == 0
    assert "already exists" in second.stdout
    assert yaml.safe_load(isolated_lnmap_config.read_text()) == {
        "protected_dirs": ["Custom/Dir"]
    }


# --- Tests for the `check` command ---


def test_cli_check_reports_no_breadcrumb_after_clean_index(
    runner: CliRunner, tmp_path: Path
) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("data")
    file2 = tmp_path / "b.txt"
    make_hardlink(file1, file2)

    index_result = runner.invoke(app, ["index", str(tmp_path)])
    assert index_result.exit_code == 0

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "No incomplete-scan breadcrumb" in result.stdout


def test_cli_check_reports_leftover_breadcrumb(
    runner: CliRunner, tmp_path: Path
) -> None:
    """check must surface a breadcrumb left behind by an interrupted run."""
    stuck_dir = tmp_path / "stuck_here"
    stuck_dir.mkdir()
    LinkMapper.progress_for(tmp_path).write_text(str(stuck_dir))

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "did not complete" in result.stdout
    assert str(stuck_dir) in result.stdout
