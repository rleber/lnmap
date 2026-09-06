"""Output formatting (text/json/yaml) shared by the `list` and `group` commands."""

import json
from enum import Enum

import yaml

from ..link_mapper import Link


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    YAML = "yaml"


def print_links(links: list[Link], format: OutputFormat, quiet: bool = False) -> None:
    text = format_links(links, format, quiet=quiet)
    if text:
        print(text)


def format_links(links: list[Link], format: OutputFormat, quiet: bool = False) -> str:
    if format == OutputFormat.JSON:
        text = format_links_as_json(links)
    elif format == OutputFormat.YAML:
        text = format_links_as_yaml(links)
    else:  # Text
        text = format_links_as_text(links, quiet=quiet)
    return text


def format_links_as_json(links: list[Link]) -> str:
    json_data = [
        {
            "type": link.link_type,
            "key": str(link.key),
            "paths": [str(p) for p in link.paths],
        }
        for link in links
    ]
    return json.dumps(json_data, indent=2)


def format_links_as_text(links: list[Link], quiet: bool = False) -> str:
    if not links:
        if quiet:
            return ""
        return "No links found."

    lines = []

    if not quiet:
        lines.append(f"Found {len(links)} link set(s):")

    for link in links:
        lines.append(f"[{link.link_type}] Key/Target: {link.key}")
        for p in link.paths:
            lines.append(f"  <- {p}")
    return "\n".join(lines)


def format_links_as_yaml(links: list[Link]) -> str:
    yaml_data = [
        {
            "type": link.link_type,
            "key": str(link.key),
            "paths": [str(p) for p in link.paths],
        }
        for link in links
    ]
    # sort_keys=False preserves dict order; default_flow_style=False enforces block structure
    return yaml.dump(yaml_data, sort_keys=False, default_flow_style=False)
