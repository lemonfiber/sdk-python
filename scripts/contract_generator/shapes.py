# Copyright (c) 2026 NightWorksIO
"""One declaration the generator writes, and the order a module's declarations are written in."""

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scripts.contract_generator.spelling import docstring

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
"""A string literal inside an annotation, which names a value rather than a shape."""


@dataclass(frozen=True)
class Field:
    """One property of an object schema, as a TypedDict declares it."""

    key: str
    annotation: str
    needed: bool
    description: str | None


def class_lines(name: str, description: str | None, fields: Sequence[Field]) -> list[str]:
    """Return a TypedDict written as a class, every key of which is a Python name."""
    lines = [f"class {name}(typing.TypedDict):"]
    if description is not None:
        lines.extend([*docstring(description, "    "), ""])
    for one in fields:
        annotation = one.annotation if one.needed else f"typing.NotRequired[{one.annotation}]"
        lines.append(f"    {one.key}: {annotation}")
        if one.description is not None:
            lines.extend(docstring(one.description, "    "))
    if not fields:
        lines.append("    pass")
    return lines


def names_in(annotation: str) -> set[str]:
    """Return every name an annotation refers to, leaving out what its string literals spell."""
    return set(re.findall(r"\b[A-Za-z_]\w*\b", QUOTED.sub("", annotation)))


@dataclass
class Shape:
    """One TypedDict or alias this generator emits, where it came from, and who carries it."""

    name: str
    origin: str
    lines: list[str]
    carriers: frozenset[str]
    """The kinds whose envelopes carry it, which decides the module it is written in."""
    annotations: list[str] = field(default_factory=list[str])
    """Every annotation it is written with, which is where it names other shapes."""
    fields: list[tuple[str, str, bool]] | None = None
    """A functional TypedDict's keys, annotations and whether each is required, written out once the order is known."""
    description: str | None = None

    def refers_to(self, known: Collection[str]) -> set[str]:
        """Return every other shape of `known` this one names."""
        return {one for annotation in self.annotations for one in names_in(annotation)} & set(known) - {
            self.name,
        }

    def written(self, quoted: frozenset[str]) -> list[str]:
        """Return the declaration, quoting any annotation that names a shape in `quoted`."""
        if self.fields is None:
            return self.lines
        lines = [f"{self.name} = typing.TypedDict(", f"    {json.dumps(self.name)},", "    {"]
        for key, annotation, needed in self.fields:
            spelled = json.dumps(annotation) if names_in(annotation) & quoted else annotation
            lines.append(
                f"        {json.dumps(key)}: {spelled if needed else f'typing.NotRequired[{spelled}]'},",
            )
        lines.extend(["    },", ")"])
        if self.description is not None:
            lines.extend(docstring(self.description, ""))
        return lines


def ordered(shapes: Mapping[str, Shape]) -> list[str]:
    """Return every declaration, each functional TypedDict after what it names.

    A class body and a `type` alias are evaluated when first read, so they are
    written in name order. A functional TypedDict is evaluated where it stands,
    so each follows the functional TypedDicts it names; one caught in a cycle
    names the rest of the cycle in quotes instead.
    """
    eager = {name for name, shape in shapes.items() if shape.fields is not None}
    order = sorted(set(shapes) - eager)
    waiting = {name: shapes[name].refers_to(eager) for name in eager}
    while waiting:
        ready = sorted(name for name, needs in waiting.items() if not needs & set(waiting))
        if not ready:
            ready = [min(waiting)]
        for name in ready:
            order.append(name)
            del waiting[name]
    return order


def declarations(shapes: Mapping[str, Shape]) -> list[str]:
    """Return the source of every declaration, in the order `ordered` gives, quoting what is not yet written."""
    functional = frozenset(name for name, shape in shapes.items() if shape.fields is not None)
    source: list[str] = []
    written: set[str] = set()
    for name in ordered(shapes):
        source.extend(["", "", *shapes[name].written(functional - written)])
        written.add(name)
    return source
