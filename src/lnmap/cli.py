"""lnmap - Command Line Interface entrypoint

Catalog hard links, symlinks and aliases in a directory
"""

from .commands import app


def main() -> None:
    """CLI entrypoint wrapper."""
    app()


if __name__ == "__main__":
    main()
