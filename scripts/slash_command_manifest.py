"""Validate and resolve per-consumer Familia slash-command manifests.

This is the small shared contract. Runtime consumers should call this module
instead of maintaining separate alias and help-token tables.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


_CANONICAL = re.compile(r"^familia-[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_-]*$")


class ManifestError(ValueError):
    """Raised when a slash-command manifest is ambiguous or malformed."""


@dataclass(frozen=True)
class Invocation:
    command: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class Consumer:
    aliases: Mapping[str, Invocation]
    exposed: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    commands: frozenset[str]
    consumers: Mapping[str, Consumer]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def parse_manifest(data: Any) -> Manifest:
    """Validate JSON-shaped manifest data and return a resolved registry."""
    _require(isinstance(data, dict), "manifest must be an object")
    _require(type(data.get("schema_version")) is int and
             data["schema_version"] == 1, "schema_version must be 1")
    command_rows = data.get("commands")
    consumer_rows = data.get("consumers")
    _require(isinstance(command_rows, list) and command_rows,
             "commands must be a non-empty array")
    _require(isinstance(consumer_rows, dict) and consumer_rows,
             "consumers must be a non-empty object")

    commands: set[str] = set()
    for command in command_rows:
        _require(isinstance(command, str) and _CANONICAL.fullmatch(command) is not None,
                 f"invalid canonical command {command!r}")
        _require(command not in commands, f"duplicate canonical command {command!r}")
        commands.add(command)

    consumers: dict[str, Consumer] = {}
    for consumer_name, spec in consumer_rows.items():
        _require(isinstance(consumer_name, str) and _TOKEN.fullmatch(consumer_name) is not None,
                 f"invalid consumer name {consumer_name!r}")
        _require(isinstance(spec, dict), f"consumer {consumer_name!r} must be an object")
        alias_rows = spec.get("aliases")
        exposed_rows = spec.get("help")
        _require(isinstance(alias_rows, list),
                 f"consumer {consumer_name!r} aliases must be an array")
        _require(isinstance(exposed_rows, list),
                 f"consumer {consumer_name!r} help must be an array")

        aliases: dict[str, Invocation] = {}
        for alias_row in alias_rows:
            _require(isinstance(alias_row, dict), "each alias must be an object")
            alias = alias_row.get("name")
            command = alias_row.get("command")
            arguments = alias_row.get("arguments", {})
            _require(isinstance(alias, str) and _TOKEN.fullmatch(alias) is not None,
                     f"invalid short alias {alias!r}")
            _require(not alias.startswith("familia-"),
                     f"short alias {alias!r} uses the reserved familia- prefix")
            _require(alias not in commands,
                     f"short alias {alias!r} collides with a canonical command")
            _require(alias not in aliases,
                     f"duplicate alias {alias!r} for consumer {consumer_name!r}")
            _require(isinstance(command, str) and command in commands,
                     f"alias {alias!r} targets unknown canonical command {command!r}")
            _require(isinstance(arguments, dict),
                     f"alias {alias!r} arguments must be an object")
            aliases[alias] = Invocation(command=command, arguments=dict(arguments))

        _require(all(isinstance(name, str) for name in exposed_rows),
                 f"consumer {consumer_name!r} help names must be strings")
        _require(len(set(exposed_rows)) == len(exposed_rows),
                 f"consumer {consumer_name!r} help names must be unique")
        for name in exposed_rows:
            _require(name in commands or name in aliases,
                     f"help name {name!r} is not registered for consumer {consumer_name!r}")
        consumers[consumer_name] = Consumer(
            aliases=aliases,
            exposed=tuple(exposed_rows),
        )

    return Manifest(commands=frozenset(commands), consumers=consumers)


def load_manifest(path: str | Path) -> Manifest:
    """Read and validate a UTF-8 JSON manifest."""
    with Path(path).open("r", encoding="utf-8") as stream:
        return parse_manifest(json.load(stream))


def resolve(manifest: Manifest, consumer: str, name: str) -> Invocation:
    """Resolve a canonical name or consumer alias, accepting `/name` syntax."""
    _require(isinstance(consumer, str), "consumer name must be a string")
    _require(isinstance(name, str), "slash command must be a string")
    if name.startswith("/"):
        name = name[1:]
    _require(bool(name) and "/" not in name and not any(ch.isspace() for ch in name),
             f"invalid slash command {name!r}")
    _require(consumer in manifest.consumers,
             f"unknown consumer {consumer!r}")
    if name in manifest.commands:
        return Invocation(command=name, arguments={})
    aliases = manifest.consumers[consumer].aliases
    if name in aliases:
        return aliases[name]
    raise ManifestError(f"unknown slash command {name!r}")


def exposed_tokens(manifest: Manifest, consumer: str) -> tuple[str, ...]:
    """Return only the ordered slash names exposed to a consumer's users."""
    _require(consumer in manifest.consumers,
             f"unknown consumer {consumer!r}")
    return tuple("/" + name for name in manifest.consumers[consumer].exposed)
