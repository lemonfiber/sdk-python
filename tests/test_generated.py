# Copyright (c) 2026 NightWorksIO
"""The generated shapes say what the vendored artefact says, and nothing of their own."""

from typing import Any, cast

import lemonfiber
from lemonfiber import _generated as generated
from lemonfiber import contract
from scripts.contract_generator import ROOT
from scripts.contract_generator.vendored import read_artefact

ARTEFACT = cast("dict[str, Any]", read_artefact(ROOT)[0])
"""The vendored contract, in whichever layout `contract/` holds it, as decoded JSON."""


def test_every_kind_the_artefact_describes_is_a_kind_here() -> None:
    assert set(ARTEFACT["kinds"]) == set(lemonfiber.KINDS)


def test_the_wire_version_is_the_artefacts() -> None:
    assert ARTEFACT["api_version"] == generated.CONTRACT_API_VERSION


def test_every_listed_refusal_says_what_the_artefact_says() -> None:
    assert set(ARTEFACT["refusals"]) == set(lemonfiber.REFUSAL_CODES)
    for code, listed in ARTEFACT["refusals"].items():
        assert lemonfiber.REFUSAL_CODES[code] == lemonfiber.ListedRefusal(
            listed["name"],
            listed["status"],
            listed["description"],
        )


def test_a_code_is_listed_only_where_the_artefact_lists_it() -> None:
    assert lemonfiber.is_refusal_code("ADMIT-4")
    assert not lemonfiber.is_refusal_code("ADMIT-0")


def test_every_action_a_key_may_call_says_what_the_artefact_says() -> None:
    listed = ARTEFACT["key_callable"]
    assert list(lemonfiber.KEY_CALLABLE) == [entry["action"] for entry in listed]
    for entry in listed:
        assert lemonfiber.KEY_CALLABLE[entry["action"]] == lemonfiber.KeyCallable(
            disturbs=entry["disturbs"],
            rehearsal=entry["rehearsal"],
            idempotent=entry["idempotent"],
        )


def test_an_action_is_key_callable_only_where_the_artefact_lists_it() -> None:
    assert lemonfiber.is_key_callable("restart")
    assert not lemonfiber.is_key_callable("uninstall")


def test_the_contract_module_hands_on_every_generated_shape() -> None:
    for name in generated.__all__:
        assert getattr(contract, name) is getattr(generated, name)
    assert "StatusEnvelope" in generated.__all__
