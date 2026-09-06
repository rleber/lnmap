"""lnmap configuration file: location, defaults, and loading.

The config file lives at $LNMAP_CONFIG if that environment variable is set,
otherwise at ~/.lnmap_config.yml. A new config file is seeded by copying
default_config.yml (shipped alongside this module) verbatim, so the default
values live in one obvious, version-controlled place rather than duplicated
in Python source.
"""

import os
import shutil
from pathlib import Path

import yaml

DEFAULT_CONFIG_NAME = ".lnmap_config.yml"
CONFIG_PATH_ENV_VAR = "LNMAP_CONFIG"
DEFAULT_CONFIG_RESOURCE = Path(__file__).parent / "default_config.yml"


def load_config(path: Path | None = None) -> dict:
    """Loads the config file, creating it from defaults first if missing."""
    path = ensure_config(path)
    with path.open() as f:
        return yaml.safe_load(f) or {}


def protected_subpaths(path: Path | None = None) -> tuple[str, ...]:
    """The configured list of $HOME-relative directories to skip while indexing."""
    return tuple(load_config(path).get("protected_dirs", []))


def ensure_config(path: Path | None = None) -> Path:
    """Creates the config file by copying the packaged defaults, if it
    doesn't already exist.

    Returns the path to the (now guaranteed to exist) config file. Silent by
    design: this runs as a side effect of ordinary indexing, not just of the
    explicit `init` command.
    """
    path = path or config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_CONFIG_RESOURCE, path)
    return path


def config_path() -> Path:
    """Resolves the config file path: $LNMAP_CONFIG if set, else ~/.lnmap_config.yml."""
    override = os.environ.get(CONFIG_PATH_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_CONFIG_NAME


def default_config() -> dict:
    """The config values a newly created config file is seeded with."""
    with DEFAULT_CONFIG_RESOURCE.open() as f:
        return yaml.safe_load(f) or {}
