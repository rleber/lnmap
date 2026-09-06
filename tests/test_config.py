from pathlib import Path

import pytest
import yaml

import lnmap
from lnmap.config import (
    DEFAULT_CONFIG_RESOURCE,
    config_path,
    default_config,
    ensure_config,
    load_config,
    protected_subpaths,
)

# --- Tests for load_config ---


def test_load_config_creates_then_returns_defaults_when_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yml"
    assert load_config(path) == default_config()
    assert path.exists()


def test_load_config_returns_existing_customized_content(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(yaml.dump({"protected_dirs": ["Custom/Dir"], "extra": "value"}))

    assert load_config(path) == {"protected_dirs": ["Custom/Dir"], "extra": "value"}


# --- Tests for protected_subpaths ---


def test_protected_subpaths_returns_configured_list(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(yaml.dump({"protected_dirs": ["A/B", "C/D"]}))

    assert protected_subpaths(path) == ("A/B", "C/D")


def test_protected_subpaths_empty_when_key_missing(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(yaml.dump({"unrelated": "value"}))

    assert protected_subpaths(path) == ()


def test_protected_subpaths_creates_default_config_when_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yml"
    assert protected_subpaths(path) == tuple(default_config()["protected_dirs"])
    assert path.exists()


# --- Tests for ensure_config ---


def test_ensure_config_creates_file_with_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    result = ensure_config(path)

    assert result == path
    assert path.exists()
    assert yaml.safe_load(path.read_text()) == default_config()


def test_ensure_config_copies_packaged_file_verbatim(tmp_path: Path) -> None:
    """ensure_config() is a plain file copy, so comments in the shipped
    default_config.yml survive into a newly created config file."""
    path = tmp_path / "config.yml"
    ensure_config(path)
    assert path.read_text() == DEFAULT_CONFIG_RESOURCE.read_text()


def test_ensure_config_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "config.yml"
    ensure_config(path)
    assert path.exists()


def test_ensure_config_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(yaml.dump({"protected_dirs": ["Custom/Dir"]}))

    ensure_config(path)

    assert yaml.safe_load(path.read_text()) == {"protected_dirs": ["Custom/Dir"]}


# --- Tests for config_path ---


def test_config_path_respects_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LNMAP_CONFIG", "/some/custom/path.yml")
    assert config_path() == Path("/some/custom/path.yml")


def test_config_path_expands_user_in_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LNMAP_CONFIG", "~/custom_config.yml")
    assert config_path() == Path.home() / "custom_config.yml"


def test_config_path_falls_back_to_home_when_env_var_unset(
    monkeypatch: pytest.MonkeyPatch, home_dir: Path
) -> None:
    monkeypatch.delenv("LNMAP_CONFIG", raising=False)
    assert config_path() == home_dir / ".lnmap_config.yml"


# --- Tests for default_config ---


def test_default_config_matches_packaged_yaml_file() -> None:
    with DEFAULT_CONFIG_RESOURCE.open() as f:
        expected = yaml.safe_load(f)

    assert default_config() == expected
    assert "protected_dirs" in default_config()


def test_default_config_resource_ships_in_the_package() -> None:
    """default_config.yml must be packaged alongside lnmap's source, not
    merely present by coincidence of running tests from a checkout."""
    assert (
        DEFAULT_CONFIG_RESOURCE == Path(lnmap.__file__).parent / "default_config.yml"
    )
    assert DEFAULT_CONFIG_RESOURCE.exists()
