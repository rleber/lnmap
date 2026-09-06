"""`lnmap index` - reindex a directory."""

from pathlib import Path
from typing import Annotated

from typer import Argument, Option

from ..link_mapper import LinkMapper
from ..support.progress import loud_logger, quiet_logger
from . import app


@app.command()
def index(
    directory: Annotated[
        Path,
        Argument(
            help="Directory to scan and index.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
        ),
    ] = Path("."),
    quiet: Annotated[
        bool,
        Option(
            "-q",
            "--quiet",
            help="Be quiet. Disables progress indicator.",
        ),
    ] = False,
) -> None:
    """Reindex a directory."""
    logger = quiet_logger if quiet else loud_logger
    LinkMapper.index(directory, logger)
    if not quiet:
        print(f"Updated index for {directory}")
