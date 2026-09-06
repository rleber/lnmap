"""`lnmap indexes` - list database indexes found from directory up to root."""

from pathlib import Path
from typing import Annotated

from typer import Argument

from ..link_mapper import LinkMapper
from . import app


@app.command()
def indexes(
    directory: Annotated[
        Path,
        Argument(
            help="Directory to start searching from.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
        ),
    ] = Path("."),
) -> None:
    """List database indexes found from directory up to root."""
    found_indexes = LinkMapper.indexes(directory)
    if not found_indexes:
        print("No index files found.")
        return

    for idx in found_indexes:
        local_dt = idx.last_modified.astimezone()
        timestamp = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"{timestamp}  {idx.path}")
