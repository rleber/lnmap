import argparse
import json
import sys
from pathlib import Path

from lnmap import DEFAULT_DB_NAME, Link, __version__, find_links


def format_path(path: Path) -> str:
    """Formats a Path object, wrapping it in double quotes and escaping if needed."""
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


def main(args: list[str] | None = None) -> None:
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="lnmap",
        description="Find and manage hard links, symlinks, and macOS aliases.",
    )
    # Define db-path on the root parser with a standard default
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

    list_parser = subparsers.add_parser(
        "list",
        help="Find and list links in a directory.",
        description="Find sets of files within a directory that share the same inode (hard links), point to targets (symlinks), or macOS aliases.",
    )
    # Define db-path on subparser with SUPPRESS so it doesn't overwrite root parser's value with None
    list_parser.add_argument(
        "--db-path",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Custom path for SQLite database file (default: <directory>/{DEFAULT_DB_NAME})",
    )
    list_parser.add_argument(
        "-u",
        "--update",
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

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize or overwrite the link database for a directory without listing links.",
        description="Scans for all link forms (hard links, symlinks, aliases) and populates or overwrites the SQLite cache without printing links.",
    )
    # Define db-path on subparser with SUPPRESS so it doesn't overwrite root parser's value with None
    init_parser.add_argument(
        "--db-path",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Custom path for SQLite database file (default: <directory>/{DEFAULT_DB_NAME})",
    )
    init_parser.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help="Display scanning progress indicator on stderr.",
    )
    init_parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Directory to scan (default: current directory)",
    )

    parsed_args = parser.parse_args(args)

    if parsed_args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    try:
        if parsed_args.subcommand == "list":
            links = find_links(
                parsed_args.directory,
                update=parsed_args.update,
                progress=parsed_args.progress,
                db_path=parsed_args.db_path,
            )
            print_links(links, output_format=parsed_args.format)
        elif parsed_args.subcommand == "init":
            find_links(
                parsed_args.directory,
                update="all",
                progress=parsed_args.progress,
                db_path=parsed_args.db_path,
            )
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
