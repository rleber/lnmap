"""`lnmap check` - report whether the last index run for a directory got stuck."""

from pathlib import Path
from typing import Annotated

from typer import Argument

from ..link_mapper import LinkMapper
from . import app


@app.command()
def check(
    directory: Annotated[
        Path,
        Argument(
            help="Directory to check for an incomplete-scan breadcrumb.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
        ),
    ] = Path("."),
) -> None:
    """Report whether the last `index` run for this directory got stuck partway through."""
    progress_path = LinkMapper.progress_for(directory)
    if not progress_path.exists():
        print(f"No incomplete-scan breadcrumb for {directory}.")
        return

    stuck_at = progress_path.read_text().strip()
    print(f"Indexing of {directory} did not complete last time.")
    print(f"Last directory reached before it stopped: {stuck_at}")
