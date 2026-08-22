"""lnmap - Command Line Interface

Catalog hard links, symlinks and aliases in a directory
"""

import json
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from typer import Argument, Option

from . import LinkMapper, __version__

app = typer.Typer(
    name="lnmap",
    help="Scans, maps, and caches filesystem links (hard links, symlinks, macOS aliases).",
    add_completion=False,
)

PROGRESS_INTERVAL = 1000


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"


def version_callback(value: bool) -> None:
    """Print program version and exit."""
    if value:
        typer.echo(f"lnmap {__version__}")
        raise typer.Exit()


VALID_TYPES = {"all", "alias", "hard", "sym"}


def parse_link_types(types: list[str] | None) -> set[str]:
    """Parse comma-separated link type argument into a normalized set."""
    if types is None or ValidTypes.ALL in types:
        types = {item.value for item in ValidTypes if item != ValidTypes.ALL}
    else:
        types = {item.value for item in types}
    return types


def loud_logger(count: int) -> None:
    if count % PROGRESS_INTERVAL == 0:
        typer.echo(f"\rScanning: {count:,} items processed...", err=True, nl=False)


def quiet_logger(count: int) -> None:
    pass


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
        typer.echo(f"Updated index for {directory}")


# 1. Define allowed choices including "all"
class ValidTypes(str, Enum):
    ALL = "all"
    ALIAS = "alias"
    HARDLINK = "hard"
    SYMLINK = "sym"


@app.command(name="list")
def list_links(
    directory: Annotated[
        Path,
        Argument(
            help="Directory to search within.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
        ),
    ] = Path("."),
    link_types: Annotated[
        list[ValidTypes] | None,
        Option(
            ...,
            "--fruit",
            "-f",
            help="Select choices, or 'all' to select everything.",
        ),
    ] = None,
    force_index: Annotated[
        bool,
        Option(
            "-I",
            "--index",
            help="Force index update before searching.",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        Option(
            "-q",
            "--quiet",
            help="Quiet mode.",
        ),
    ] = False,
    output_format: Annotated[
        OutputFormat,
        Option(
            "--format",
            case_sensitive=False,
            help="Output format.",
        ),
    ] = OutputFormat.TEXT,
) -> None:
    """Query indexed links."""
    if force_index:
        db_path = LinkMapper.index_for(directory)
        logger = quiet_logger if quiet else loud_logger
        LinkMapper.index(db_path, logger)

    mapper = LinkMapper(directory)
    include = parse_link_types(link_types)
    links = mapper.find_links(include=include)

    if output_format == OutputFormat.JSON:
        json_data = [
            {
                "type": link.link_type,
                "key": str(link.key),
                "paths": [str(p) for p in link.paths],
            }
            for link in links
        ]
        typer.echo(json.dumps(json_data, indent=2))
    else:
        if not links:
            if not quiet:
                typer.echo("No links found.")
            return

        if not quiet:
            typer.echo(f"Found {len(links)} link set(s):")

        for link in links:
            typer.echo(f"[{link.link_type.upper()}] Key/Target: {link.key}")
            for p in link.paths:
                typer.echo(f"  -> {p}")


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
        typer.echo("No index files found.")
        return

    for idx in found_indexes:
        local_dt = idx.last_modified.astimezone()
        timestamp = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        typer.echo(f"{timestamp}  {idx.path}")


def main() -> None:
    """CLI entrypoint wrapper."""
    app()


if __name__ == "__main__":
    main()
