"""`lnmap group` - look for aliased/linked group of files."""

from pathlib import Path
from typing import Annotated

from typer import Argument, Option

from ..link_mapper import LinkMapper
from ..support.link_types import ValidTypes, parse_link_types
from ..support.output import OutputFormat, print_links
from ..support.progress import loud_logger, quiet_logger
from . import app


@app.command(name="group")
def list_groups(
    target: Annotated[
        Path,
        Argument(
            help="Path to search for alias/links around.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
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
            "--type",
            "-t",
            help="Select choices, or 'all' to select everything.",
        ),
    ] = None,
    force_index: Annotated[
        bool,
        Option(
            "-F",
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
    """Look for aliased/linked group of files."""
    if force_index:
        logger = quiet_logger if quiet else loud_logger
        LinkMapper.index(directory, logger)

    mapper = LinkMapper(directory)
    include = parse_link_types(link_types)
    links = mapper.find_group(include=include, target=target)
    print_links(links, output_format, quiet=quiet)
