import os
import sqlite3
from pathlib import Path

import pytest

from lnmap import LinkMapper


@pytest.fixture
def root_dir(tmp_path: Path) -> Path:
    """Provides a resolved temporary directory Path instance."""
    return tmp_path.resolve()


def test_indexes_traversal(root_dir: Path) -> None:
    """Test traversing parent directories to locate .lnmap_index.db."""
    sub_dir = root_dir / "sub"
    sub_dir.mkdir()

    idx_root = root_dir / ".lnmap_index.db"
    idx_root.touch()

    found = LinkMapper.indexes(sub_dir)
    assert len(found) == 1
    assert found[0].path == idx_root


def test_hard_link_indexing(root_dir: Path) -> None:
    """Test indexing and finding hard links."""
    file1 = root_dir / "file1.txt"
    file1.write_text("hello")

    file2 = root_dir / "file2.txt"
    try:
        os.link(file1, file2)
    except OSError:
        pytest.skip("Hard links not supported on this filesystem/OS")

    db_path = LinkMapper.index_for(root_dir)
    LinkMapper.index(db_path.parent, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include="hard")

    assert len(links) == 1
    assert links[0].link_type == "hard"
    assert len(links[0].paths) == 2


def test_symlink_indexing(root_dir: Path) -> None:
    """Test indexing and finding symbolic links."""
    target = root_dir / "target.txt"
    target.write_text("target file")

    sym = root_dir / "sym.txt"
    try:
        sym.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this OS")

    db_path = LinkMapper.index_for(root_dir)
    LinkMapper.index(db_path.parent, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include="sym")

    assert len(links) == 1
    assert links[0].link_type == "sym"
    assert links[0].paths[0] == sym


@pytest.fixture
def mock_db_mapper(tmp_path: Path) -> LinkMapper:
    """Fixture providing a LinkMapper initialized with a populated SQLite database for testing."""
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

        # Hard links setup (Shared inode 1001)
        cursor.executemany(
            "INSERT INTO hard_links VALUES (?, ?);",
            [
                (1001, str(base_dir / "hard1.txt")),
                (1001, str(base_dir / "hard2.txt")),
                (2002, str(base_dir / "other_hard.txt")),
            ],
        )

        # Symlinks setup
        cursor.executemany(
            "INSERT INTO sym_links VALUES (?, ?);",
            [
                (str(base_dir / "targets" / "doc.pdf"), str(base_dir / "sym1.pdf")),
                (str(base_dir / "targets" / "doc.pdf"), str(base_dir / "sym2.pdf")),
            ],
        )

        # Alias setup
        cursor.executemany(
            "INSERT INTO alias_links VALUES (?, ?);",
            [
                (str(base_dir / "targets" / "doc.pdf"), str(base_dir / "alias1.pdf")),
            ],
        )
        conn.commit()

    return LinkMapper(directory=base_dir, db_path=db_path)


# --- Tests for find_links (Regular Expressions) ---


def test_find_links_regex_path_filtering(mock_db_mapper: LinkMapper) -> None:
    regexps = {"path": r"\.pdf$"}
    results = mock_db_mapper.find_links(
        include={"hard", "sym", "alias"}, regexps=regexps
    )

    assert len(results) == 2
    types = {link.link_type for link in results}
    assert types == {"sym", "alias"}
    for link in results:
        assert all(str(p).endswith(".pdf") for p in link.paths)


def test_find_links_regex_target_filtering(mock_db_mapper: LinkMapper) -> None:
    regexps = {"target": r".*doc.*"}
    results = mock_db_mapper.find_links(include={"sym", "alias"}, regexps=regexps)

    assert len(results) == 2
    for link in results:
        assert "doc.pdf" in str(link.target)


def test_find_links_regex_inode_filtering(mock_db_mapper: LinkMapper) -> None:
    regexps = {"inode": r"^100\d$"}
    results = mock_db_mapper.find_links(include={"hard"}, regexps=regexps)

    assert len(results) == 1
    assert results[0].inode == 1001
    assert len(results[0].paths) == 2


def test_find_links_multiple_regex_criteria(mock_db_mapper: LinkMapper) -> None:
    regexps = {"target": r"doc\.pdf$", "path": r"sym1"}
    results = mock_db_mapper.find_links(include={"sym"}, regexps=regexps)

    assert len(results) == 1
    assert results[0].target.name == "doc.pdf"
    assert results[0].paths[0].name == "sym1.pdf"


def test_find_links_invalid_regex_field_raises_value_error(
    mock_db_mapper: LinkMapper,
) -> None:
    regexps = {"unsupported_field": r".*"}
    with pytest.raises(ValueError, match="Invalid search target unsupported_field"):
        mock_db_mapper.find_links(include={"hard"}, regexps=regexps)


def test_find_links_exceeding_max_re_length_raises_value_error(
    mock_db_mapper: LinkMapper,
) -> None:
    long_regex = "a" * (LinkMapper.MAX_RE_LENGTH + 1)
    regexps = {"path": long_regex}
    with pytest.raises(ValueError, match="Search expression is too long"):
        mock_db_mapper.find_links(include={"hard"}, regexps=regexps)


def test_re2_regexp_invalid_pattern_returns_false() -> None:
    invalid_pattern = r"(unclosed_parenthesis"
    assert LinkMapper.re2_regexp(invalid_pattern, "test_string") is False


def test_find_links_empty_include_returns_empty_list(
    mock_db_mapper: LinkMapper,
) -> None:
    results = mock_db_mapper.find_links(include=set(), regexps={"path": r".*"})
    assert results == []


# --- Tests for find_group ---


def test_find_group_hard_link_by_path(mock_db_mapper: LinkMapper) -> None:
    """Verify resolving hard link groups via one member's file path."""
    target_path = mock_db_mapper.directory / "hard1.txt"
    results = mock_db_mapper.find_group(include={"hard"}, target=target_path)

    assert len(results) == 1
    assert results[0].link_type == "hard"
    assert results[0].inode == 1001
    assert set(results[0].paths) == {
        mock_db_mapper.directory / "hard1.txt",
        mock_db_mapper.directory / "hard2.txt",
    }


def test_find_group_symlink_by_target(mock_db_mapper: LinkMapper) -> None:
    """Verify finding symlinks matching an exact target path."""
    target_path = mock_db_mapper.directory / "targets" / "doc.pdf"
    results = mock_db_mapper.find_group(include={"sym"}, target=target_path)

    assert len(results) == 1
    assert results[0].link_type == "sym"
    assert results[0].target == target_path
    assert set(results[0].paths) == {
        mock_db_mapper.directory / "sym1.pdf",
        mock_db_mapper.directory / "sym2.pdf",
    }


def test_find_group_symlink_by_link_path(mock_db_mapper: LinkMapper) -> None:
    """Verify finding symlink groups when passing the path of the link itself."""
    link_path = mock_db_mapper.directory / "sym1.pdf"
    results = mock_db_mapper.find_group(include={"sym"}, target=link_path)

    assert len(results) == 1
    assert results[0].link_type == "sym"
    assert results[0].target == mock_db_mapper.directory / "targets" / "doc.pdf"
    assert len(results[0].paths) == 2


def test_find_group_alias(mock_db_mapper: LinkMapper) -> None:
    """Verify finding macOS alias link groups."""
    target_path = mock_db_mapper.directory / "targets" / "doc.pdf"
    results = mock_db_mapper.find_group(include={"alias"}, target=target_path)

    assert len(results) == 1
    assert results[0].link_type == "alias"
    assert results[0].paths == (mock_db_mapper.directory / "alias1.pdf",)


def test_find_group_multiple_types(mock_db_mapper: LinkMapper) -> None:
    """Verify querying multiple link types for the same target simultaneously."""
    target_path = mock_db_mapper.directory / "targets" / "doc.pdf"
    results = mock_db_mapper.find_group(include={"sym", "alias"}, target=target_path)

    assert len(results) == 2
    types = {link.link_type for link in results}
    assert types == {"sym", "alias"}


def test_find_group_empty_include(mock_db_mapper: LinkMapper) -> None:
    """Verify early exit when include set is empty."""
    target_path = mock_db_mapper.directory / "hard1.txt"
    results = mock_db_mapper.find_group(include=set(), target=target_path)
    assert results == []


def test_find_group_non_existent_target(mock_db_mapper: LinkMapper) -> None:
    """Verify empty list is returned when target matches no DB records."""
    target_path = mock_db_mapper.directory / "non_existent.txt"
    results = mock_db_mapper.find_group(
        include={"hard", "sym", "alias"}, target=target_path
    )
    assert results == []
