# Copyright (c) 2026 NightWorksIO
"""One generated module: where it sits, what it imports, what it declares and what it hands on."""

import json
import pathlib
from dataclasses import dataclass, field

from scripts.contract_generator.spelling import docstring

COPYRIGHT = "# Copyright (c) 2026 NightWorksIO"

PROVENANCE = (
    "Generated from `contract/web-api.contract.json`. Do not edit: `just generate` rewrites it,\n"
    "and CI fails on any difference."
)
"""What every generated module says of itself beneath what it holds."""

OUT = pathlib.Path("src/lemonfiber/_generated")
"""Where the generated package is written, relative to the repository."""


@dataclass
class Module:
    """One generated module, by its path beneath the generated package."""

    path: tuple[str, ...]
    """Its dotted path beneath `lemonfiber._generated`: `("kinds", "status")`."""
    summary: str
    """What it holds, in one sentence."""
    body: list[str]
    names: list[str]
    """Every name it hands on, as its `__all__`."""
    imports: dict[tuple[str, ...], set[str]] = field(default_factory=dict[tuple[str, ...], set[str]])
    """Each generated module it takes names from, to those names."""
    standard: tuple[str, ...] = ("typing",)
    """The standard modules it imports whole."""
    package: bool = False
    """Whether it is a package's `__init__`, gathering the modules beneath it."""

    @property
    def file(self) -> pathlib.Path:
        """Return where it is written, relative to the repository."""
        if self.package:
            return OUT.joinpath(*self.path, "__init__.py")
        return OUT.joinpath(*self.path[:-1], f"{self.path[-1]}.py")

    def relative(self, target: tuple[str, ...]) -> str:
        """Return how this module spells a generated module or package in a relative import."""
        here = self.path if self.package else self.path[:-1]
        common = 0
        while common < min(len(here), len(target)) and here[common] == target[common]:
            common += 1
        return "." * (len(here) - common + 1) + ".".join(target[common:])

    def source(self) -> str:
        """Return the module as written, before the formatter reads it."""
        lines = [COPYRIGHT, *docstring(f"{self.summary}\n\n{PROVENANCE}", ""), ""]
        lines.extend(f"import {one}" for one in self.standard)
        if self.imports:
            lines.append("")
        lines.extend(
            f"from {self.relative(target)} import {', '.join(sorted(self.imports[target]))}"
            for target in sorted(self.imports)
        )
        lines.extend(self.body)
        if self.names:
            lines.extend(
                ["", "", "__all__ = [", *(f"    {json.dumps(name)}," for name in sorted(self.names)), "]"],
            )
        return "\n".join(lines) + "\n"


def index(path: tuple[str, ...], summary: str, members: list[tuple[str, ...]]) -> Module:
    """Return a package's `__init__`, handing on every name each of its members hands on.

    Each member is imported once whole, under a private name, so its `__all__`
    extends the package's, and once for its names, so a type checker sees them
    handed on.
    """
    module = Module(path, summary, [], [], standard=(), package=True)
    aliases = {member: "_" + "_".join(member[len(path) :]) for member in members}
    lines = [
        "",
        *(
            f"from {module.relative(member[:-1])} import {member[-1]} as {aliases[member]}"
            for member in members
        ),
        "",
    ]
    lines.extend(f"from {module.relative(member)} import *" for member in members)
    lines.extend(["", "__all__: list[str] = []"])
    lines.extend(f"__all__ += {aliases[member]}.__all__" for member in members)
    module.body = lines
    return module
