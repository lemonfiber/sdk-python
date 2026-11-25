# Copyright (c) 2026 NightWorksIO
"""A definition with fields beside a union carries them in every branch, and every branch."""

import typing

import pytest

from lemonfiber._generated.kinds import copying, plugin_provenance
from tests.generating import CODE, artefact, generated, keys, kind, refusal, source

if typing.TYPE_CHECKING:
    import pathlib
    import types


@pytest.mark.parametrize(
    ("module", "union", "beside", "branches"),
    [
        (
            copying,
            "RunningCopy",
            {"what", "scope", "part", "started", "written", "whole"},
            {
                "RunningCopyWorking": {"state"},
                "RunningCopyPaced": {"state", "limit"},
                "RunningCopyStalled": {"state", "wrote"},
            },
        ),
        (
            plugin_provenance,
            "Vouch",
            {"digest", "image", "service"},
            {
                "VouchSigned": {"provenance", "by"},
                "VouchUnproven": {"provenance", "why"},
                "VouchRefused": {"provenance", "why"},
            },
        ),
        (
            plugin_provenance,
            "Based",
            {"image", "release"},
            {
                "BasedRecorded": {"basis", "digests"},
                "BasedUnproven": {"basis", "why"},
                "BasedRefused": {"basis", "why"},
            },
        ),
    ],
)
def test_each_branch_carries_the_fields_beside_it_and_its_own(
    module: types.ModuleType,
    union: str,
    beside: set[str],
    branches: dict[str, set[str]],
) -> None:
    alias = typing.cast("typing.TypeAliasType", getattr(module, union))
    assert {branch.__name__ for branch in typing.get_args(alias.__value__)} == set(branches)
    for branch, own in branches.items():
        required, _ = keys(module, branch)
        assert beside | own <= required, branch


def test_the_fields_beside_a_union_join_every_branch_of_it(tmp_path: pathlib.Path) -> None:
    running = {
        "type": "object",
        "properties": {"part": {"type": "string"}, "job": {"type": "string"}},
        "required": ["part"],
        "oneOf": [
            {"type": "object", "properties": {"state": {"const": "working"}}, "required": ["state"]},
            {
                "type": "object",
                "properties": {"state": {"const": "paced"}, "limit": {"type": "integer"}},
                "required": ["state", "limit"],
            },
        ],
    }
    module = generated(
        tmp_path,
        artefact({"copying": kind({"$ref": "#/$defs/Running"}, {"Running": running})}),
    )
    assert keys(module, "RunningWorking") == ({"part", "state"}, {"job"})
    assert keys(module, "RunningPaced") == ({"part", "state", "limit"}, {"job"})
    assert "type Running = RunningWorking | RunningPaced" in source(tmp_path, "kinds", "copying.py")


@pytest.mark.parametrize(
    ("branch", "said"),
    [
        ({"$ref": "#/$defs/Code"}, "oneOf/0 is a branch the fields beside it cannot join"),
        ("working", "oneOf/0 is a branch the fields beside it cannot join"),
    ],
)
def test_fields_beside_a_branch_they_cannot_join_are_refused(branch: object, said: str) -> None:
    beside = {"type": "object", "properties": {"part": {"type": "string"}}, "oneOf": [branch]}
    assert said in refusal(
        artefact({"copying": kind({"$ref": "#/$defs/Running"}, {"Running": beside, "Code": CODE})}),
    )
