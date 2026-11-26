# Copyright (c) 2026 NightWorksIO
"""Generating the request each action is posted with, from what the contract says of its arguments."""

import json
import typing

import pytest

from scripts.contract_generator import run
from scripts.contract_sync import DIRECTORY
from tests.generating import artefact, generated, kind, load, refusal, source, write, write_directory

if typing.TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping

PULL: typing.Final[dict[str, object]] = {"pull": kind({"type": "string"})}

NULLABLE: typing.Final[dict[str, object]] = {"type": ["string", "null"], "default": None}

MOMENT: typing.Final[dict[str, object]] = {"description": "A moment, in seconds.", "type": "integer"}

HANDED_BACK: typing.Final = "p-1"
"""What an argument Python reserves the name of holds."""

AT: typing.Final[dict[str, object]] = {
    "anyOf": [{"$ref": "#/$defs/Moment"}, {"type": "null"}],
    "default": None,
}


def argument(name: str, schema: Mapping[str, object]) -> dict[str, object]:
    """Return one argument as the core lists it."""
    return {"name": name, "type": schema}


def action(
    name: str,
    arguments: list[dict[str, object]],
    consent: list[str],
    *,
    rehearsal: bool = True,
    definitions: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return one action as the core describes it, carrying the definitions its arguments reach."""
    described: dict[str, object] = {
        "action": name,
        "arguments": arguments,
        "consent": consent,
        "rehearsal": rehearsal,
    }
    if definitions is not None:
        described["$defs"] = definitions
    return described


ACTIONS: typing.Final[dict[str, object]] = {
    "restart": action(
        "restart",
        [
            argument(
                "forms",
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "The forms to act on.",
                },
            ),
            argument("offer", NULLABLE),
        ],
        ["offer"],
    ),
    "diagnose": action(
        "diagnose",
        [argument("disruptive", {"type": "boolean"}), argument("pass", NULLABLE)],
        [],
        rehearsal=False,
    ),
    "repair": action(
        "repair",
        [argument("offer", NULLABLE), argument("agreed", NULLABLE)],
        ["offer", "agreed"],
    ),
}


def with_actions(actions: object, kinds: Mapping[str, object] = PULL) -> dict[str, object]:
    """Return an artefact describing these actions beside these kinds."""
    return {**artefact(dict(kinds)), "actions": actions}


def test_each_action_is_generated_as_the_request_it_is_posted_with(tmp_path: pathlib.Path) -> None:
    module = generated(tmp_path, with_actions(ACTIONS))
    assert issubclass(module.RestartAction, module.ActionRequest)
    assert module.RestartAction.ACTION == "restart"
    assert module.RestartAction().arguments() == {"forms": [], "offer": None, "dry_run": False}
    assert module.RestartAction(forms=["tv"], dry_run=True).arguments()["forms"] == ["tv"]
    assert module.DiagnoseAction(disruptive=True, pass_=HANDED_BACK).arguments() == {
        "disruptive": True,
        "pass": HANDED_BACK,
    }
    with pytest.raises(TypeError, match="disruptive"):
        module.DiagnoseAction()
    assert "`offer` carries the operator's yes." in module.RestartAction.__doc__
    assert "`agreed` and `offer` carry the operator's yes." in module.RepairAction.__doc__
    assert "yes" not in module.DiagnoseAction.__doc__
    written = source(tmp_path, "bodies", "actions_restart.py")
    assert '    """The forms to act on."""' in written
    assert "The action posted to `/api/actions/restart`" in written


def test_a_default_is_the_value_the_contract_writes_and_no_two_requests_share_one(
    tmp_path: pathlib.Path,
) -> None:
    listed = {"type": "array", "items": {"type": "string"}}
    mapped = {
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": ["integer", "null"]}},
    }
    defaults = [
        argument("count", {"type": "integer", "default": 3}),
        argument("ratio", {"type": "number", "default": 1.5}),
        argument("word", {"type": "string", "default": 'a "word"'}),
        argument("on", {"type": "boolean", "default": True}),
        argument("forms", {**listed, "default": ["tv"]}),
        argument("empty", {**mapped, "default": {}}),
        argument("held", {**mapped, "default": {"k": [1, None]}}),
    ]
    module = generated(tmp_path, with_actions({"tune": action("tune", defaults, [], rehearsal=False)}))
    one, other = module.TuneAction(), module.TuneAction()
    assert one.arguments() == {
        "count": 3,
        "ratio": 1.5,
        "word": 'a "word"',
        "on": True,
        "forms": ["tv"],
        "empty": {},
        "held": {"k": [1, None]},
    }
    assert one.forms is not other.forms
    assert one.empty is not other.empty
    assert one.held["k"] is not other.held["k"]


def test_a_definition_only_an_action_reaches_is_written_with_its_request_from_either_layout(
    tmp_path: pathlib.Path,
) -> None:
    whole = with_actions({"undo": action("undo", [argument("at", AT)], [], definitions={"Moment": MOMENT})})
    single, split = tmp_path / "single", tmp_path / "split"
    write(single, whole)
    write_directory(split, whole)
    assert run(single) == 0
    assert run(split) == 0
    written = source(split, "bodies", "actions_undo.py")
    assert written == source(single, "bodies", "actions_undo.py")
    assert "type Moment = int" in written
    assert "    at: Moment | None = None" in written
    assert load(split).UndoAction(at=5).arguments() == {"at": 5, "dry_run": False}


def test_a_definition_a_kind_and_an_action_both_reach_is_written_once_where_both_import_it(
    tmp_path: pathlib.Path,
) -> None:
    kinds = {"pull": kind({"$ref": "#/$defs/Moment"}, {"Moment": MOMENT})}
    undo = action("undo", [argument("at", AT)], [], definitions={"Moment": MOMENT})
    generated(tmp_path, with_actions({"undo": undo}, kinds))
    assert "`/api/actions/undo` and `pull` both carry" in source(tmp_path, "shared", "moment.py")
    assert "from ..shared.moment import Moment" in source(tmp_path, "bodies", "actions_undo.py")


REFUSED: typing.Final[list[tuple[object, str]]] = [
    (
        {"restart": action("restart", [argument("dry_run", {"type": "boolean"})], [])},
        "restart: argument dry_run is the rehearsal, which `rehearsal` says",
    ),
    (
        {"restart": action("restart", [argument("arguments", NULLABLE)], [])},
        "restart: argument arguments takes the name every action request hands its arguments on with",
    ),
    (
        {"restart": {**action("restart", [], []), "$defs": []}},
        "restart: $defs [] is not an object of definitions",
    ),
    (
        {"restart": action("restart", [argument("forms", {"type": "object"})], [])},
        "the action `restart` argument `forms` is an object that says nothing of its fields",
    ),
    (
        {
            "undo": action(
                "undo",
                [argument("at", {"$ref": "#/$defs/Moment", "minimum": 0})],
                [],
                definitions={"Moment": MOMENT},
            ),
        },
        "actions/undo/arguments/0/type (minimum)",
    ),
]


@pytest.mark.parametrize(("actions", "said"), REFUSED)
def test_a_request_this_cannot_write_is_refused_naming_it(actions: object, said: str) -> None:
    assert said in refusal(with_actions(actions))


def amended(root: pathlib.Path, file: str, change: dict[str, object]) -> None:
    """Set fields of one file of the vendored directory."""
    path = root / DIRECTORY / file
    held = typing.cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps({**held, **change}), encoding="utf-8")


def test_an_action_file_holding_its_own_definitions_is_refused(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_directory(tmp_path, with_actions({"undo": action("undo", [argument("at", AT)], [])}))
    amended(tmp_path, "actions/undo.json", {"$defs": {"Moment": MOMENT}})
    assert run(tmp_path) == 1
    assert "contract/web-api/actions/undo.json holds $defs" in capsys.readouterr().err


def test_an_action_reaching_definitions_written_in_two_dialects_is_refused(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    both = {"anyOf": [{"$ref": "#/$defs/Moment"}, {"$ref": "#/$defs/Span"}], "default": 0}
    undo = action("undo", [argument("at", both)], [], definitions={"Moment": MOMENT, "Span": MOMENT})
    write_directory(tmp_path, with_actions({"undo": undo}))
    amended(tmp_path, "defs/Moment.json", {"$schema": "http://json-schema.org/draft-07/schema#"})
    assert run(tmp_path) == 1
    assert (
        'contract/web-api/defs/Moment.json is written in "http://json-schema.org/draft-07/schema#", and '
        "contract/web-api/defs/Span.json, which contract/web-api/actions/undo.json reaches too, in "
        '"https://json-schema.org/draft/2020-12/schema"'
    ) in capsys.readouterr().err
