"""
lnmap - Core Library Module

Provides core abstractions for finding, categorizing, and caching file system links,
including hard links, symbolic links, and macOS file aliases.
"""

import datetime
import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__version__ = "0.7.0"
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
class LinkIndex:
    """Encapsulates information about an index database file and its last modification date in UTC."""

    path: Path
    last_modified: datetime.datetime


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
        if db_path is None:
            self.db_path = self.index_for(self.directory)
        else:
            self.db_path = db_path.resolve()

    @staticmethod
    def index_for(
        directory: str | Path,
    ) -> Path:
        """Resolves the best database path for a directory"""

        target_dir = Path(directory).resolve()
        found_indexes = LinkMapper.indexes(target_dir)

        if found_indexes:
            best_index = max(found_indexes, key=lambda idx: idx.last_modified)
            return best_index.path
        else:
            return target_dir / DEFAULT_DB_NAME

    @classmethod
    def indexes(cls, directory: str | Path) -> list[LinkIndex]:
        """
        Searches for index database files starting from the specified directory
        and traversing up through parent directories, returning a list of LinkIndex objects with last_modified in UTC.
        """
        target_dir = Path(directory).resolve()
        if not target_dir.is_dir():
            raise ValueError(f"Target path '{directory}' is not a valid directory.")

        current = target_dir
        found_indexes: list[LinkIndex] = []

        while True:
            candidate = current / DEFAULT_DB_NAME
            if candidate.is_file():
                try:
                    mtime = candidate.stat().st_mtime
                    dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.UTC)
                except OSError:
                    dt = datetime.datetime.fromtimestamp(0, tz=datetime.UTC)
                found_indexes.append(LinkIndex(path=candidate, last_modified=dt))

            if current.parent == current:
                break
            current = current.parent

        return found_indexes

    @classmethod
    def _parse_update_modes(cls, update: UpdateMode) -> set[str]:
        """Parses include argument into a set of target link types ('hard', 'sym', 'alias')."""
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
                    f"Invalid option '{item}'. Must be one or more of: hard, sym, alias, all, none."
                )
            if item == "all":
                has_all = True
            elif item != "none":
                targets.add(item)

        if has_all:
            return {"hard", "sym", "alias"}

        return targets

    @staticmethod
    def _save_to_db(
        db_path: str | Path,
        hard_records: list[tuple[int, str]],
        sym_records: list[tuple[str, str]],
        alias_records: list[tuple[str, str]],
    ) -> None:
        """Updates the specified database file with all provided link records."""
        target_db = Path(db_path)
        try:
            with sqlite3.connect(target_db) as conn:
                cursor = conn.cursor()

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
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_hard_path ON hard_links(path COLLATE BINARY, inode);"
                )
                cursor.executemany(
                    "INSERT INTO hard_links (inode, path) VALUES (?, ?);",
                    hard_records,
                )

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
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sym_path ON sym_links(path COLLATE BINARY, target);"
                )
                cursor.executemany(
                    "INSERT INTO sym_links (target, path) VALUES (?, ?);",
                    sym_records,
                )

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
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alias_path ON alias_links(path COLLATE BINARY, target);"
                )
                cursor.executemany(
                    "INSERT INTO alias_links (target, path) VALUES (?, ?);",
                    alias_records,
                )

                conn.commit()
        except sqlite3.Error:
            # If database file is corrupted or unreadable, safely remove it and recreate from scratch
            if target_db.exists():
                try:
                    os.unlink(target_db)
                except OSError:
                    return
            LinkMapper._save_to_db(target_db, hard_records, sym_records, alias_records)

    @staticmethod
    def index(db_path: str | Path, progress: bool = False) -> None:
        """
        Scans the directory containing the given database file for all link types
        and overwrites their information in the database.
        """
        resolved_db_path = Path(db_path).resolve()
        scan_directory = resolved_db_path.parent

        inode_map: dict[int, list[Path]] = defaultdict(list)
        sym_map: dict[Path, list[Path]] = defaultdict(list)
        alias_map: dict[Path, list[Path]] = defaultdict(list)
        scanned_count = 0

        for path in scan_directory.rglob("*"):
            abs_p = path.resolve()
            if abs_p == resolved_db_path:
                continue

            scanned_count += 1
            if progress and (scanned_count % PROGRESS_INTERVAL == 0):
                sys.stderr.write(f"\rScanning: {scanned_count:,} items processed...")
                sys.stderr.flush()

            try:
                if path.is_symlink():
                    try:
                        resolved_target = path.resolve()
                        sym_map[resolved_target].append(abs_p)
                    except (OSError, FileNotFoundError):
                        pass
                    continue

                if HAS_MACOS_ALIAS and not path.is_symlink() and path.is_file():
                    try:
                        if is_alias(path):
                            tgt = target_of(path)
                            if tgt is not None:
                                alias_map[Path(tgt).resolve()].append(abs_p)
                            continue
                    except Exception:  # noqa
                        pass

                if path.is_file() and not path.is_symlink():
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

        for inode, paths in inode_map.items():
            unique_paths = tuple(sorted(set(paths)))
            if len(unique_paths) > 1:
                hard_records.extend((inode, str(p)) for p in unique_paths)

        for target, paths in sym_map.items():
            unique_paths = tuple(sorted(set(paths)))
            if unique_paths:
                sym_records.extend((str(target), str(p)) for p in unique_paths)

        for target, paths in alias_map.items():
            unique_paths = tuple(sorted(set(paths)))
            if unique_paths:
                alias_records.extend((str(target), str(p)) for p in unique_paths)

        LinkMapper._save_to_db(
            resolved_db_path, hard_records, sym_records, alias_records
        )

    def find_links(self, include: UpdateMode = "all") -> list[Link]:
        """
        Retrieves link records from the database matching specified include types,
        using indexed LIKE queries to efficiently fetch only paths under self.directory.
        """
        if not self.db_path.exists():
            return []

        include_targets = self._parse_update_modes(include)
        if not include_targets:
            return []

        # Prepare prefix matching string for SQLite LIKE query
        dir_str = str(self.directory.resolve())
        if not dir_str.endswith(os.sep):
            dir_str += os.sep

        # Escape wildcard characters % and _ so they are matched literally
        escaped_prefix = (
            dir_str.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        like_pattern = f"{escaped_prefix}%"

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

                if "hard" in include_targets and "hard_links" in tables:
                    cursor.execute(
                        """
                            SELECT inode, path FROM hard_links
                            WHERE path LIKE ? ESCAPE '\\'
                            ORDER BY inode, path;
                            """,
                        (like_pattern,),
                    )
                    hard_rows = cursor.fetchall()

                if "sym" in include_targets and "sym_links" in tables:
                    cursor.execute(
                        """
                            SELECT target, path FROM sym_links
                            WHERE path LIKE ? ESCAPE '\\'
                            ORDER BY target, path;
                            """,
                        (like_pattern,),
                    )
                    sym_rows = cursor.fetchall()

                if "alias" in include_targets and "alias_links" in tables:
                    cursor.execute(
                        """
                            SELECT target, path FROM alias_links
                            WHERE path LIKE ? ESCAPE '\\'
                            ORDER BY target, path;
                            """,
                        (like_pattern,),
                    )
                    alias_rows = cursor.fetchall()

            links: list[Link] = []

            # Group hard links
            hard_map: dict[int, list[Path]] = defaultdict(list)
            for inode, path_str in hard_rows:
                hard_map[inode].append(Path(path_str))

            for inode, paths in hard_map.items():
                if len(paths) > 1:
                    links.append(Link(link_type="hard", key=inode, paths=tuple(paths)))

            # Group symlinks
            sym_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in sym_rows:
                sym_map[Path(target_str)].append(Path(path_str))

            for target, paths in sym_map.items():
                if paths:
                    links.append(Link(link_type="sym", key=target, paths=tuple(paths)))

            # Group aliases
            alias_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in alias_rows:
                alias_map[Path(target_str)].append(Path(path_str))

            for target, paths in alias_map.items():
                if paths:
                    links.append(
                        Link(link_type="alias", key=target, paths=tuple(paths))
                    )

            return links
        except sqlite3.Error:
            return []
