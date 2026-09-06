import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest
from conftest import make_hardlink

from lnmap import (
    HAS_MACOS_ALIAS,
    MACOS_PROTECTED_HOME_SUBPATHS,
    Link,
    LinkMapper,
    _macos_protected_dirs,
)

needs_macos_alias = pytest.mark.skipif(
    not HAS_MACOS_ALIAS, reason="macos-alias package not available"
)
darwin_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS-specific behavior"
)


def test_indexes_traversal(root_dir: Path) -> None:
    """Test traversing parent directories to locate .lnmap_index.db."""
    sub_dir = root_dir / "sub"
    sub_dir.mkdir()

    idx_root = root_dir / ".lnmap_index.db"
    idx_root.touch()

    found = LinkMapper.indexes(sub_dir)
    assert len(found) == 1
    assert found[0].path == idx_root


def test_indexes_returns_index_in_target_directory_itself(root_dir: Path) -> None:
    """An index file directly in the queried directory is found, not just ancestors."""
    idx = root_dir / ".lnmap_index.db"
    idx.touch()

    found = LinkMapper.indexes(root_dir)
    assert len(found) == 1
    assert found[0].path == idx


def test_indexes_returns_empty_list_when_none_found(root_dir: Path) -> None:
    assert LinkMapper.indexes(root_dir) == []


def test_indexes_raises_for_non_directory(root_dir: Path) -> None:
    not_a_dir = root_dir / "file.txt"
    not_a_dir.write_text("data")
    with pytest.raises(ValueError, match="not a valid directory"):
        LinkMapper.indexes(not_a_dir)


def test_indexes_collects_multiple_ancestors(root_dir: Path) -> None:
    """Index files at more than one level above the target are all reported."""
    sub = root_dir / "a" / "b"
    sub.mkdir(parents=True)
    root_idx = root_dir / ".lnmap_index.db"
    mid_idx = root_dir / "a" / ".lnmap_index.db"
    root_idx.touch()
    mid_idx.touch()

    found = LinkMapper.indexes(sub)
    assert {idx.path for idx in found} == {root_idx, mid_idx}


def test_index_for_falls_back_when_no_index_exists(root_dir: Path) -> None:
    """With no index anywhere in the hierarchy, index_for names one in `directory`."""
    assert LinkMapper.index_for(root_dir) == root_dir / ".lnmap_index.db"


def test_index_for_prefers_newest_index(root_dir: Path) -> None:
    """Among indexes at different levels, the most recently modified one wins."""
    sub = root_dir / "sub"
    sub.mkdir()

    older = root_dir / ".lnmap_index.db"
    older.touch()
    os.utime(older, (1_000_000, 1_000_000))

    newer = sub / ".lnmap_index.db"
    newer.touch()
    os.utime(newer, (2_000_000, 2_000_000))

    assert LinkMapper.index_for(sub) == newer


def test_index_for_prefers_closest_directory_on_tie(root_dir: Path) -> None:
    """When modification times tie, the index in the closer enclosing directory wins."""
    sub = root_dir / "sub"
    sub.mkdir()

    older = root_dir / ".lnmap_index.db"
    newer = sub / ".lnmap_index.db"
    older.touch()
    newer.touch()
    same_time = 1_500_000
    os.utime(older, (same_time, same_time))
    os.utime(newer, (same_time, same_time))

    assert LinkMapper.index_for(sub) == newer


def test_link_mapper_init_raises_for_non_directory(root_dir: Path) -> None:
    not_a_dir = root_dir / "file.txt"
    not_a_dir.write_text("data")
    with pytest.raises(ValueError, match="not a valid directory"):
        LinkMapper(not_a_dir)


def test_hard_link_indexing(root_dir: Path) -> None:
    """Test indexing and finding hard links."""
    file1 = root_dir / "file1.txt"
    file1.write_text("hello")

    file2 = root_dir / "file2.txt"
    make_hardlink(file1, file2)

    db_path = LinkMapper.index_for(root_dir)
    LinkMapper.index(db_path.parent, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include="hard")

    assert len(links) == 1
    assert links[0].link_type == "hard"
    assert len(links[0].paths) == 2


def test_hard_link_indexing_three_way(root_dir: Path) -> None:
    """A hard link group with more than two members is reported as one link."""
    file1 = root_dir / "file1.txt"
    file1.write_text("hello")
    file2 = root_dir / "file2.txt"
    make_hardlink(file1, file2)
    file3 = root_dir / "file3.txt"
    make_hardlink(file1, file3)

    LinkMapper.index(root_dir, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include={"hard"})

    assert len(links) == 1
    assert set(links[0].paths) == {file1, file2, file3}


def test_unlinked_file_not_indexed_as_hard_link(root_dir: Path) -> None:
    """A regular file with no other hard links must not appear in results."""
    (root_dir / "solo.txt").write_text("hello")

    LinkMapper.index(root_dir, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include={"hard"})

    assert links == []


def test_reindex_drops_stale_entries(root_dir: Path) -> None:
    """Running index() again must reflect the current filesystem, not accumulate."""
    file1 = root_dir / "file1.txt"
    file1.write_text("hello")
    file2 = root_dir / "file2.txt"
    make_hardlink(file1, file2)

    LinkMapper.index(root_dir, print)
    mapper = LinkMapper(root_dir)
    assert len(mapper.find_links(include={"hard"})) == 1

    file2.unlink()

    LinkMapper.index(root_dir, print)
    assert mapper.find_links(include={"hard"}) == []


def test_index_skips_its_own_database_file(root_dir: Path) -> None:
    """The .lnmap_index.db file itself must never be treated as scan data."""
    db_path = LinkMapper.db_for(root_dir)
    db_path.touch()
    sibling = root_dir / "also_db.txt"
    make_hardlink(db_path, sibling)

    LinkMapper.index(root_dir, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include={"hard"})
    assert links == []


def test_index_records_dangling_symlink(root_dir: Path) -> None:
    """A symlink to a non-existent target must not crash the scan.

    Path.resolve() doesn't raise just because the target is missing (only for
    permission-style errors on an intermediate component), so index() records
    it with its literal, non-existent target rather than skipping it. This
    locks in that actual behavior so a refactor doesn't change it by accident.
    """
    sym = root_dir / "broken.txt"
    missing_target = root_dir / "does_not_exist.txt"
    try:
        sym.symlink_to(missing_target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this OS")

    LinkMapper.index(root_dir, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include={"sym"})

    assert len(links) == 1
    assert links[0].target == missing_target
    assert links[0].paths == (sym,)


def test_index_skips_unreadable_directory(root_dir: Path) -> None:
    """A directory with no read/execute permission must not abort the scan."""
    if sys.platform == "win32":
        pytest.skip("chmod-based permission restriction not applicable on Windows")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("Permission restrictions don't apply when running as root")

    visible_file = root_dir / "file1.txt"
    visible_file.write_text("hello")
    visible_link = root_dir / "file2.txt"
    make_hardlink(visible_file, visible_link)

    locked_dir = root_dir / "locked"
    locked_dir.mkdir()
    locked_file = locked_dir / "secret1.txt"
    locked_file.write_text("secret")
    make_hardlink(locked_file, locked_dir / "secret2.txt")
    locked_dir.chmod(0)

    try:
        LinkMapper.index(root_dir, print)
    finally:
        locked_dir.chmod(stat.S_IRWXU)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include={"hard"})

    assert len(links) == 1
    assert set(links[0].paths) == {visible_file, visible_link}


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


@needs_macos_alias
def test_alias_indexing(root_dir: Path) -> None:
    """Test indexing and finding a real macOS Finder alias."""
    from macos_alias import make_alias

    target = root_dir / "target.txt"
    target.write_text("target file")

    alias_path = root_dir / "alias.txt"
    assert make_alias(alias_path, target)

    LinkMapper.index(root_dir, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include={"alias"})

    assert len(links) == 1
    assert links[0].link_type == "alias"
    assert links[0].target == target.resolve()
    assert links[0].paths == (alias_path,)


@needs_macos_alias
def test_alias_indexing_groups_multiple_aliases_to_same_target(root_dir: Path) -> None:
    """Multiple aliases pointing at the same file are grouped into one link."""
    from macos_alias import make_alias

    target = root_dir / "target.txt"
    target.write_text("target file")

    alias1 = root_dir / "alias1.txt"
    alias2 = root_dir / "alias2.txt"
    assert make_alias(alias1, target)
    assert make_alias(alias2, target)

    LinkMapper.index(root_dir, print)

    mapper = LinkMapper(root_dir)
    links = mapper.find_links(include={"alias"})

    assert len(links) == 1
    assert set(links[0].paths) == {alias1, alias2}


@darwin_only
def test_index_skips_macos_protected_dirs(home_dir: Path) -> None:
    """Hard links inside known TCC-protected locations (e.g. app containers)
    must not be walked into, while links elsewhere are still indexed."""
    protected_dir = home_dir / "Library" / "Containers"
    protected_dir.mkdir(parents=True)
    hidden1 = protected_dir / "file1.txt"
    hidden1.write_text("hello")
    make_hardlink(hidden1, protected_dir / "file2.txt")

    visible1 = home_dir / "file1.txt"
    visible1.write_text("hello")
    visible2 = home_dir / "file2.txt"
    make_hardlink(visible1, visible2)

    LinkMapper.index(home_dir, print)

    mapper = LinkMapper(home_dir)
    links = mapper.find_links(include={"hard"})

    assert len(links) == 1
    assert set(links[0].paths) == {visible1, visible2}


@darwin_only
def test_index_skips_multi_segment_protected_dir(home_dir: Path) -> None:
    """A protected path nested two levels deep (e.g. Application Support/AddressBook)
    is pruned too, not just top-level Library children."""
    assert "Library/Application Support/AddressBook" in MACOS_PROTECTED_HOME_SUBPATHS

    protected_dir = home_dir / "Library" / "Application Support" / "AddressBook"
    protected_dir.mkdir(parents=True)
    hidden1 = protected_dir / "contacts1.abcddb"
    hidden1.write_text("hello")
    make_hardlink(hidden1, protected_dir / "contacts2.abcddb")

    LinkMapper.index(home_dir, print)

    mapper = LinkMapper(home_dir)
    assert mapper.find_links(include={"hard"}) == []


def test_protected_dirs_empty_off_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pruning is a no-op on non-macOS platforms."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert _macos_protected_dirs() == set()


@darwin_only
def test_protected_dirs_resolved_against_home(home_dir: Path) -> None:
    """The protected-dir set is computed relative to the current Path.home()."""
    protected = _macos_protected_dirs()
    assert home_dir / "Library" / "Containers" in protected
    assert all(str(p).startswith(str(home_dir)) for p in protected)


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


def test_link_inode_property_for_hard_link() -> None:
    link = Link(link_type="hard", key=42, paths=(Path("/a"), Path("/b")))
    assert link.inode == 42
    assert link.target is None


def test_link_target_property_for_symlink() -> None:
    link = Link(link_type="sym", key=Path("/target"), paths=(Path("/link"),))
    assert link.inode is None
    assert link.target == Path("/target")


# --- Tests for find_links (directory scoping) ---


def test_find_links_excludes_hard_link_partly_outside_directory(
    tmp_path: Path,
) -> None:
    """A hard link with only one of its two paths inside the queried directory
    must be dropped entirely, not reported as a single-path link."""
    base_dir = tmp_path / "app"
    base_dir.mkdir()
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    db_path = base_dir / ".lnmap_index.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE hard_links (inode INTEGER NOT NULL, path TEXT NOT NULL);"
        )
        conn.execute(
            "CREATE TABLE sym_links (target TEXT NOT NULL, path TEXT NOT NULL);"
        )
        conn.execute(
            "CREATE TABLE alias_links (target TEXT NOT NULL, path TEXT NOT NULL);"
        )
        conn.executemany(
            "INSERT INTO hard_links VALUES (?, ?);",
            [
                (5000, str(base_dir / "in_scope.txt")),
                (5000, str(outside_dir / "out_of_scope.txt")),
            ],
        )
        conn.commit()

    mapper = LinkMapper(directory=base_dir, db_path=db_path)
    assert mapper.find_links(include={"hard"}) == []


def test_find_links_escapes_special_characters_in_directory_name(
    tmp_path: Path,
) -> None:
    """Directory names containing SQL LIKE wildcards (%, _) must be matched
    literally, not treated as pattern metacharacters."""
    parent = tmp_path.resolve()

    target_dir = parent / "my_dir"
    target_dir.mkdir()
    file1 = target_dir / "file1.txt"
    file1.write_text("hello")
    make_hardlink(file1, target_dir / "file2.txt")

    # Under an unescaped LIKE pattern, "_" matches any single character, so
    # "my_dir/%" would incorrectly also match paths under "myXdir/".
    decoy_dir = parent / "myXdir"
    decoy_dir.mkdir()
    decoy1 = decoy_dir / "file1.txt"
    decoy1.write_text("hello")
    make_hardlink(decoy1, decoy_dir / "file2.txt")

    LinkMapper.index(parent, print)

    mapper = LinkMapper(target_dir, db_path=LinkMapper.db_for(parent))
    links = mapper.find_links(include={"hard"})

    assert len(links) == 1
    assert set(links[0].paths) == {file1, target_dir / "file2.txt"}


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


def _make_empty_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE hard_links (inode INTEGER NOT NULL, path TEXT NOT NULL);"
        )
        conn.execute(
            "CREATE TABLE sym_links (target TEXT NOT NULL, path TEXT NOT NULL);"
        )
        conn.execute(
            "CREATE TABLE alias_links (target TEXT NOT NULL, path TEXT NOT NULL);"
        )
        conn.commit()


def test_find_group_hard_link_raises_for_conflicting_inodes(tmp_path: Path) -> None:
    """Defensive check: the same path can't legitimately have two inodes."""
    base_dir = tmp_path / "app"
    base_dir.mkdir()
    db_path = base_dir / ".lnmap_index.db"
    _make_empty_db(db_path)
    p = base_dir / "ambiguous.txt"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO hard_links VALUES (?, ?);", [(1, str(p)), (2, str(p))]
        )
        conn.commit()

    mapper = LinkMapper(directory=base_dir, db_path=db_path)
    with pytest.raises(RuntimeError, match="more than one inode"):
        mapper.find_group(include={"hard"}, target=p)


def test_find_group_symlink_raises_for_conflicting_targets(tmp_path: Path) -> None:
    """Defensive check: the same path can't legitimately resolve two targets."""
    base_dir = tmp_path / "app"
    base_dir.mkdir()
    db_path = base_dir / ".lnmap_index.db"
    _make_empty_db(db_path)
    p = base_dir / "ambiguous.txt"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO sym_links VALUES (?, ?);",
            [(str(base_dir / "t1"), str(p)), (str(base_dir / "t2"), str(p))],
        )
        conn.commit()

    mapper = LinkMapper(directory=base_dir, db_path=db_path)
    with pytest.raises(RuntimeError, match="more than.*matching alias or symlink"):
        mapper.find_group(include={"sym"}, target=p)
