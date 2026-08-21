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


def test_hard_link_detection(tmp_path: Path) -> None:
    file1 = tmp_path / "file1.txt"
    file1.write_text("hello world")

    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    # Single unlinked file
    file3 = tmp_path / "file3.txt"
    file3.write_text("single file")

    mapper = LinkMapper(tmp_path)
    links = mapper.find_links(update="all")

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
    links = mapper.find_links(update="all")

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
    links1 = mapper.find_links(update="all")
    assert len(links1) == 2
    assert db_file.exists()

    # Add new hard link and new symlink
    file3 = tmp_path / "file3.txt"
    os.link(file1, file3)

    sym2 = tmp_path / "sym2.txt"
    sym2.symlink_to(target)

    # Run with update="none" -> should return cached results
    links_cached = mapper.find_links(update="none")
    hard_cached = next(l for l in links_cached if l.link_type == "hard")
    sym_cached = next(l for l in links_cached if l.link_type == "sym")
    assert len(hard_cached.paths) == 2
    assert len(sym_cached.paths) == 1

    # Run with update="hard" -> should refresh hard links but keep cached symlinks
    links_partial = mapper.find_links(update="hard")
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

    links = mapper.find_links(update="all")

    assert custom_db.exists()
    assert not (tmp_path / DEFAULT_DB_NAME).exists()
    assert len(links) == 1


def test_progress_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file1 = tmp_path / "file1.txt"
    file1.write_text("data")
    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    mapper = LinkMapper(tmp_path)
    mapper.find_links(update="all", progress=True)

    captured = capsys.readouterr()
    assert "Scanning complete." in captured.err


def test_corrupted_db_fallback(tmp_path: Path) -> None:
    db_file = tmp_path / DEFAULT_DB_NAME
    db_file.write_text("not a valid sqlite file")

    file1 = tmp_path / "file1.txt"
    file1.write_text("data")
    file2 = tmp_path / "file2.txt"
    os.link(file1, file2)

    # Should safely handle DB connection error and rescan
    mapper = LinkMapper(tmp_path)
    links = mapper.find_links(update="none")
    assert len(links) == 1
