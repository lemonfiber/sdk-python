# Copyright (c) 2026 NightWorksIO
"""Write `src/lemonfiber/_generated/` from the vendored contract artefact.

Offline and deterministic: the same artefact in gives the same files out, so CI
regenerates and fails on any difference. Generation reads the vendored contract,
the directory `contract/web-api/` or the single file
`contract/web-api.contract.json`, and `contract/VERSION`, and nothing else, and
writes nothing when it refuses the artefact. Every module is written as the
formatter writes it, and none holds more lines than `pyproject.toml` allows a
source file: a module that would is written as a package of parts.
"""

import pathlib
import shutil
import sys
from typing import TYPE_CHECKING

from scripts.contract_generator.artefact import (
    as_map,
    checked,
    key_callable_of,
    kinds_of,
    reads_of,
    refusals_of,
    users_of,
)
from scripts.contract_generator.formatting import Formatter
from scripts.contract_generator.layout import Layout
from scripts.contract_generator.modules import OUT, Module, index
from scripts.contract_generator.refused import ArtefactRefusedError, refuse
from scripts.contract_generator.spelling import pascal
from scripts.contract_generator.tables import (
    KINDS_PACKAGE,
    SHARED_PACKAGE,
    envelope_module,
    key_callable_module,
    narrowing_module,
    reads_module,
    refusals_module,
)
from scripts.contract_generator.vendored import read_artefact
from scripts.contract_generator.writer import Writer
from scripts.contract_sync import ROOT
from scripts.line_cap import LineCapError, line_cap, lines_in

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["OUT", "ROOT", "ArtefactRefusedError", "generate", "run"]


def generate(
    artefact: Mapping[str, object],
    stamp: str,
    *,
    cap: int | None = None,
) -> dict[pathlib.Path, str]:
    """Return every generated file's path and source, or raise the refusal.

    `cap` is the most lines a module may hold, `pyproject.toml`'s where none is given.
    """
    try:
        limit = line_cap(ROOT, "source") if cap is None else cap
    except LineCapError as undeclared:
        refuse(str(undeclared))
    checked(artefact, stamp)
    kinds = kinds_of(artefact)
    refusals = refusals_of(artefact)
    callable_by_key = key_callable_of(artefact)
    reads = reads_of(artefact)

    writer = Writer(users=users_of(kinds))
    names = sorted(kinds)
    for kind in names:
        writer.owned[f"{pascal(kind)}Envelope"] = f"the envelope carrying `{kind}`"
    for kind in names:
        writer.kind = kind
        writer.definitions = as_map(kinds[kind].get("$defs", {}))
        for name in sorted(writer.definitions):
            writer.definition(name)
        writer.envelope(kinds[kind])

    formatter = Formatter(ROOT / "ruff.toml")
    layout = Layout(writer.shapes, formatter, limit)
    modules = layout.modules()
    kind_paths = sorted(path for path in layout.groups if path[: len(KINDS_PACKAGE)] == KINDS_PACKAGE)
    shared_paths = sorted(path for path in layout.groups if path[: len(SHARED_PACKAGE)] == SHARED_PACKAGE)
    modules.extend(
        [
            envelope_module(names),
            narrowing_module(names),
            refusals_module(refusals),
            key_callable_module(callable_by_key),
            reads_module(reads),
            index(KINDS_PACKAGE, "Every kind's envelope, and the shapes only that kind carries.", kind_paths),
        ],
    )
    members = [("envelope",), ("key_callable",), KINDS_PACKAGE, ("narrowing",), ("reads",), ("refusals",)]
    if shared_paths:
        modules.append(index(SHARED_PACKAGE, "Every shape more than one kind carries.", shared_paths))
        members.append(SHARED_PACKAGE)
    summary = f"The lemonfiber contract's shapes, generated from the artefact at {stamp}."
    modules.append(index((), summary, sorted(members)))
    return fitted(modules, formatter, limit)


def fitted(modules: list[Module], formatter: Formatter, cap: int) -> dict[pathlib.Path, str]:
    """Return every module as the formatter writes it, refusing one that holds more lines than `cap`."""
    written = formatter.formatted({str(module.file): module.source() for module in modules})
    for file, source in sorted(written.items()):
        if lines_in(source) > cap:
            refuse(f"{file} would hold {lines_in(source)} lines, over the {cap} a module may hold")
    return {pathlib.Path(file): source for file, source in written.items()}


def run(root: pathlib.Path, *, cap: int | None = None) -> int:
    """Generate into `root`, replacing what was generated before and writing nothing when the artefact is refused."""
    try:
        artefact, stamp = read_artefact(root)
        files = generate(artefact, stamp, cap=cap)
    except ArtefactRefusedError as refused:
        sys.stderr.write(f"contract_generate: refused, and nothing was written: {refused}\n")
        return 1
    shutil.rmtree(root / OUT, ignore_errors=True)
    for path, source in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    sys.stdout.write(f"generated {len(kinds_of(artefact))} kinds from {stamp} into {OUT}\n")
    return 0
