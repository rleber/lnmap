import os
from pathlib import Path

import pytest


@pytest.fixture
def root_dir(tmp_path: Path) -> Path:
    """Provides a resolved temporary directory Path instance."""
    return tmp_path.resolve()


@pytest.fixture
def home_dir(monkeypatch: pytest.MonkeyPatch, root_dir: Path) -> Path:
    """Redirects Path.home() to a temporary directory for the duration of a test."""
    monkeypatch.setattr(Path, "home", lambda: root_dir)
    return root_dir


@pytest.fixture(autouse=True)
def isolated_lnmap_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Points $LNMAP_CONFIG at a per-test path for every test.

    LinkMapper.index() reads the lnmap config file (and creates it from
    defaults if missing) on every call on macOS. Without this, the entire
    suite would read and write the developer's real ~/.lnmap_config.yml.
    """
    config_path = tmp_path / ".lnmap_config.yml"
    monkeypatch.setenv("LNMAP_CONFIG", str(config_path))
    return config_path


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
