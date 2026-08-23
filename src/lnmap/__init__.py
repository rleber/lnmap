"""
lnmap - Core Library Module

Provides core abstractions for finding, categorizing, and caching file system links,
including hard links, symbolic links, and macOS file aliases.
"""

import contextlib
import datetime
import os
import sqlite3
import sys
import typing
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import re2  # Use google-re2 to protect against ReDOS attack

__version__ = "0.7.1"
DEFAULT_DB_NAME = ".lnmap_index.db"

UpdateMode = Iterable[str]

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
        directory: Path,
        db_path: Path | None = None,
    ) -> None:
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise ValueError(f"Target path '{directory}' is not a valid directory.")

        if db_path is not None:
            self.db_path = Path(db_path).resolve()
        else:
            self.db_path = self.index_for(self.directory)

    @staticmethod
    def db_for(directory: Path) -> Path:
        """Returns the name of the index database corresponding to a directory"""
        return Path(directory) / DEFAULT_DB_NAME

    @staticmethod
    def index_for(directory: Path) -> Path:
        """Finds the best existing index database for a directory.
        Scans up through the directory hierarchy from the given directory,
        looking for index files. Returns the newest index. In case of ties,
        it picks the index in the closest enclosing directory."""
        directory = directory.resolve()
        found_indexes = LinkMapper.indexes(directory)

        if found_indexes:
            best_index = max(found_indexes, key=lambda idx: idx.last_modified)
            return best_index.path

        return LinkMapper.db_for(directory)

    @classmethod
    def indexes(cls, directory: Path) -> list[LinkIndex]:
        """
        Searches for index database files starting from the specified directory
        and traversing up through parent directories, returning a list of LinkIndex
        objects.
        """
        target_dir = directory.resolve()
        if not target_dir.is_dir():
            raise ValueError(f"Target path '{directory}' is not a valid directory.")

        current = target_dir
        found_indexes: list[LinkIndex] = []

        while True:
            candidate = current / DEFAULT_DB_NAME
            if candidate.is_file():
                try:
                    mtime = candidate.stat().st_mtime
                    dt = datetime.datetime.fromtimestamp(
                        mtime, tz=datetime.timezone.utc
                    )
                except OSError:
                    dt = datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)
                found_indexes.append(LinkIndex(path=candidate, last_modified=dt))

            if current.parent == current:
                break
            current = current.parent

        return found_indexes

    TABLE_FIELDS: typing.ClassVar = {
        "hard_links": ["inode", "path"],
        "sym_links": ["target", "path"],
        "alias_links": ["target", "path"],
    }

    @staticmethod
    def _save_to_db(
        db: Path,
        hard_records: list[tuple[int, str]],
        sym_records: list[tuple[str, str]],
        alias_records: list[tuple[str, str]],
    ) -> None:
        """Updates the specified database file with all provided link records."""
        if db.exists():
            db.unlink()
        with (
            sqlite3.connect(db) as conn,
            contextlib.closing(conn.cursor()) as cursor,
        ):
            cursor.execute("PRAGMA journal_mode = MEMORY;")
            cursor.execute("PRAGMA synchronous = OFF;")

            cursor.execute("DROP TABLE IF EXISTS hard_links;")
            cursor.execute(
                """
                    CREATE TABLE hard_links (
                        inode INTEGER NOT NULL,
                        path TEXT NOT NULL
                    );
                    """
            )
            cursor.executemany(
                "INSERT INTO hard_links (inode, path) VALUES (?, ?);",
                hard_records,
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_hard_inode ON hard_links(inode);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_hard_path ON hard_links(path COLLATE BINARY, inode);"
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
            cursor.executemany(
                "INSERT INTO sym_links (target, path) VALUES (?, ?);",
                sym_records,
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sym_target ON sym_links(target);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sym_path ON sym_links(path COLLATE BINARY, target);"
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
            cursor.executemany(
                "INSERT INTO alias_links (target, path) VALUES (?, ?);",
                alias_records,
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_alias_target ON alias_links(target);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_alias_path ON alias_links(path COLLATE BINARY, target);"
            )

    @staticmethod
    def index(scan_directory: Path, logger: Callable) -> None:
        """
        Scans the directory containing the given database file for all links
        of any type and overwrites their information in the database.
        """
        scan_directory = scan_directory.resolve()
        resolved_db_path = LinkMapper.db_for(scan_directory)

        inode_map: dict[int, list[Path]] = defaultdict(list)
        sym_map: dict[Path, list[Path]] = defaultdict(list)
        alias_map: dict[Path, list[Path]] = defaultdict(list)
        scanned_count = 0

        for root_str, _, filenames in os.walk(scan_directory):
            for fname in filenames:
                path = Path(root_str) / fname
                # Construct canonical resolved path without following symlink if `path` is a symlink
                if path.is_symlink():
                    abs_p = path.parent.resolve() / path.name
                else:
                    abs_p = path.resolve()

                if abs_p == resolved_db_path:
                    continue

                scanned_count += 1
                logger(scanned_count)

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

    def find_links(
        self, include: set[str], regexps: dict[str, str] | None = None
    ) -> list[Link]:
        """
        Retrieves information about matching links from the database.
        Search is restricted to links within this directory, and may
        be restricted to only certain kinds of links or only links matching
        the link's inode, target, or path using regular expressions.
        """

        if not include:  # No kinds of links are allowed. Scram
            return []

        self._check_find_res(regexps)

        with (
            sqlite3.connect(self.db_path) as conn,
            contextlib.closing(conn.cursor()) as cursor,
        ):
            hard_rows = []
            sym_rows = []
            alias_rows = []

            conn.create_function(
                "REGEXP", 2, self.re2_regexp
            )  # Enable Regexp searching in SQLite3

            if "hard" in include:
                hard_rows = self._execute_find_query(
                    cursor, "hard_links", regexps=regexps
                )

            if "sym" in include:
                sym_rows = self._execute_find_query(
                    cursor, "sym_links", regexps=regexps
                )

            if "alias" in include:
                alias_rows = self._execute_find_query(
                    cursor, "alias_links", regexps=regexps
                )

            links: list[Link] = []

            hard_map: dict[int, list[Path]] = defaultdict(list)
            for inode, path_str in hard_rows:
                hard_map[inode].append(Path(path_str))

            for inode, paths in hard_map.items():
                if len(paths) > 1:
                    links.append(Link(link_type="hard", key=inode, paths=tuple(paths)))

            sym_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in sym_rows:
                sym_map[Path(target_str)].append(Path(path_str))

            for target, paths in sym_map.items():
                if paths:
                    links.append(Link(link_type="sym", key=target, paths=tuple(paths)))

            alias_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in alias_rows:
                alias_map[Path(target_str)].append(Path(path_str))

            for target, paths in alias_map.items():
                if paths:
                    links.append(
                        Link(link_type="alias", key=target, paths=tuple(paths))
                    )

            return links

    MAX_RE_LENGTH = 200  # Limit regexp size to reduce risk of ReDOS attack
    FIELD_MAPPING: typing.ClassVar = {
        "target": "target",
        "path": "path",
        "inode": "CAST(inode AS TEXT)",
    }

    @staticmethod
    def _check_find_res(regexps: dict[str, str] | None) -> None:
        """Validate searches: Valid label and regular expression not too long"""
        if regexps is None:
            return
        for label, regexp in regexps.items():
            if label not in LinkMapper.FIELD_MAPPING:
                raise ValueError(f"Invalid search target {label}")
            if len(regexp) > LinkMapper.MAX_RE_LENGTH:
                raise ValueError(
                    f"Search expression is too long (limit: {LinkMapper.MAX_RE_LENGTH} characters)."
                )

    def _execute_find_query(
        self, cursor, table: str, regexps: dict[str, str] | None = None
    ):
        """Execute a database query for find_links, with appropriate WHERE clauses."""
        where_clause, user_data = self._build_find_query(
            table=table,
            regexps=regexps,
        )
        fields = self.TABLE_FIELDS[table]
        field_list = ", ".join(fields)
        cursor.execute(
            f"""
            SELECT {field_list} FROM {table}
            WHERE {where_clause}
            ORDER BY {field_list};
            """,
            user_data,
        )
        return cursor.fetchall()

    def _build_find_query(
        self, table: str, regexps: dict[str, str] | None = None
    ) -> list[str, list[str, ...]]:
        """Build an appropriate WHERE clause for use in _execute_find_query"""
        limit_clause, limit_pattern = self._build_directory_limit_query()
        clauses = [limit_clause]
        data = [limit_pattern]
        if regexps is None:
            regexps = {}
        for field, regexp in regexps.items():
            if field in self.TABLE_FIELDS[table]:
                clauses.append(f"{self.FIELD_MAPPING[field]} REGEXP ?")
                data.append(regexp)

        joined_clauses = " AND ".join(clauses)
        return [joined_clauses, data]

    def _build_directory_limit_query(self) -> list[str, str]:
        dir_str = str(self.directory.resolve())
        if not dir_str.endswith(os.sep):
            dir_str += os.sep

        escaped_prefix = (
            dir_str.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        return ["path LIKE ? ESCAPE '\\'", f"{escaped_prefix}%"]

    @staticmethod
    def re2_regexp(pattern: str, string: str) -> bool:
        """A ReDoS-safe regex evaluation function using Google RE2,
        for use in find_links to allow searching via regular expression
        in SQLite3
        """
        try:
            # re2 compiles and executes in linear time, preventing ReDoS
            return bool(re2.search(pattern, string))
        except re2.error:
            # Handle invalid regex patterns entered by the user gracefully
            return False

    # TODO A more sophisticated version of this would allow for the case where
    #      multiple groups of soft linked files are aliased to different paths,
    #      but ultimately refer to the same physical file because their target
    #      paths are hard linked to the same inode. We might call these "cousins".
    #      This is probably a rare edge case. As written right now, this code
    #      won't find them.
    def find_group(self, include: set[str], target: Path) -> list[Link]:
        """
        Searches the database to find files that form an alias or link group,
        i.e. that all are aliased, symlinked, or hard linked to the same file.
        The members of the group must all be in the current directory. The
        search may be restricted to only certain kinds of links.
        """

        if not include:  # No kinds of links are allowed. Scram
            return []

        with (
            sqlite3.connect(self.db_path) as conn,
            contextlib.closing(conn.cursor()) as cursor,
        ):
            hard_rows = []
            sym_rows = []
            alias_rows = []

            if "hard" in include:
                hard_rows = self._execute_group_query(cursor, "hard_links", target)

            if "sym" in include:
                sym_rows = self._execute_group_query(cursor, "sym_links", target)

            if "alias" in include:
                alias_rows = self._execute_group_query(cursor, "alias_links", target)

            links: list[Link] = []

            hard_map: dict[int, list[Path]] = defaultdict(list)
            for inode, path_str in hard_rows:
                hard_map[inode].append(Path(path_str))

            for inode, paths in hard_map.items():
                if len(paths) > 1:
                    links.append(Link(link_type="hard", key=inode, paths=tuple(paths)))

            sym_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in sym_rows:
                sym_map[Path(target_str)].append(Path(path_str))

            for target_str, paths in sym_map.items():
                if paths:
                    links.append(
                        Link(link_type="sym", key=target_str, paths=tuple(paths))
                    )

            alias_map: dict[Path, list[Path]] = defaultdict(list)
            for target_str, path_str in alias_rows:
                alias_map[Path(target_str)].append(Path(path_str))

            for target_str, paths in alias_map.items():
                if paths:
                    links.append(
                        Link(link_type="alias", key=target_str, paths=tuple(paths))
                    )

            return links

    def _execute_group_query(self, cursor, table: str, target: Path):
        """Execute a database query for find_group, with appropriate WHERE clauses."""
        if table == "hard_links":
            rows = self._execute_hard_link_group_query(cursor, target)
        else:
            rows = self._execute_soft_link_group_query(cursor, table, target)
        return rows

    def _execute_hard_link_group_query(self, cursor, p: Path):
        limit_clause, limit_pattern = self._build_directory_limit_query()

        # Find the matching inode (if any)
        cursor.execute(
            f"""
            SELECT inode, path FROM hard_links
            WHERE {limit_clause}
              AND path = ?
            ORDER BY inode, path;
            """,
            [limit_pattern, str(p)],
        )
        matching_rows = cursor.fetchall()
        inodes = [inode for inode, _ in matching_rows]
        inode_count = len(set(inodes))
        if inode_count == 0:
            return []
        if inode_count > 1:  # This should never happen
            raise RuntimeError(f"Path {p} has more than one inode.")
        inode = inodes[0]
        cursor.execute(
            f"""
            SELECT inode, path FROM hard_links
            WHERE {limit_clause}
              AND inode = ?
            ORDER BY inode, path;
            """,
            [limit_pattern, inode],
        )
        return cursor.fetchall()

    def _execute_soft_link_group_query(self, cursor, table: str, p: Path):
        limit_clause, limit_pattern = self._build_directory_limit_query()

        # Find the matching target (if any)
        cursor.execute(
            f"""
            SELECT target, path FROM {table}
            WHERE {limit_clause}
              AND (
                path = ?
                OR target = ?
              )
            ORDER BY target, path;
            """,
            [limit_pattern, str(p), str(p)],
        )
        matching_rows = cursor.fetchall()
        targets = [target for target, _ in matching_rows]
        target_count = len(set(targets))
        if target_count == 0:
            return []
        if target_count > 1:  # This should never happen
            raise RuntimeError(f"Path {p} has more than matching alias or symlink.")
        target = targets[0]
        cursor.execute(
            f"""
            SELECT target, path FROM {table}
            WHERE {limit_clause}
              AND target = ?
            ORDER BY target, path;
            """,
            [limit_pattern, target],
        )
        return cursor.fetchall()
