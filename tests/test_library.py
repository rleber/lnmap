import os
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
