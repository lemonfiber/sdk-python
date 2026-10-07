# Copyright (c) 2026 NightWorksIO
"""Artefacts written as the core writes them, and the generated package imported from wherever it was written."""

import importlib.util
import json
import sys
from typing import TYPE_CHECKING

import pytest

from scripts.contract_generator import OUT, ArtefactRefusedError, generate, run

if TYPE_CHECKING:
    import pathlib
    import types

ENVELOPE_DESCRIPTION = "The wrapper every machine-readable payload arrives in."

CODE = {"description": "A stable identifier.\n\nNever recycled.", "type": "string"}


def kind(data: object, definitions: dict[str, object] | None = None) -> dict[str, object]:
    """Return one kind's envelope schema, as the core writes one."""
    schema: dict[str, object] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Envelope",
        "description": ENVELOPE_DESCRIPTION,
        "type": "object",
        "properties": {
            "api_version": {"type": "integer", "format": "uint32", "minimum": 0},
            "data": data,
            "host": {"type": ["string", "null"]},
            "kind": {"type": "string"},
        },
        "required": ["api_version", "kind", "data"],
    }
    if definitions is not None:
        schema["$defs"] = definitions
    return schema


def artefact(
    kinds: dict[str, object],
    refusals: object = None,
    version: object = 1,
    key_callable: object = None,
    reads: object = None,
) -> dict[str, object]:
    """Return a whole artefact describing these kinds."""
    whole: dict[str, object] = {"api_version": version, "kinds": kinds}
    if refusals is not None:
        whole["refusals"] = refusals
    if key_callable is not None:
        whole["key_callable"] = key_callable
    if reads is not None:
        whole["reads"] = reads
    return whole


def write(root: pathlib.Path, whole: object, stamp: str | None = "v1.0.0") -> None:
    """Vendor an artefact under `root` as `contract/` holds one."""
    (root / "contract").mkdir(parents=True, exist_ok=True)
    (root / "contract" / "web-api.contract.json").write_text(json.dumps(whole), encoding="utf-8")
    if stamp is not None:
        (root / "contract" / "VERSION").write_text(f"{stamp}\n", encoding="utf-8")


def load(root: pathlib.Path) -> types.ModuleType:
    """Import the package generated under `root`, under a name of its own."""
    name = f"generated_{abs(hash(root))}"
    spec = importlib.util.spec_from_file_location(
        name,
        root / OUT / "__init__.py",
        submodule_search_locations=[str(root / OUT)],
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def generated(tmp_path: pathlib.Path, whole: object, cap: int | None = None) -> types.ModuleType:
    """Generate from an artefact and import what was written."""
    write(tmp_path, whole)
    assert run(tmp_path, cap=cap) == 0
    return load(tmp_path)


def refusal(whole: dict[str, object], cap: int | None = None) -> str:
    """Return the sentence generation refuses an artefact with."""
    with pytest.raises(ArtefactRefusedError) as refused:
        generate(whole, "v1.0.0", cap=cap)
    return str(refused.value)


def keys(module: types.ModuleType, name: str) -> tuple[set[str], set[str]]:
    """Return a generated TypedDict's required and optional keys."""
    shape = getattr(module, name)
    return set(shape.__required_keys__), set(shape.__optional_keys__)


def source(root: pathlib.Path, *path: str) -> str:
    """Return the source of the generated module at `path`, beneath the generated package under `root`."""
    return (root / OUT).joinpath(*path).read_text(encoding="utf-8")
