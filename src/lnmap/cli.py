"""
lnmap - Command Line Interface
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import LinkMapper, __version__


def main(args: Sequence[str] | None = None) -> None:
    """CLI entrypoint for index generation and link queries."""
    parser = argparse.ArgumentParser(
        prog="lnmap",
        description="Scans, maps, and caches filesystem links (hard links, symlinks, macOS aliases).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # index command
    index_parser = subparsers.add_parser("index", help="Reindex a directory")
    index_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan and index (default: current directory)",
    )
    index_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Be quiet. Disables progress indicator",
    )

    # list subcommand
    list_parser = subparsers.add_parser("list", help="Query indexed links")
    list_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to search within (default: current directory)",
    )
    list_parser.add_argument(
        "-t",
        "--type",
        default="all",
        help="Link types to include: hard, sym, alias, or all (comma-separated, default: all)",
    )
    list_parser.add_argument(
        "-I",
        "--index",
        action="store_true",
        help="Force index update before searching",
    )
    list_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress human-readable summary header",
    )
    list_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    # indexes command
    indexes_parser = subparsers.add_parser(
        "indexes", help="List database indexes found from directory up to root"
    )
    indexes_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to start searching from (default: current directory)",
    )

    parsed_args = parser.parse_args(args if args is not None else sys.argv[1:])

    if not parsed_args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if parsed_args.command == "index":
            target_dir = Path(parsed_args.directory).resolve()
            LinkMapper.index(target_dir, quiet=parsed_args.quiet)
            if not parsed_args.quiet:
                print(f"Updated index for {target_dir}")

        elif parsed_args.command == "list":
            target_dir = Path(parsed_args.directory).resolve()
            if parsed_args.index:
                db_path = LinkMapper.index_for(target_dir)
                LinkMapper.index(db_path)

            mapper = LinkMapper(target_dir)
            links = mapper.find_links(include=parsed_args.type)

            if parsed_args.format == "json":
                json_data = [
                    {
                        "type": link.link_type,
                        "key": str(link.key),
                        "paths": [str(p) for p in link.paths],
                    }
                    for link in links
                ]
                print(json.dumps(json_data, indent=2))
            else:
                if not links:
                    if not parsed_args.quiet:
                        print("No links found.")
                    return

                if not parsed_args.quiet:
                    print(f"Found {len(links)} link set(s):")

                for link in links:
                    print(f"[{link.link_type.upper()}] Key/Target: {link.key}")
                    for p in link.paths:
                        print(f"  -> {p}")

        elif parsed_args.command == "indexes":
            target_dir = Path(parsed_args.directory).resolve()
            found_indexes = LinkMapper.indexes(target_dir)
            if not found_indexes:
                print("No index files found.")
                return

            for idx in found_indexes:
                print(f"{idx.path} (last modified: {idx.last_modified})")

    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
