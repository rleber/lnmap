"""`lnmap init` - create the lnmap config file from defaults if missing."""

from ..config import config_path, ensure_config
from . import app


@app.command()
def init() -> None:
    """Create the lnmap config file from defaults, if it doesn't already exist."""
    path = config_path()
    if path.exists():
        print(f"Config file already exists at {path}")
    else:
        ensure_config(path)
        print(f"Created config file at {path}")
