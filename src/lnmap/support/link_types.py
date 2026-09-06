"""Link-type selection shared by the `list` and `group` commands."""

from enum import Enum


class ValidTypes(str, Enum):
    ALL = "all"
    ALIAS = "alias"
    HARDLINK = "hard"
    SYMLINK = "sym"


def parse_link_types(types: list[str] | None) -> set[str]:
    """Parse comma-separated link type argument into a normalized set."""
    if types is None or ValidTypes.ALL in types:
        types = {item.value for item in ValidTypes if item != ValidTypes.ALL}
    else:
        types = {item.value for item in types}
    return types
