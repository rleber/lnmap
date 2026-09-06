"""CLI commands for lnmap, each registered onto a shared Typer app.

Every command lives in its own module (index.py, list_links.py, group.py,
indexes.py, init.py) and registers itself onto `app` via the @app.command()
decorator when imported below.
"""

from typing import Annotated

import typer
from typer import Option

from .. import __version__

app = typer.Typer(
    name="lnmap",
    help="Scans, maps, and caches filesystem links (hard links, symlinks, macOS aliases).",
    add_completion=False,
)


def version_callback(value: bool) -> None:
    """Print program version and exit."""
    if value:
        print(f"lnmap {__version__}")
        raise typer.Exit()


@app.callback()
def global_options(
    version: Annotated[
        bool | None,
        Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show application version and exit.",
        ),
    ] = None,
) -> None:
    """Global callback for top-level flags like --version."""


# Imported for their side effect of registering commands onto `app`; must
# follow the `app` definition above, since each module does `from . import app`.
from . import group, index, indexes, init, list_links  # noqa: F401
