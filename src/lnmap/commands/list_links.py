"""`lnmap list` - query indexed links."""

from pathlib import Path
from typing import Annotated

from typer import Argument, Option

from ..link_mapper import LinkMapper
from ..support.link_types import ValidTypes, parse_link_types
from ..support.output import OutputFormat, print_links
from ..support.progress import loud_logger, quiet_logger
from . import app


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
            "--type",
            "-t",
            help="Select choices, or 'all' to select everything.",
        ),
    ] = None,
    inode: Annotated[
        str | None,
        Option(
            "--inode",
            "-I",
            help="Limit inodes using regular expression.",
        ),
    ] = None,
    target: Annotated[
        str | None,
        Option(
            "--target",
            "-T",
            help="Limit target paths using regular expression.",
        ),
    ] = None,
    path: Annotated[
        str | None,
        Option(
            "--path",
            "-P",
            help="Limit link paths using regular expression.",
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
    """Query indexed links."""
    if force_index:
        logger = quiet_logger if quiet else loud_logger
        LinkMapper.index(directory, logger)

    mapper = LinkMapper(directory)
    include = parse_link_types(link_types)
    regexps = {}
    if target:
        regexps["target"] = target
    if inode:
        regexps["inode"] = inode
    if path:
        regexps["path"] = path
    links = mapper.find_links(include=include, regexps=regexps)
    print_links(links, output_format, quiet=quiet)
