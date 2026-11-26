# Copyright (c) 2026 NightWorksIO
"""Generating every action the web API takes, and what the contract says of each."""

import typing

import pytest

import lemonfiber
from scripts.contract_generator import run
from tests.generating import artefact, generated, kind, load, refusal, write_directory

if typing.TYPE_CHECKING:
    import pathlib

PULL: typing.Final[dict[str, object]] = {"pull": kind({"type": "string"})}

LIST: typing.Final[dict[str, object]] = {"type": "array", "items": {"type": "string"}, "default": []}


def described(
    action: object,
    names: list[str],
    consent: list[object],
    *,
    rehearsal: object = True,
) -> dict[str, object]:
    """Return one action as the core describes it: its arguments by name, those carrying the yes, and its rehearsal."""
    return {
        "action": action,
        "arguments": [{"name": name, "type": LIST} for name in names],
        "consent": consent,
        "rehearsal": rehearsal,
    }


ACTIONS: typing.Final[dict[str, dict[str, object]]] = {
    "restart": described("restart", ["forms", "services", "offer"], ["offer"]),
    "diagnose": described("diagnose", ["only", "disruptive"], [], rehearsal=False),
    "downloads-pause": described("downloads-pause", ["offer"], ["offer"]),
}


def with_actions(actions: object) -> dict[str, object]:
    """Return an artefact describing these actions beside one kind."""
    return {**artefact(PULL), "actions": actions}


def test_every_action_is_generated_by_name_with_its_arguments_consent_and_rehearsal(
    tmp_path: pathlib.Path,
) -> None:
    module = generated(tmp_path, with_actions(ACTIONS))
    assert list(module.ACTIONS) == ["diagnose", "downloads-pause", "restart"]
    assert module.ACTIONS["restart"] == module.ActionDescribed(
        arguments=("forms", "services", "offer"),
        consent=("offer",),
        rehearsal=True,
    )
    assert module.ACTIONS["diagnose"] == module.ActionDescribed(
        arguments=("only", "disruptive"),
        consent=(),
        rehearsal=False,
    )
    assert module.is_action_name("downloads-pause")
    assert not module.is_action_name("uninstall")
    assert typing.get_args(module.ActionName.__value__) == ("diagnose", "downloads-pause", "restart")
    with pytest.raises(TypeError):
        module.ACTIONS["uninstall"] = module.ActionDescribed(arguments=(), consent=(), rehearsal=False)


def test_an_artefact_older_than_the_list_of_actions_describes_none(tmp_path: pathlib.Path) -> None:
    module = generated(tmp_path, artefact(PULL))
    assert dict(module.ACTIONS) == {}
    assert module.ActionName.__value__ is typing.Never


def test_each_action_is_read_from_its_own_file_in_the_directory(tmp_path: pathlib.Path) -> None:
    write_directory(tmp_path, with_actions(ACTIONS))
    assert run(tmp_path) == 0
    module = load(tmp_path)
    assert module.ACTIONS["downloads-pause"] == module.ActionDescribed(
        arguments=("offer",),
        consent=("offer",),
        rehearsal=True,
    )


REFUSED: typing.Final[list[tuple[object, str]]] = [
    ([], "they are an object keyed by each action's name"),
    ("restart", "they are an object keyed by each action's name"),
    ({"Restart": described("Restart", [], [])}, '"Restart": not an action\'s name'),
    ({"restart": "restart"}, "restart: not an object"),
    ({"restart": described("down", [], [])}, 'restart: describes itself as "down"'),
    (
        {"restart": described("restart", [], [], rehearsal="yes")},
        'restart: rehearsal "yes" is not true or false',
    ),
    ({"restart": {**ACTIONS["restart"], "arguments": {}}}, "restart: arguments {} is not a list"),
    ({"restart": {**ACTIONS["restart"], "arguments": ["forms"]}}, "restart: argument 0 is not named"),
    ({"restart": described("restart", ["Forms"], [])}, "restart: argument 0 is not named"),
    (
        {"restart": described("restart", ["forms", "forms"], [])},
        "restart: argument forms is listed twice",
    ),
    (
        {"restart": {**ACTIONS["restart"], "arguments": [{"name": "forms"}]}},
        "restart: argument forms has no schema for its type",
    ),
    (
        {"restart": {**ACTIONS["restart"], "arguments": [{"name": "forms", "type": LIST, "why": "x"}]}},
        "restart: argument forms: carries why, which this generator does not read",
    ),
    ({"restart": {**ACTIONS["restart"], "consent": "offer"}}, 'restart: consent "offer" is not a list'),
    ({"restart": described("restart", ["forms"], ["offer"])}, 'restart: consent names "offer"'),
    ({"restart": {**ACTIONS["restart"], "moved": "LIFE-10"}}, "restart: carries moved"),
]


@pytest.mark.parametrize(("actions", "said"), REFUSED)
def test_an_action_this_cannot_write_is_refused_naming_it(actions: object, said: str) -> None:
    assert said in refusal(with_actions(actions))


def test_every_action_that_is_wrong_is_named() -> None:
    actions = {"restart": described("restart", [], [], rehearsal=1), "down": described("down", ["Wait"], [])}
    said = refusal(with_actions(actions))
    assert "down: argument 0" in said
    assert "restart: rehearsal 1" in said


def test_actions_the_directory_names_as_no_object_of_files_are_refused(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_directory(tmp_path, with_actions([]))
    assert run(tmp_path) == 1
    assert "they are an object keyed by each action's name" in capsys.readouterr().err


def test_the_package_hands_on_the_actions_the_vendored_contract_describes() -> None:
    assert lemonfiber.is_action_name("restart")
    assert not lemonfiber.is_action_name("retry-import")
    assert lemonfiber.ACTIONS["downloads-pause"].consent == ("offer",)
