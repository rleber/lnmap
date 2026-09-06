import os
from pathlib import Path

import pytest


@pytest.fixture
def root_dir(tmp_path: Path) -> Path:
    """Provides a resolved temporary directory Path instance."""
    return tmp_path.resolve()


def make_hardlink(source: Path, link: Path) -> None:
    """Create a hard link at `link` pointing to `source`.

    Skips the calling test if the filesystem/OS doesn't support hard links,
    matching the behavior every test in this suite already relied on
    individually.
    """
    try:
        os.link(source, link)
    except OSError:
        pytest.skip("Hard links not supported on this filesystem/OS")


@pytest.fixture
def home_dir(monkeypatch: pytest.MonkeyPatch, root_dir: Path) -> Path:
    """Redirects Path.home() to a temporary directory for the duration of a test."""
    monkeypatch.setattr(Path, "home", lambda: root_dir)
    return root_dir
