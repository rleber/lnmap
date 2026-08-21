"""
lnmap - Command Line Interface

Parses CLI options and handles execution for subcommands:
`list`, `index`, and `indexes`.
"""

import argparse
import datetime
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


def _format_timestamp(db_path: Path) -> str:
    """Returns a human-readable string of the last modified time of the DB file."""
    try:
        mtime = db_path.stat().st_mtime
        dt = datetime.datetime.fromtimestamp(mtime)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "Unknown"


def handle_indexes(args: argparse.Namespace) -> None:
    """Handles the 'indexes' subcommand to list parent database index files."""
    target_dir = Path(args.directory).resolve()
    if not target_dir.is_dir():
        sys.stderr.write(
            f"Error: Target path '{args.directory}' is not a valid directory.\n"
        )
        sys.exit(1)

    current = target_dir
    found_indexes: list[Path] = []

    while True:
        candidate = current / DEFAULT_DB_NAME
        if candidate.is_file():
            found_indexes.append(candidate)

        if current.parent == current:
            break
        current = current.parent

    if not found_indexes:
        sys.stdout.write(f"No {DEFAULT_DB_NAME} files found in parent hierarchy.\n")
        return

    for idx_path in found_indexes:
        ts = _format_timestamp(idx_path)
        sys.stdout.write(f"{ts}  {idx_path}\n")


def handle_list(args: argparse.Namespace) -> None:
    """Handles the 'list' subcommand."""
    db_path = getattr(args, "db_path", None)
    try:
        mapper = LinkMapper(directory=args.directory, db_path=db_path)
        links = mapper.find_links(update=args.index, progress=args.progress)
        print_links(links, output_format=args.format)
    except ValueError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


def handle_index(args: argparse.Namespace) -> None:
    """Handles the 'index' subcommand."""
    db_path = getattr(args, "db_path", None)
    try:
        mapper = LinkMapper(directory=args.directory, db_path=db_path)
        mapper.find_links(update="all", progress=args.progress)
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
        help=f"Custom path for SQLite database file (default: <directory>/{DEFAULT_DB_NAME})",
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
        help=f"Custom path for SQLite database file (default: <directory>/{DEFAULT_DB_NAME})",
    )
    list_parser.add_argument(
        "-i",
        "--index",
        default="none",
        help="Specify which link types to update in the SQLite cache: hard, sym, alias, all, none, or comma-separated combinations like 'hard,alias' (default: none if omitted).",
    )
    list_parser.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help="Display scanning progress indicator on stderr.",
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
        "-p",
        "--progress",
        action="store_true",
        help="Display scanning progress indicator on stderr.",
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
