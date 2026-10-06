# Copyright (c) 2026 NightWorksIO
"""How many lines a file may hold, as `pyproject.toml` declares it, and how a file's lines are counted.

A source file, generated ones included, is held to `source`; a test file to
`tests`, since it carries fixtures and every case of one thing.
"""

import tomllib
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pathlib

type Held = Literal["source", "tests"]
"""Which files a cap holds."""


class LineCapError(ValueError):
    """`pyproject.toml` declares no cap a file can be held to."""


def line_cap(root: pathlib.Path, held: Held) -> int:
    """Return how many lines the files `held` names may hold, as `root`'s `pyproject.toml` declares it."""
    declared: object = (
        tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        .get("tool", {})
        .get("lemonfiber", {})
        .get("line-cap", {})
        .get(held)
    )
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        message = (
            f"pyproject.toml declares the {held} line cap as {declared!r}, and it is a whole number of lines"
        )
        raise LineCapError(message)
    return declared


def lines_in(text: str) -> int:
    """Return how many lines a file's text holds."""
    return len(text.splitlines())
