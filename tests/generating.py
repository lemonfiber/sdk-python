# Copyright (c) 2026 NightWorksIO
"""Artefacts written as the core writes them, in either layout, and the generated package imported from wherever it was written."""

import importlib.util
import json
import sys
import typing
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


LISTED = {"key_callable": "key-callable.json", "reads": "reads.json", "refusals": "refusals.json"}
"""Each list the directory's index names, and the file the core writes it to."""


def relinked(node: object, prefix: str) -> object:
    """Return a schema with each `#/$defs/<Name>` reference spelled as the path `<prefix><Name>.json`."""
    if isinstance(node, list):
        return [relinked(item, prefix) for item in typing.cast("list[object]", node)]
    if not isinstance(node, dict):
        return node
    named = typing.cast("dict[str, object]", node)
    return {
        key: f"{prefix}{str(value).removeprefix('#/$defs/')}.json"
        if key == "$ref"
        else relinked(value, prefix)
        for key, value in named.items()
    }


def exploded(whole: dict[str, object]) -> dict[str, object]:
    """Return the files the directory layout holds for an artefact, by their path beneath `contract/web-api/`."""
    files: dict[str, object] = {}
    kinds: dict[str, str] = {}
    index: dict[str, object] = {"api_version": whole["api_version"], "kinds": kinds}
    for listed, file in LISTED.items():
        if listed in whole:
            index[listed] = file
            files[file] = whole[listed]
    for name, schema in typing.cast("dict[str, dict[str, object]]", whole["kinds"]).items():
        envelope = {key: value for key, value in schema.items() if key != "$defs"}
        kinds[name] = f"kinds/{name}.json"
        files[kinds[name]] = relinked(envelope, "../defs/")
        definitions = typing.cast("dict[str, dict[str, object]]", schema.get("$defs", {}))
        for defined, definition in definitions.items():
            spelled = typing.cast("dict[str, object]", relinked(definition, ""))
            files[f"defs/{defined}.json"] = {"$schema": schema.get("$schema"), **spelled}
    files["index.json"] = index
    return files


def write_directory(root: pathlib.Path, whole: dict[str, object], stamp: str = "v1.0.0") -> None:
    """Vendor an artefact under `root` as the directory layout holds one."""
    for file, held in exploded(whole).items():
        path = root / "contract" / "web-api" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(held, indent=2), encoding="utf-8")
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
