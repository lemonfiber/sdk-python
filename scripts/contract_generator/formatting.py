# Copyright (c) 2026 NightWorksIO
"""What the formatter makes of a generated module."""

import pathlib
import subprocess
import sysconfig
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

RUFF = pathlib.Path(sysconfig.get_path("scripts")) / "ruff"
"""The formatter the lockfile pins, installed beside the interpreter running the generator."""


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
