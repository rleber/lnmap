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

__version__ = "0.4.0"
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

    def _load_from_db(self) -> list[Link] | None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('hard_links', 'sym_links', 'alias_links');"
                )
                tables = {row[0] for row in cursor.fetchall()}
                if "hard_links" not in tables or "sym_links" not in tables:
                    return None

                cursor.execute(
                    "SELECT inode, path FROM hard_links ORDER BY inode, path;"
                )
                hard_rows = cursor.fetchall()

                cursor.execute(
                    "SELECT target, path FROM sym_links ORDER BY target, path;"
                )
                sym_rows = cursor.fetchall()

                alias_rows = []
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
            return None

    def _save_to_db(
        self,
        links: list[Link],
        update_targets: set[str],
    ) -> None:
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
                    hard_records = [
                        (link.key, str(p))
                        for link in links
                        if link.link_type == "hard"
                        for p in link.paths
                    ]
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
                    sym_records = [
                        (str(link.key), str(p))
                        for link in links
                        if link.link_type == "sym"
                        for p in link.paths
                    ]
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
                    alias_records = [
                        (str(link.key), str(p))
                        for link in links
                        if link.link_type == "alias"
                        for p in link.paths
                    ]
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
            self._save_to_db(links, update_targets)

    def find_links(
        self,
        update: UpdateMode = "none",
        progress: bool = False,
    ) -> list[Link]:
        """
        Scans the directory recursively for hard links, symlinks, and macOS aliases.
        Stores and retrieves results using the SQLite database cache.
        """
        requested_targets = self._parse_update_modes(update)

        db_exists = self.db_path.exists()
        cached_links: list[Link] | None = None
        if db_exists:
            cached_links = self._load_from_db()

        if cached_links is None:
            update_targets = {"hard", "sym", "alias"}
        else:
            update_targets = requested_targets

        if db_exists and not update_targets and cached_links is not None:
            return cached_links

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
                sys.stderr.write(f"\rScanning: {scanned_count} items processed...")
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
                        inode_map[stat_info.st_ino].append(path.resolve())

            except (OSError, PermissionError):
                continue

        if progress:
            sys.stderr.write(f"\rScanning complete. {scanned_count} items checked.\n")
            sys.stderr.flush()

        scanned_links: list[Link] = []

        if "hard" in update_targets:
            for inode, paths in inode_map.items():
                unique_paths = tuple(sorted(set(paths)))
                if len(unique_paths) > 1:
                    scanned_links.append(
                        Link(link_type="hard", key=inode, paths=unique_paths)
                    )

        if "sym" in update_targets:
            for target, paths in sym_map.items():
                unique_paths = tuple(sorted(set(paths)))
                if unique_paths:
                    scanned_links.append(
                        Link(link_type="sym", key=target, paths=unique_paths)
                    )

        if "alias" in update_targets:
            for target, paths in alias_map.items():
                unique_paths = tuple(sorted(set(paths)))
                if unique_paths:
                    scanned_links.append(
                        Link(link_type="alias", key=target, paths=unique_paths)
                    )

        self._save_to_db(scanned_links, update_targets)

        if cached_links is not None:
            cached_unupdated = [
                l for l in cached_links if l.link_type not in update_targets
            ]
            return scanned_links + cached_unupdated

        return scanned_links
