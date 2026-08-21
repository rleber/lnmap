"""
lnmap - Core Library Module

Provides core abstractions for finding, categorizing, and caching file system links,
including hard links, symbolic links, and macOS file aliases.
"""

import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__version__ = "0.5.0"
DEFAULT_DB_NAME = ".lnmap_index.db"
PROGRESS_INTERVAL = 1000

UpdateMode = str | Iterable[str] | bool

if sys.platform == "darwin":
    try:
        from macos_alias import is_alias, target_of

        HAS_MACOS_ALIAS = True
    except ImportError:
        HAS_MACOS_ALIAS = False
else:
    HAS_MACOS_ALIAS = False


@dataclass(frozen=True)
class Link:
    """Encapsulates information about a hard link set, symlink set, or macOS alias set."""

    link_type: Literal["hard", "sym", "alias"]
    key: int | Path
    paths: tuple[Path, ...]

    @property
    def inode(self) -> int | None:
        """Returns the inode number if this is a hard link, otherwise None."""
        return self.key if isinstance(self.key, int) else None

    @property
    def target(self) -> Path | None:
        """Returns the target Path if this is a symlink or alias, otherwise None."""
        return self.key if isinstance(self.key, Path) else None


class LinkMapper:
    """Manages link scanning, caching, and database interaction for a given directory."""

    def __init__(
        self,
        directory: str | Path,
        db_path: str | Path | None = None,
    ) -> None:
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise ValueError(f"Target path '{directory}' is not a valid directory.")

        self.db_path = (
            Path(db_path).resolve() if db_path else self.directory / DEFAULT_DB_NAME
        )

    @classmethod
    def indexes(cls, directory: str | Path) -> list[Path]:
        """
        Searches for index database files starting from the specified directory
        and traversing up through parent directories.
        """
        target_dir = Path(directory).resolve()
        if not target_dir.is_dir():
            raise ValueError(f"Target path '{directory}' is not a valid directory.")

        current = target_dir
        found_indexes: list[Path] = []

        while True:
            candidate = current / DEFAULT_DB_NAME
            if candidate.is_file():
                found_indexes.append(candidate)

            if current.parent == current:
                break
            current = current.parent

        return found_indexes

    @classmethod
    def _parse_update_modes(cls, update: UpdateMode) -> set[str]:
        """Parses update argument into a set of target link types to update ('hard', 'sym', 'alias')."""
        if isinstance(update, bool):
            return {"hard", "sym", "alias"} if update else set()

        if isinstance(update, str):
            raw_items = [item.strip() for item in update.split(",") if item.strip()]
        else:
            raw_items = [str(item) for item in update]

        valid_types = {"hard", "sym", "alias"}
        valid_choices = valid_types | {"all", "none"}
        targets: set[str] = set()
        has_all = False

        for item in raw_items:
            if item not in valid_choices:
                raise ValueError(
                    f"Invalid update option '{item}'. Must be one or more of: hard, sym, alias, all, none."
                )
            if item == "all":
                has_all = True
            elif item != "none":
                targets.add(item)

        if has_all:
            return {"hard", "sym", "alias"}

        return targets

    def _save_to_db(
        self,
        hard_records: list[tuple[int, str]],
        sym_records: list[tuple[str, str]],
        alias_records: list[tuple[str, str]],
        update_targets: set[str],
    ) -> None:
        """Updates the database with the provided link records."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if "hard" in update_targets:
                    cursor.execute("DROP TABLE IF EXISTS hard_links;")
                    cursor.execute(
                        """
                        CREATE TABLE hard_links (
                            inode INTEGER NOT NULL,
                            path TEXT NOT NULL
                        );
                        """
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_hard_inode ON hard_links(inode);"
                    )
                    cursor.executemany(
                        "INSERT INTO hard_links (inode, path) VALUES (?, ?);",
                        hard_records,
                    )

                if "sym" in update_targets:
                    cursor.execute("DROP TABLE IF EXISTS sym_links;")
                    cursor.execute(
                        """
                        CREATE TABLE sym_links (
                            target TEXT NOT NULL,
                            path TEXT NOT NULL
                        );
                        """
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sym_target ON sym_links(target);"
                    )
                    cursor.executemany(
                        "INSERT INTO sym_links (target, path) VALUES (?, ?);",
                        sym_records,
                    )

                if "alias" in update_targets:
                    cursor.execute("DROP TABLE IF EXISTS alias_links;")
                    cursor.execute(
                        """
                        CREATE TABLE alias_links (
                            target TEXT NOT NULL,
                            path TEXT NOT NULL
                        );
                        """
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_alias_target ON alias_links(target);"
                    )
                    cursor.executemany(
                        "INSERT INTO alias_links (target, path) VALUES (?, ?);",
                        alias_records,
                    )

                conn.commit()
        except sqlite3.Error:
            # If database file is corrupted or unreadable, safely remove it and recreate from scratch
            if self.db_path.exists():
                try:
                    os.unlink(self.db_path)
                except OSError:
                    return
            self._save_to_db(hard_records, sym_records, alias_records, update_targets)

    def index(self, update: UpdateMode = "all", progress: bool = False) -> None:
        """
        Scans the directory for the specified link types and overwrites their information in the database.
        """
        update_targets = self._parse_update_modes(update)
        if not update_targets:
            return

        inode_map: dict[int, list[Path]] = defaultdict(list)
        sym_map: dict[Path, list[Path]] = defaultdict(list)
        alias_map: dict[Path, list[Path]] = defaultdict(list)
        scanned_count = 0

        for path in self.directory.rglob("*"):
            abs_p = path.resolve()
            if abs_p == self.db_path:
                continue

            scanned_count += 1
            if progress and (scanned_count % PROGRESS_INTERVAL == 0):
                sys.stderr.write(f"\rScanning: {scanned_count:,} items processed...")
                sys.stderr.flush()

            try:
                if "sym" in update_targets and path.is_symlink():
                    try:
                        resolved_target = path.resolve()
                        sym_map[resolved_target].append(abs_p)
                    except (OSError, FileNotFoundError):
                        pass
                    continue

                if (
                    HAS_MACOS_ALIAS
                    and "alias" in update_targets
                    and not path.is_symlink()
                    and path.is_file()
                ):
                    try:
                        if is_alias(path):
                            tgt = target_of(path)
                            if tgt is not None:
                                alias_map[Path(tgt).resolve()].append(abs_p)
                            continue
                    except Exception:
                        pass

                if (
                    "hard" in update_targets
                    and path.is_file()
                    and not path.is_symlink()
                ):
                    stat_info = path.stat()
                    if stat_info.st_nlink > 1:
                        inode_map[stat_info.st_ino].append(abs_p)

            except (OSError, PermissionError):
                continue

        if progress:
            sys.stderr.write(f"\rScanning complete. {scanned_count:,} items checked.\n")
            sys.stderr.flush()

        hard_records: list[tuple[int, str]] = []
        sym_records: list[tuple[str, str]] = []
        alias_records: list[tuple[str, str]] = []

        if "hard" in update_targets:
            for inode, paths in inode_map.items():
                unique_paths = tuple(sorted(set(paths)))
                if len(unique_paths) > 1:
                    hard_records.extend((inode, str(p)) for p in unique_paths)

        if "sym" in update_targets:
            for target, paths in sym_map.items():
                unique_paths = tuple(sorted(set(paths)))
                if unique_paths:
                    sym_records.extend((str(target), str(p)) for p in unique_paths)

        if "alias" in update_targets:
            for target, paths in alias_map.items():
                unique_paths = tuple(sorted(set(paths)))
                if unique_paths:
                    alias_records.extend((str(target), str(p)) for p in unique_paths)

        self._save_to_db(hard_records, sym_records, alias_records, update_targets)

    def find_links(self) -> list[Link]:
        """
        Retrieves all link records from the database and returns them as a list of Link objects.
        Returns an empty list if the database does not exist or is empty.
        """
        if not self.db_path.exists():
            return []

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('hard_links', 'sym_links', 'alias_links');"
                )
                tables = {row[0] for row in cursor.fetchall()}

                hard_rows = []
                sym_rows = []
                alias_rows = []

                if "hard_links" in tables:
                    cursor.execute(
                        "SELECT inode, path FROM hard_links ORDER BY inode, path;"
                    )
                    hard_rows = cursor.fetchall()

                if "sym_links" in tables:
                    cursor.execute(
                        "SELECT target, path FROM sym_links ORDER BY target, path;"
                    )
                    sym_rows = cursor.fetchall()

                if "alias_links" in tables:
                    cursor.execute(
                        "SELECT target, path FROM alias_links ORDER BY target, path;"
                    )
                    alias_rows = cursor.fetchall()

            hard_map: dict[int, list[Path]] = defaultdict(list)
            for inode, path_str in hard_rows:
                hard_map[inode].append(Path(path_str))

            sym_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in sym_rows:
                sym_map[Path(target_str)].append(Path(path_str))

            alias_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in alias_rows:
                alias_map[Path(target_str)].append(Path(path_str))

            links: list[Link] = []
            for inode, paths in hard_map.items():
                links.append(Link(link_type="hard", key=inode, paths=tuple(paths)))

            for target, paths in sym_map.items():
                links.append(Link(link_type="sym", key=target, paths=tuple(paths)))

            for target, paths in alias_map.items():
                links.append(Link(link_type="alias", key=target, paths=tuple(paths)))

            return links
        except sqlite3.Error:
            return []
