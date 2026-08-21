import os
from pathlib import Path

import pytest

from lnmap import DEFAULT_DB_NAME, LinkMapper


def test_parse_update_modes() -> None:
    assert LinkMapper._parse_update_modes(True) == {"hard", "sym", "alias"}
    assert LinkMapper._parse_update_modes(False) == set()
    assert LinkMapper._parse_update_modes("all") == {"hard", "sym", "alias"}
    assert LinkMapper._parse_update_modes("none") == set()
    assert LinkMapper._parse_update_modes("hard,alias") == {"hard", "alias"}
    assert LinkMapper._parse_update_modes(["hard", "sym"]) == {"hard", "sym"}

    with pytest.raises(ValueError, match="Invalid update option"):
        LinkMapper._parse_update_modes("invalid_option")


def test_invalid_directory() -> None:
    with pytest.raises(ValueError, match="not a valid directory"):
        LinkMapper(directory="/path/that/does/not/exist/at/all")

    with pytest.raises(ValueError, match="not a valid directory"):
        LinkMapper.indexes(directory="/path/that/does/not/exist/at/all")


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
    assert db_sub2.resolve() in found
    assert db_root.resolve() in found


def test_hard_link_detection(tmp_path: Path) -> None:
    file1 = tmp_path / "file1.txt"
    file1.write_text("hello world")

    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    # Single unlinked file
    file3 = tmp_path / "file3.txt"
    file3.write_text("single file")

    mapper = LinkMapper(tmp_path)
    mapper.index(update="all")
    links = mapper.find_links()

    hard_links = [l for l in links if l.link_type == "hard"]
    assert len(hard_links) == 1
    assert hard_links[0].inode == file1.stat().st_ino
    assert set(hard_links[0].paths) == {file1.resolve(), file2.resolve()}


def test_symlink_detection(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target file")

    sym1 = tmp_path / "sym1.txt"
    sym2 = tmp_path / "sym2.txt"

    sym1.symlink_to(target)
    sym2.symlink_to(target)

    mapper = LinkMapper(tmp_path)
    mapper.index(update="all")
    links = mapper.find_links()

    sym_links = [l for l in links if l.link_type == "sym"]
    assert len(sym_links) == 1
    assert sym_links[0].target == target.resolve()
    assert set(sym_links[0].paths) == {sym1.resolve(), sym2.resolve()}


def test_db_caching_and_partial_update(tmp_path: Path) -> None:
    file1 = tmp_path / "file1.txt"
    file1.write_text("content")
    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    target = tmp_path / "target.txt"
    target.write_text("target")
    sym1 = tmp_path / "sym1.txt"
    sym1.symlink_to(target)

    db_file = tmp_path / DEFAULT_DB_NAME
    assert not db_file.exists()

    mapper = LinkMapper(tmp_path)

    # Initial run creates database
    mapper.index(update="all")
    links1 = mapper.find_links()
    assert len(links1) == 2
    assert db_file.exists()

    # Add new hard link and new symlink
    file3 = tmp_path / "file3.txt"
    os.link(file1, file3)

    sym2 = tmp_path / "sym2.txt"
    sym2.symlink_to(target)

    # Run with update="none" -> should return cached results without updating DB
    mapper.index(update="none")
    links_cached = mapper.find_links()
    hard_cached = next(l for l in links_cached if l.link_type == "hard")
    sym_cached = next(l for l in links_cached if l.link_type == "sym")
    assert len(hard_cached.paths) == 2
    assert len(sym_cached.paths) == 1

    # Run with update="hard" -> should refresh hard links but keep cached symlinks
    mapper.index(update="hard")
    links_partial = mapper.find_links()
    hard_partial = next(l for l in links_partial if l.link_type == "hard")
    sym_partial = next(l for l in links_partial if l.link_type == "sym")
    assert len(hard_partial.paths) == 3
    assert len(sym_partial.paths) == 1


def test_custom_db_path(tmp_path: Path) -> None:
    custom_db = tmp_path / "subfolder" / "custom.db"
    custom_db.parent.mkdir()

    file1 = tmp_path / "file1.txt"
    file1.write_text("data")
    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    mapper = LinkMapper(directory=tmp_path, db_path=custom_db)
    assert mapper.db_path == custom_db.resolve()

    mapper.index(update="all")
    links = mapper.find_links()

    assert custom_db.exists()
    assert not (tmp_path / DEFAULT_DB_NAME).exists()
    assert len(links) == 1


def test_progress_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "file1.txt"
    file1.write_text("data")
    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    mapper = LinkMapper(tmp_path)
    mapper.index(update="all", progress=True)

    captured = capsys.readouterr()
    assert "Scanning complete." in captured.err


def test_corrupted_db_fallback(tmp_path: Path) -> None:
    db_file = tmp_path / DEFAULT_DB_NAME
    db_file.write_text("not a valid sqlite file")

    file1 = tmp_path / "file1.txt"
    file1.write_text("data")
    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    mapper = LinkMapper(tmp_path)
    mapper.index(update="all")
    links = mapper.find_links()

    assert len(links) == 1
