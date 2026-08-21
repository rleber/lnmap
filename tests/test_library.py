"""Tests for LinkMapper class and core library functions."""

import os
import sqlite3
import time
from pathlib import Path

import pytest

from lnmap import DEFAULT_DB_NAME, LinkMapper


def test_linkmapper_invalid_directory() -> None:
    with pytest.raises(ValueError, match="not a valid directory"):
        LinkMapper("/path/that/does/not/exist/at/all")


def test_linkmapper_default_db_path(tmp_path: Path) -> None:
    mapper = LinkMapper(tmp_path)
    assert mapper.db_path == tmp_path / DEFAULT_DB_NAME


def test_linkmapper_indexes_classmethod(tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub1 = root / "sub1"
    sub2 = sub1 / "sub2"
    sub2.mkdir(parents=True)

    db_root = root / DEFAULT_DB_NAME
    db_root.touch()

    db_sub2 = sub2 / DEFAULT_DB_NAME
    db_sub2.touch()

    found = LinkMapper.indexes(sub2)
    assert len(found) == 2

    found_paths = [idx.path for idx in found]
    assert db_sub2.resolve() in found_paths
    assert db_root.resolve() in found_paths


def test_linkmapper_auto_db_selection_most_recent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub1 = root / "sub1"
    sub2 = sub1 / "sub2"
    sub2.mkdir(parents=True)

    db_root = root / DEFAULT_DB_NAME
    db_root.touch()

    time.sleep(0.01)

    db_sub2 = sub2 / DEFAULT_DB_NAME
    db_sub2.touch()

    mapper1 = LinkMapper(sub2)
    assert mapper1.db_path == db_sub2.resolve()

    new_mtime = time.time() + 10.0
    os.utime(db_root, (new_mtime, new_mtime))

    mapper2 = LinkMapper(sub2)
    assert mapper2.db_path == db_root.resolve()


def test_linkmapper_auto_db_selection_tie_breaker(tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub1 = root / "sub1"
    sub2 = sub1 / "sub2"
    sub2.mkdir(parents=True)

    db_root = root / DEFAULT_DB_NAME
    db_root.touch()

    db_sub2 = sub2 / DEFAULT_DB_NAME
    db_sub2.touch()

    same_mtime = 1700000000.0
    os.utime(db_root, (same_mtime, same_mtime))
    os.utime(db_sub2, (same_mtime, same_mtime))

    mapper = LinkMapper(sub2)
    assert mapper.db_path == db_sub2.resolve()


def test_save_to_db_static_method(tmp_path: Path) -> None:
    custom_db = tmp_path / "custom.db"
    hard_records = [(12345, str(tmp_path / "file1.txt"))]
    sym_records = [("target_path", str(tmp_path / "sym1.txt"))]
    alias_records = [("alias_target", str(tmp_path / "alias1.txt"))]

    LinkMapper._save_to_db(custom_db, hard_records, sym_records, alias_records)
    assert custom_db.is_file()

    with sqlite3.connect(custom_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM hard_links;")
        assert cursor.fetchone()[0] == 1


def test_index_static_method(tmp_path: Path) -> None:
    custom_db = tmp_path / "custom_index.db"

    target_file = tmp_path / "target.txt"
    target_file.write_text("content")
    link_file = tmp_path / "link.txt"
    os.link(target_file, link_file)

    LinkMapper.index(custom_db)
    assert custom_db.is_file()

    with sqlite3.connect(custom_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM hard_links;")
        assert cursor.fetchone()[0] == 2


def test_find_links_include_filter(tmp_path: Path) -> None:
    target_file = tmp_path / "target.txt"
    target_file.touch()

    hard1 = tmp_path / "hard1.txt"
    hard2 = tmp_path / "hard2.txt"
    hard1.hardlink_to(target_file)
    hard2.hardlink_to(target_file)

    sym1 = tmp_path / "sym1.txt"
    sym1.symlink_to(target_file)

    db_path = tmp_path / DEFAULT_DB_NAME
    LinkMapper.index(db_path)

    mapper = LinkMapper(tmp_path, db_path=db_path)

    all_links = mapper.find_links()
    assert len(all_links) == 2
    link_types = {link.link_type for link in all_links}
    assert link_types == {"hard", "sym"}

    hard_links = mapper.find_links(include="hard")
    assert len(hard_links) == 1
    assert hard_links[0].link_type == "hard"

    sym_links = mapper.find_links(include="sym")
    assert len(sym_links) == 1
    assert sym_links[0].link_type == "sym"

    none_links = mapper.find_links(include="none")
    assert len(none_links) == 0

    with pytest.raises(ValueError, match="Invalid option"):
        mapper.find_links(include="invalid_option")


def test_find_links_filters_out_parent_paths(tmp_path: Path):
    # Setup hierarchy: parent_dir / child_dir
    parent_dir = tmp_path / "parent"
    child_dir = parent_dir / "child"
    parent_dir.mkdir()
    child_dir.mkdir()

    # Create hard-linked files inside child_dir
    c1 = child_dir / "child_file1.txt"
    c2 = child_dir / "child_file2.txt"
    c1.write_text("hello")
    os.link(c1, c2)

    # Create a hard-linked file up in parent_dir
    p1 = parent_dir / "parent_file1.txt"
    p2 = parent_dir / "parent_file2.txt"
    p1.write_text("world")
    os.link(p1, p2)

    # Index from parent directory level
    parent_db = parent_dir / DEFAULT_DB_NAME
    LinkMapper.index(parent_db)

    # Initialize LinkMapper targeting child_dir using parent's index database
    mapper = LinkMapper(directory=child_dir, db_path=parent_db)
    links = mapper.find_links()

    # Verify only child_dir paths are returned
    all_returned_paths = [p for link in links for p in link.paths]
    assert len(links) == 1
    assert set(all_returned_paths) == {c1.resolve(), c2.resolve()}
    assert p1.resolve() not in all_returned_paths
    assert p2.resolve() not in all_returned_paths


def test_find_links_drops_hard_link_if_fewer_than_two_paths_in_subdirectory(
    tmp_path: Path,
):
    parent_dir = tmp_path / "parent"
    child_dir = parent_dir / "child"
    parent_dir.mkdir()
    child_dir.mkdir()

    # Hard link shared across parent and child directory boundaries
    p_file = parent_dir / "file.txt"
    c_file = child_dir / "file_link.txt"
    p_file.write_text("shared")
    os.link(p_file, c_file)

    parent_db = parent_dir / DEFAULT_DB_NAME
    LinkMapper.index(parent_db)

    # Querying child_dir should return no hard link sets since only 1 path exists inside child_dir
    mapper = LinkMapper(directory=child_dir, db_path=parent_db)
    links = mapper.find_links(include="hard")
    assert links == []
