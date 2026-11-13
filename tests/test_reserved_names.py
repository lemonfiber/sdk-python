# Copyright (c) 2026 NightWorksIO
"""Refusing a definition that takes a name generation writes itself."""

import ast
import copy
import pathlib
import typing

import pytest

from scripts.contract_generator import OUT, ArtefactRefusedError, generate
from scripts.contract_generator.vendored import read_artefact
from tests.generating import CODE

ROOT = pathlib.Path(__file__).resolve().parent.parent


def handed_on_beside_the_shapes() -> set[str]:
    """Return every name a committed module written from the artefact's lists hands on."""
    names: set[str] = set()
    for path in (ROOT / OUT).rglob("*.py"):
        if path.relative_to(ROOT / OUT).parts[0] in {"kinds", "shared"} or path.name == "__init__.py":
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            ):
                names.update(ast.literal_eval(node.value))
    return names


def test_a_definition_taking_a_name_a_table_hands_on_is_refused_naming_it_and_its_kind() -> None:
    handed_on = handed_on_beside_the_shapes()
    assert {"Read", "Readable", "READS", "BUNDLE"} <= handed_on
    whole, stamp = read_artefact(ROOT)
    first = min(typing.cast("dict[str, object]", whole["kinds"]))
    for name in sorted(handed_on):
        taking = copy.deepcopy(whole)
        carrier = typing.cast("dict[str, dict[str, dict[str, object]]]", taking["kinds"])[first]
        carrier.setdefault("$defs", {})[name] = CODE
        with pytest.raises(ArtefactRefusedError) as refused:
            generate(taking, stamp)
        said = str(refused.value)
        assert f"`{name}`, defined by `{first}`, takes a name this generator writes itself" in said
