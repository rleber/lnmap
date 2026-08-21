"""
lnmap - Command Line Interface

Parses CLI options and handles execution for subcommands:
`list`, `index`, and `indexes`.
"""

import argparse
import json
import sys
from pathlib import Path

from lnmap import DEFAULT_DB_NAME, Link, LinkMapper, __version__


def format_path(path: Path) -> str:
    """Formats a Path object, wrapping it in double quotes and escaping special characters if needed."""
    path_str = str(path)
    special_chars = set(" \t\n\r\f\v\"'\\$`!&*()[]{};<>?|~#")

    if any(c in special_chars for c in path_str):
        escaped = (
            path_str.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        return f'"{escaped}"'
    return path_str


def print_links(
    links: list[Link],
    output_format: str = "text",
) -> None:
    """Prints link mapping results to stdout in text or jsonlines format."""
    if output_format == "json":
        for link in links:
            if link.link_type == "hard":
                record = {
                    "type": "hard",
                    "inode": link.key,
                    "paths": [str(p) for p in link.paths],
                }
            else:
                record = {
                    "type": link.link_type,
                    "target": str(link.key),
                    "paths": [str(p) for p in link.paths],
                }
            print(json.dumps(record))
    else:
        for link in links:
            paths_str = ", ".join(format_path(p) for p in link.paths)
            if link.link_type == "hard":
                print(f"{link.key} #= {paths_str}")
            elif link.link_type == "sym":
                target_path = Path(str(link.key))
                print(f"{format_path(target_path)} @= {paths_str}")
            elif link.link_type == "alias":
                target_path = Path(str(link.key))
                print(f"{format_path(target_path)} a= {paths_str}")


def handle_indexes(args: argparse.Namespace) -> None:
    """Handles the 'indexes' subcommand to list parent database index files."""
    try:
        found_indexes = LinkMapper.indexes(args.directory)
    except ValueError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

    if not found_indexes:
        sys.stdout.write(f"No {DEFAULT_DB_NAME} files found in parent hierarchy.\n")
        return

    for idx in found_indexes:
        local_dt = idx.last_modified.astimezone()
        ts = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        sys.stdout.write(f"{ts}  {idx.path}\n")


def handle_list(args: argparse.Namespace) -> None:
    """Handles the 'list' subcommand."""
    db_path = getattr(args, "db_path", None)
    if db_path is None:
        resolved_db = LinkMapper.index_for(args.directory)
    else:
        resolved_db = Path(db_path).resolve()
    try:
        if args.index:
            LinkMapper.index(resolved_db, progress=not args.quiet)

        mapper = LinkMapper(directory=args.directory, db_path=resolved_db)
        links = mapper.find_links(include=args.include)
        print_links(links, output_format=args.format)
    except ValueError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


def handle_index(args: argparse.Namespace) -> None:
    """Handles the 'index' subcommand."""
    db_path = getattr(args, "db_path", None)
    if db_path is None:
        db_path = Path(args.directory).resolve() / DEFAULT_DB_NAME

    try:
        LinkMapper.index(db_path, progress=not args.quiet)
    except ValueError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


def main(args: list[str] | None = None) -> None:
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="lnmap",
        description="Find and manage hard links, symlinks, and macOS aliases.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help=f"Custom path for SQLite database file (default: automatically selected from parent tree or <directory>/{DEFAULT_DB_NAME})",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Subcommand: list
    list_parser = subparsers.add_parser(
        "list",
        help="Find and list links in a directory.",
        description="Find sets of files within a directory that share the same inode (hard links), point to targets (symlinks), or macOS aliases.",
    )
    list_parser.add_argument(
        "--db-path",
        type=Path,
        default=argparse.SUPPRESS,
        help="Custom path for SQLite database file (default: automatically select newest parent index)",
    )
    list_parser.add_argument(
        "-I",
        "--index",
        action="store_true",
        help="Update the index database before listing links.",
    )
    list_parser.add_argument(
        "-i",
        "--include",
        default="all",
        help="Specify which link types to include in output: hard, sym, alias, all, none, or comma-separated combinations (default: all).",
    )
    list_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress scanning progress indicator on stderr when indexing.",
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json (jsonlines).",
    )
    list_parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Directory to scan (default: current directory)",
    )

    # Subcommand: index
    index_parser = subparsers.add_parser(
        "index",
        help="Update index database of all links in a directory",
        description="Scans for all link forms (hard links, symlinks, aliases) and populates or overwrites the SQLite cache without printing links.",
    )
    index_parser.add_argument(
        "--db-path",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Custom path for SQLite database file (default: <directory>/{DEFAULT_DB_NAME})",
    )
    index_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress scanning progress indicator on stderr.",
    )
    index_parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Directory to scan (default: current directory)",
    )

    # Subcommand: indexes
    indexes_parser = subparsers.add_parser(
        "indexes",
        help="Find and list index database files up the directory tree.",
    )
    indexes_parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Starting directory to search upward from (default: current directory)",
    )

    parsed_args = parser.parse_args(args)

    if parsed_args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    if parsed_args.subcommand == "list":
        handle_list(parsed_args)
    elif parsed_args.subcommand == "index":
        handle_index(parsed_args)
    elif parsed_args.subcommand == "indexes":
        handle_indexes(parsed_args)


if __name__ == "__main__":
    main()
