"""
lnmap - Catalog hard links, symlinks and macOS aliases in a directory.

Package layout:
    link_mapper.py, config.py  Core library: scanning, the link database,
                               and config-file handling. Usable standalone,
                               with no dependency on the CLI.
    commands/                  One module per CLI subcommand, each
                               registering itself onto the shared Typer app.
    support/                   Helpers used only by commands/ (CLI-argument
                               enums, output formatting, progress logging).
                               Never imported by the core library.

Dependencies flow one way: commands/ -> support/ -> link_mapper.py/config.py.
"""

from .link_mapper import Link, LinkIndex, LinkMapper

__version__ = "1.0.0"

__all__ = ["Link", "LinkIndex", "LinkMapper"]
