# Copyright (c) 2026 NightWorksIO
"""What the formatter makes of a generated module, and how many lines a module may hold."""

import pathlib
import subprocess
import sysconfig
import tempfile
import tomllib
from typing import TYPE_CHECKING

from scripts.contract_generator.refused import refuse

if TYPE_CHECKING:
    from collections.abc import Mapping

RUFF = pathlib.Path(sysconfig.get_path("scripts")) / "ruff"
"""The formatter the lockfile pins, installed beside the interpreter running the generator."""


def line_cap(root: pathlib.Path) -> int:
    """Return how many lines a source file may hold, as `pyproject.toml` declares it."""
    declared: object = (
        tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        .get("tool", {})
        .get("lemonfiber", {})
        .get("line-cap", {})
        .get("source")
    )
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        refuse(
            f"pyproject.toml declares the source line cap as {declared!r}, and it is a whole number of lines",
        )
    return declared


def lines_in(source: str) -> int:
    """Return how many lines a source holds."""
    return len(source.splitlines())


class Formatter:
    """Hands each module to the formatter as the repository's configuration has it, remembering what it said."""

    def __init__(self, config: pathlib.Path) -> None:
        """Format with the configuration at `config`."""
        self._config = config
        self._seen: dict[str, str] = {}

    def formatted(self, sources: Mapping[str, str]) -> dict[str, str]:
        """Return each source as the formatter writes it, asking it once for everything it has not yet seen."""
        unseen = sorted({source for source in sources.values() if source not in self._seen})
        if unseen:
            with tempfile.TemporaryDirectory() as scratch:
                files = [pathlib.Path(scratch) / f"m{at}.py" for at in range(len(unseen))]
                for file, source in zip(files, unseen, strict=True):
                    file.write_text(source, encoding="utf-8")
                subprocess.run(
                    [str(RUFF), "format", "--quiet", "--config", str(self._config), *map(str, files)],
                    check=True,
                )
                for file, source in zip(files, unseen, strict=True):
                    self._seen[source] = file.read_text(encoding="utf-8")
        return {key: self._seen[source] for key, source in sources.items()}
