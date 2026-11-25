# Copyright (c) 2026 NightWorksIO
"""A definition with fields beside a union carries them in every branch, and every branch."""

import typing

import pytest

from lemonfiber._generated.kinds import copying, plugin_provenance
from tests.generating import keys

if typing.TYPE_CHECKING:
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
