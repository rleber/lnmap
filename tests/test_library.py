import os
from pathlib import Path

import pytest

from lnmap import DEFAULT_DB_NAME, find_links


def test_find_links_default_db(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("hello")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    links = find_links(tmp_path)

    expected_db = tmp_path / DEFAULT_DB_NAME
    assert expected_db.exists()
    assert len(links) == 1
    assert links[0].link_type == "hard"


def test_find_links_custom_db_path(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("hello")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    custom_db = tmp_path / "sub" / "custom_catalog.db"
    custom_db.parent.mkdir(parents=True, exist_ok=True)

    links = find_links(tmp_path, db_path=custom_db)

    assert custom_db.exists()
    assert len(links) == 1


def test_find_links_caching(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("hello")
    file2 = tmp_path / "b.txt"
    os.link(file1, file2)

    # Initial run creates database
    links_first = find_links(tmp_path)

    # Modify file system (add another hard link)
    file3 = tmp_path / "c.txt"
    os.link(file1, file3)

    # Subsequent run without update should hit cache and return 2 paths instead of 3
    links_cached = find_links(tmp_path, update="none")
    assert len(links_cached[0].paths) == 2

    # Run with update='all' should refresh the cache to include the 3rd path
    links_updated = find_links(tmp_path, update="all")
    assert len(links_updated[0].paths) == 3


def test_find_links_invalid_directory() -> None:
    with pytest.raises(ValueError):
        find_links("nonexistent_directory_path_12345")
