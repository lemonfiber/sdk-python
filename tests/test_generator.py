# Copyright (c) 2026 NightWorksIO
"""Generating the shapes from the artefact, and refusing an artefact that cannot be read one way."""

import json
import pathlib
import typing

import pytest

from scripts import contract_generate
from scripts.contract_generator import OUT, generate, run
from scripts.contract_generator.vendored import read_artefact
from scripts.contract_sync import STAMP
from tests.generating import CODE, artefact, generated, keys, kind, refusal, source, write

PROBLEM = {
    "description": "Something that went wrong.",
    "type": "object",
    "properties": {
        "cause": {"anyOf": [{"$ref": "#/$defs/Problem"}, {"type": "null"}]},
        "code": {"description": "The stable identifier.", "$ref": "#/$defs/Code"},
        "remedies": {"type": "array", "items": {"type": "string"}},
        "severity": {
            "oneOf": [
                {"type": "string", "const": "advisory", "description": "Informational."},
                {"type": "string", "const": "error"},
            ],
        },
    },
    "required": ["code", "remedies", "severity"],
}


def test_the_vendored_artefact_generates_what_is_committed() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    whole, stamp = read_artefact(root)
    files = generate(whole, stamp)
    committed = {path.relative_to(root): path for path in (root / OUT).rglob("*.py")}
    assert set(files) == set(committed)
    for path, written in files.items():
        assert committed[path].read_text(encoding="utf-8") == written
    assert all(stamp not in written for written in files.values())


def test_an_object_is_a_typed_dict_with_its_required_and_optional_keys(tmp_path: pathlib.Path) -> None:
    module = generated(
        tmp_path,
        artefact({"error": kind({"$ref": "#/$defs/Problem"}, {"Problem": PROBLEM, "Code": CODE})}),
    )
    assert keys(module, "Problem") == ({"code", "remedies", "severity"}, {"cause"})
    assert module.Problem.__doc__ == "Something that went wrong."
    assert module.Code.__value__ is str
    assert module.Problem.__annotations__["remedies"] == list[str]
    assert module.Problem.__annotations__["severity"] == typing.Literal["advisory", "error"]


def test_each_kind_has_an_envelope_naming_it(tmp_path: pathlib.Path) -> None:
    module = generated(
        tmp_path,
        artefact({"front-door": kind({"type": "string"}), "pull": kind({"type": "string"})}),
    )
    assert keys(module, "FrontDoorEnvelope") == ({"api_version", "kind", "data"}, {"host"})
    assert module.FrontDoorEnvelope.__annotations__["kind"] == typing.Literal["front-door"]
    assert frozenset({"front-door", "pull"}) == module.KINDS
    assert typing.get_args(module.Kind.__value__) == ("front-door", "pull")
    assert module.CONTRACT_API_VERSION == 1
    assert "PullEnvelope" in module.__all__
    assert "typing" not in module.__all__


def test_a_tagged_union_names_each_variant_for_its_tag(tmp_path: pathlib.Path) -> None:
    scope = {
        "description": "How much a backup covers.",
        "oneOf": [
            {
                "description": "Everything.",
                "type": "object",
                "properties": {"scope": {"const": "whole_stack"}},
                "required": ["scope"],
            },
            {
                "type": "object",
                "properties": {"scope": {"const": "service"}, "name": {"type": "string"}},
                "required": ["scope", "name"],
            },
        ],
    }
    module = generated(tmp_path, artefact({"backup": kind({"$ref": "#/$defs/Scope"}, {"Scope": scope})}))
    assert keys(module, "ScopeWholeStack") == ({"scope"}, set())
    assert module.ScopeWholeStack.__doc__ == "Everything."
    assert keys(module, "ScopeService") == ({"scope", "name"}, set())
    written = source(tmp_path, "kinds", "backup.py")
    assert 'type Scope = ScopeWholeStack | ScopeService\n"""How much a backup covers."""' in written


def test_untagged_variants_are_named_for_their_place(tmp_path: pathlib.Path) -> None:
    either = {
        "oneOf": [
            {"type": "string", "const": "nothing"},
            {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
            {"type": "object", "properties": {"b": {"type": "number"}}},
            {"$ref": "#/$defs/Code"},
        ],
    }
    module = generated(
        tmp_path,
        artefact({"word": kind({"$ref": "#/$defs/Either"}, {"Either": either, "Code": CODE})}),
    )
    assert keys(module, "EitherVariant2") == ({"a"}, set())
    assert keys(module, "EitherVariant3") == (set(), {"b"})
    members = typing.get_args(module.Either.__value__)
    assert members[0] == typing.Literal["nothing"]
    assert members[-1] is module.Code


def test_a_tag_whose_value_names_nothing_falls_back_to_the_place(tmp_path: pathlib.Path) -> None:
    either = {
        "oneOf": [
            {"type": "object", "properties": {"t": {"const": "--"}}, "required": ["t"]},
            {"type": "object", "properties": {"t": {"const": "two"}}, "required": ["t"]},
        ],
    }
    module = generated(tmp_path, artefact({"word": kind({"$ref": "#/$defs/Either"}, {"Either": either})}))
    assert hasattr(module, "EitherVariant1")
    assert hasattr(module, "EitherTwo")


def test_keys_python_cannot_spell_are_written_in_the_functional_form(tmp_path: pathlib.Path) -> None:
    freshness = {
        "description": 'Read "as of" a moment.',
        "type": "object",
        "properties": {"as": {"const": "as_of"}, "at-time": {"type": "integer"}},
        "required": ["as"],
    }
    module = generated(
        tmp_path,
        artefact({"space": kind({"$ref": "#/$defs/Freshness"}, {"Freshness": freshness})}),
    )
    assert keys(module, "Freshness") == ({"as"}, {"at-time"})


def test_inline_objects_maps_and_nullable_shapes_are_named_after_where_they_sit(
    tmp_path: pathlib.Path,
) -> None:
    report: dict[str, object] = {
        "type": "object",
        "properties": {
            "inner": {"type": "object", "properties": {"x": {"type": "boolean"}}, "required": ["x"]},
            "maybe": {"type": ["object", "null"], "properties": {"y": {"type": "null"}}},
            "counts": {"type": "object", "additionalProperties": {"type": "integer"}},
            "rows": {"type": "array", "items": {"type": "object", "properties": {"z": {"type": "string"}}}},
            "mixed": {"anyOf": [{"type": "integer"}, {"type": "boolean"}, {"type": "string"}]},
            "pick": {"enum": ["a", 1, True]},
            "flag": {"const": False},
            "empty": {"type": "object", "properties": {}},
        },
        "required": ["inner", "counts", "rows"],
    }
    module = generated(tmp_path, artefact({"status": kind({"$ref": "#/$defs/Report"}, {"Report": report})}))
    assert keys(module, "ReportInner") == ({"x"}, set())
    assert keys(module, "ReportMaybe") == (set(), {"y"})
    assert keys(module, "ReportRowsItem") == (set(), {"z"})
    assert keys(module, "ReportEmpty") == (set(), set())
    assert module.Report.__annotations__["counts"] == dict[str, int]


def test_a_definition_two_kinds_carry_alike_is_written_once(tmp_path: pathlib.Path) -> None:
    module = generated(
        tmp_path,
        artefact(
            {
                "a": kind({"$ref": "#/$defs/Code"}, {"Code": CODE}),
                "b": kind({"$ref": "#/$defs/Code"}, {"Code": CODE}),
            },
        ),
    )
    assert module.AEnvelope.__annotations__["data"] is module.Code


def test_listed_refusals_are_generated_with_what_the_contract_says_of_each(tmp_path: pathlib.Path) -> None:
    refusals = {
        "ADMIT-4": {"name": "NOT_ADMITTED", "status": 403, "description": "Raised when nothing admits it."},
        "READ-1": {"name": "NO_SUCH", "status": 404, "description": 'Raised "here".'},
    }
    module = generated(tmp_path, artefact({"pull": kind({"type": "string"})}, refusals))
    assert module.REFUSAL_CODES["ADMIT-4"] == module.ListedRefusal(
        "NOT_ADMITTED",
        403,
        "Raised when nothing admits it.",
    )
    assert module.is_refusal_code("READ-1")
    assert not module.is_refusal_code("READ-2")
    assert typing.get_args(module.RefusalCode.__value__) == ("ADMIT-4", "READ-1")


def test_an_artefact_older_than_the_refusal_list_lists_none(tmp_path: pathlib.Path) -> None:
    module = generated(tmp_path, artefact({"pull": kind({"type": "string"})}))
    assert dict(module.REFUSAL_CODES) == {}
    assert module.RefusalCode.__value__ is typing.Never


PULL: dict[str, object] = {"pull": kind({"type": "string"})}


def callable_by_key(
    action: object,
    *,
    disturbs: object = True,
    rehearsal: object = False,
    idempotent: object = False,
    **more: object,
) -> dict[str, object]:
    """Return one action a key may call, as the contract lists it."""
    return {"action": action, "disturbs": disturbs, "rehearsal": rehearsal, "idempotent": idempotent, **more}


def test_the_actions_a_key_may_call_are_generated_in_the_contracts_order(tmp_path: pathlib.Path) -> None:
    listed = [
        callable_by_key("restart", rehearsal=True),
        callable_by_key("downloads-pause", disturbs=False, idempotent=True),
    ]
    module = generated(tmp_path, artefact(PULL, key_callable=listed))
    assert list(module.KEY_CALLABLE) == ["restart", "downloads-pause"]
    assert module.KEY_CALLABLE["restart"] == module.KeyCallable(
        disturbs=True,
        rehearsal=True,
        idempotent=False,
    )
    assert module.KEY_CALLABLE["downloads-pause"] == module.KeyCallable(
        disturbs=False,
        rehearsal=False,
        idempotent=True,
    )
    assert module.KEY_CALLABLE["restart"].moved is None
    assert module.is_key_callable("restart")
    assert not module.is_key_callable("uninstall")
    assert typing.get_args(module.KeyCallableAction.__value__) == ("restart", "downloads-pause")
    with pytest.raises(TypeError):
        module.KEY_CALLABLE["uninstall"] = module.KeyCallable(disturbs=True, rehearsal=True, idempotent=False)


MOVED: typing.Final = {
    "LIFE-10": {"name": "OFFER_MOVED", "status": 409, "description": "Raised when the offer moved."},
}


def test_the_code_an_action_refuses_a_moved_offer_with_is_generated(tmp_path: pathlib.Path) -> None:
    listed = [callable_by_key("restart", rehearsal=True, moved="LIFE-10"), callable_by_key("diagnose")]
    module = generated(tmp_path, artefact(PULL, MOVED, key_callable=listed))
    assert module.KEY_CALLABLE["restart"] == module.KeyCallable(
        disturbs=True,
        rehearsal=True,
        idempotent=False,
        moved="LIFE-10",
    )
    assert module.KEY_CALLABLE["diagnose"].moved is None


def test_an_artefact_older_than_the_key_callable_list_lets_a_key_call_nothing(tmp_path: pathlib.Path) -> None:
    module = generated(tmp_path, artefact(PULL))
    assert dict(module.KEY_CALLABLE) == {}
    assert module.KeyCallableAction.__value__ is typing.Never


@pytest.mark.parametrize(
    ("listed", "said"),
    [
        ({}, "it is a list of actions"),
        (["restart"], "entry 0: not an object"),
        ([callable_by_key("Restart")], 'entry 0: action "Restart" is not an action\'s name'),
        ([callable_by_key("restart-")], 'entry 0: action "restart-" is not an action\'s name'),
        ([callable_by_key(None)], "entry 0: action null is not an action's name"),
        ([callable_by_key("restart", disturbs=1)], "entry 0: disturbs 1 is not true or false"),
        ([callable_by_key("restart", rehearsal=None)], "entry 0: rehearsal null is not true or false"),
        ([callable_by_key("restart", idempotent="no")], 'entry 0: idempotent "no" is not true or false'),
        (
            [{**callable_by_key("restart"), "scope": "act"}],
            "entry 0: carries scope, which this generator does not read",
        ),
        ([callable_by_key("restart"), callable_by_key("restart")], "entry 1: restart is listed twice"),
        ([callable_by_key("restart", moved="moved")], 'entry 0: moved "moved" is not a code'),
        ([callable_by_key("restart", moved=10)], "entry 0: moved 10 is not a code"),
        (
            [callable_by_key("restart", moved="LIFE-11")],
            "entry 0: moved LIFE-11 is not a refusal the contract lists",
        ),
    ],
)
def test_an_action_a_key_may_call_this_generator_cannot_write_is_refused(listed: object, said: str) -> None:
    assert said in refusal(artefact(PULL, MOVED, key_callable=listed))


def served(
    path: object,
    *,
    kinds: object = None,
    parameters: object = None,
    file: object = False,
) -> dict[str, object]:
    """Return one read the web API serves, as the contract lists it: answering `pull` and taking nothing, unless told."""
    return {
        "path": path,
        "parameters": [] if parameters is None else parameters,
        "kinds": ["pull"] if kinds is None else kinds,
        "file": file,
    }


def parameter(name: object, *, repeatable: object = False) -> dict[str, object]:
    """Return one query parameter a read takes, as the contract lists it."""
    return {"name": name, "repeatable": repeatable}


READS = [
    served("/api/front-door", parameters=[parameter("form", repeatable=True), parameter("most")]),
    served("/api/logs", kinds=["pull", "start"]),
    served("/api/status"),
    served("/api/bundle/{name}", kinds=[], file=True),
    served("/api/export", kinds=[], file=True),
]

PULL_AND_START: dict[str, object] = {"pull": kind({"type": "string"}), "start": kind({"type": "string"})}


def test_the_reads_are_generated_in_the_contracts_order_with_what_each_takes(tmp_path: pathlib.Path) -> None:
    module = generated(tmp_path, artefact(PULL_AND_START, reads=READS))
    assert list(module.Read) == ["front-door", "status"]
    assert module.Read.FRONT_DOOR.path == "/api/front-door"
    assert module.READS[module.Read.FRONT_DOOR] == module.Readable(
        kinds=("pull",),
        parameters=(
            module.ReadParameter("form", repeatable=True),
            module.ReadParameter("most", repeatable=False),
        ),
    )
    assert module.READS[module.Read.STATUS] == module.Readable(kinds=("pull",), parameters=())
    with pytest.raises(TypeError):
        module.READS[module.Read.STATUS] = module.Readable(kinds=(), parameters=())


def test_a_read_answered_a_line_at_a_time_or_with_a_file_is_a_path_beside_the_reads(
    tmp_path: pathlib.Path,
) -> None:
    module = generated(tmp_path, artefact(PULL_AND_START, reads=READS))
    assert (module.API, module.LOGS, module.BUNDLE, module.EXPORT) == (
        "/api",
        "/api/logs",
        "/api/bundle",
        "/api/export",
    )
    written = source(tmp_path, "reads.py")
    assert '"""Answers with `pull`; takes `form` (more than once) and `most`."""' in written
    assert '"""Answers one envelope a line, each `pull` or `start`."""' in written
    assert '"""Answers with a file, named by `name` in the path."""' in written
    assert '"""Answers with a file."""' in written


def test_an_artefact_older_than_the_read_list_names_no_read(tmp_path: pathlib.Path) -> None:
    module = generated(tmp_path, artefact(PULL))
    assert list(module.Read) == []
    assert dict(module.READS) == {}


@pytest.mark.parametrize(
    ("listed", "said"),
    [
        ({}, "they are a list of reads"),
        (["/api/status"], "entry 0: not an object"),
        ([served("/status")], 'entry 0: path "/status" is not a read\'s path'),
        ([served("/api/Status")], 'entry 0: path "/api/Status" is not a read\'s path'),
        ([served("/api/status", kinds="pull")], 'entry 0: kinds "pull" is not a list of kinds'),
        (
            [served("/api/status", kinds=["push"])],
            "entry 0: answers with push, which the contract describes no",
        ),
        ([served("/api/status", kinds=[])], "entry 0: answers with neither a kind nor a file"),
        ([served("/api/status", file="no")], 'entry 0: file "no" is not true or false'),
        (
            [served("/api/status/{name}", parameters=[parameter("name")])],
            "entry 0: names name both as a segment of /api/status/{name} and as a query parameter",
        ),
        ([served("/api/status", parameters={})], "entry 0: parameters {} is not a list"),
        ([served("/api/status", parameters=["form"])], "entry 0: parameter 0: not an object"),
        ([served("/api/status", parameters=[parameter("Form")])], 'parameter 0: name "Form" is not a query'),
        (
            [served("/api/status", parameters=[parameter("form", repeatable=1)])],
            "parameter 0: repeatable 1 is not true",
        ),
        (
            [served("/api/status", parameters=[parameter("form"), parameter("form")])],
            "entry 0: parameter 1: form is listed twice",
        ),
        (
            [served("/api/status", parameters=[{**parameter("form"), "default": 1}])],
            "entry 0: parameter 0: carries default, which this generator does not read",
        ),
        (
            [{**served("/api/status"), "scope": "read"}],
            "entry 0: carries scope, which this generator does not read",
        ),
        ([served("/api/status"), served("/api/status")], "entry 1: /api/status is listed twice"),
    ],
)
def test_a_read_this_generator_cannot_write_is_refused(listed: object, said: str) -> None:
    assert said in refusal(artefact(PULL, reads=listed))


def test_a_read_whose_path_a_caller_fills_keeps_its_segment(tmp_path: pathlib.Path) -> None:
    listed = [served("/api/held"), served("/api/held/{id}", parameters=[parameter("member")])]
    module = generated(tmp_path, artefact(PULL, reads=listed))
    assert list(module.Read) == ["held", "held/{id}"]
    assert module.Read.HELD_ID.path == "/api/held/{id}"
    assert module.READS[module.Read.HELD_ID] == module.Readable(
        kinds=("pull",),
        parameters=(module.ReadParameter("member", repeatable=False),),
        segments=("id",),
    )
    assert module.READS[module.Read.HELD].segments == ()
    written = source(tmp_path, "reads.py")
    assert '"""Answers with `pull`, for the `id` in its path; takes `member`."""' in written


def test_two_reads_written_under_one_name_are_refused() -> None:
    listed = [served("/api/held-id"), served("/api/held/{id}")]
    assert "/api/held/{id} would be written as `HELD_ID`, which `Read` already names" in refusal(
        artefact(PULL, reads=listed),
    )


def test_a_path_beside_the_reads_taking_a_name_the_module_holds_is_refused() -> None:
    listed = [served("/api/api/{name}", kinds=[], file=True)]
    assert "/api/api/{name} would be written as `API`" in refusal(artefact(PULL, reads=listed))


@pytest.mark.parametrize("stamp", [None, "v2.0.0", "d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6"])
def test_the_revision_a_contract_came_from_changes_no_generated_file(
    tmp_path: pathlib.Path,
    stamp: str | None,
) -> None:
    contract = artefact({"pull": kind({"type": "string"})})
    write(tmp_path / "stamped", contract, stamp="v1.0.0")
    write(tmp_path / "other", contract, stamp=stamp)
    assert run(tmp_path / "stamped") == 0
    assert run(tmp_path / "other") == 0
    written = {
        path.relative_to(tmp_path / "stamped"): path for path in (tmp_path / "stamped" / OUT).rglob("*.py")
    }
    assert written
    for path, file in written.items():
        assert (tmp_path / "other" / path).read_text(encoding="utf-8") == file.read_text(encoding="utf-8")


def test_a_version_this_package_does_not_implement_is_refused_naming_both() -> None:
    said = refusal(artefact({"pull": kind({"type": "string"})}, version=2))
    assert "api_version 2" in said
    assert "implements 1" in said


@pytest.mark.parametrize("kinds", [None, {}, []])
def test_an_artefact_describing_no_kinds_is_refused(kinds: object) -> None:
    assert refusal({"api_version": 1, "kinds": kinds}) == "the vendored contract describes no kinds"


def test_a_kind_that_is_not_a_schema_is_refused() -> None:
    assert "the kind `pull` is 3" in refusal(artefact({"pull": 3}))


def test_a_constraint_beside_a_reference_is_refused_naming_where() -> None:
    beside = {
        "type": "object",
        "properties": {"v": {"$ref": "#/$defs/Code", "type": "string", "description": "ok"}},
    }
    said = refusal(artefact({"a": kind({"$ref": "#/$defs/R"}, {"R": beside, "Code": CODE})}))
    assert "/a/$defs/R/properties/v (type)" in said


def test_a_described_reference_is_ordinary_company() -> None:
    described = {
        "type": "object",
        "properties": {"v": {"$ref": "#/$defs/Code", "description": "d", "default": None}},
    }
    generate(artefact({"a": kind({"$ref": "#/$defs/R"}, {"R": described, "Code": CODE})}), "v1.0.0")


@pytest.mark.parametrize("name", ["Kind", "Envelope", "KINDS", "RefusalCode", "AEnvelope"])
def test_a_definition_taking_a_name_the_generator_writes_is_refused_naming_it_and_its_kind(name: str) -> None:
    said = refusal(artefact({"a": kind({"$ref": f"#/$defs/{name}"}, {name: CODE})}))
    assert f"`{name}`, defined by `a`, takes a name this generator writes itself" in said


def test_one_name_for_two_shapes_is_refused() -> None:
    other = {"type": "integer"}
    said = refusal(
        artefact(
            {
                "a": kind({"$ref": "#/$defs/Code"}, {"Code": CODE}),
                "b": kind({"$ref": "#/$defs/Code"}, {"Code": other}),
            },
        ),
    )
    assert "`Code` is defined by `a` and by `b` as two different shapes" in said


def test_an_inline_name_another_shape_holds_is_refused() -> None:
    report: dict[str, object] = {
        "type": "object",
        "properties": {"inner": {"type": "object", "properties": {}}},
    }
    said = refusal(artefact({"a": kind({"$ref": "#/$defs/Report"}, {"Report": report, "ReportInner": CODE})}))
    assert "would both be written as `ReportInner`" in said


def test_an_inline_name_the_generator_owns_is_refused() -> None:
    listing: dict[str, object] = {
        "type": "object",
        "properties": {"code": {"type": "object", "properties": {}}},
    }
    said = refusal(artefact({"a": kind({"$ref": "#/$defs/Refusal"}, {"Refusal": listing})}))
    assert "would be written as `RefusalCode`, which here names every code a refusal may carry" in said


@pytest.mark.parametrize(
    ("schema", "said"),
    [
        ({"not": {}}, "uses not, which this generator does not read"),
        (True, "is true, which is not a schema this generator reads"),
        ({"description": "?"}, "declares no type"),
        ({"type": "array"}, "is an array that says nothing of its items"),
        ({"type": "object"}, "is an object that says nothing of its fields"),
        ({"type": "tuple"}, "is of type 'tuple'"),
        ({"const": [1]}, "a constant of [1] has no Python literal"),
    ],
)
def test_a_shape_this_generator_cannot_read_is_refused_rather_than_guessed(schema: object, said: str) -> None:
    assert said in refusal(artefact({"a": kind(schema, {})}))


INSIDE = {"type": "object", "properties": {"v": {"$ref": "#/$defs/Missing"}}}
"""A definition whose one property refers to a definition its kind does not hold."""


@pytest.mark.parametrize(
    ("data", "definitions", "said"),
    [
        (
            {"$ref": "other.json#/x"},
            {},
            "the envelope of `a` property `data` refers to other.json#/x, outside the definitions beside it",
        ),
        (
            {"$ref": "#/$defs/Missing"},
            {"Code": CODE},
            "the envelope of `a` property `data` refers to #/$defs/Missing, which `a` does not define",
        ),
        (
            {"$ref": "#/$defs/Inside"},
            {"Inside": INSIDE},
            "`Inside`, defined by `a` property `v` refers to #/$defs/Missing, which `a` does not define",
        ),
    ],
)
def test_a_reference_to_no_definition_is_refused_naming_it_and_where_it_sits_and_nothing_is_written(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    data: object,
    definitions: dict[str, object],
    said: str,
) -> None:
    write(tmp_path, artefact({"a": kind(data, definitions)}))
    assert run(tmp_path) == 1
    assert not (tmp_path / OUT).exists()
    assert said in capsys.readouterr().err


@pytest.mark.parametrize("name", ["lower", "Not-A-Name", "None2-", "Code\n"])
def test_a_definition_python_cannot_name_is_refused(name: str) -> None:
    said = refusal(artefact({"a": kind({"$ref": f"#/$defs/{name}"}, {name: CODE})}))
    assert f"`{name}`, defined by `a`, is not a name a Python type can carry" in said


@pytest.mark.parametrize("missing", ["api_version", "kind", "data"])
def test_an_envelope_without_its_fields_is_refused(missing: str) -> None:
    schema = kind({"type": "string"})
    schema["required"] = [field for field in ["api_version", "kind", "data"] if field != missing]
    assert f"does not require `{missing}`" in refusal(artefact({"a": schema}))


def test_an_envelope_field_python_cannot_spell_is_refused() -> None:
    schema = kind({"type": "string"})
    typing.cast("dict[str, object]", schema["properties"])["from"] = {"type": "string"}
    assert "carries `from`, which an envelope field cannot be named" in refusal(artefact({"a": schema}))


@pytest.mark.parametrize(
    ("refusals", "said"),
    [
        ([], "they are an object keyed by code"),
        ({"admit-4": {"name": "X", "status": 403, "description": "d"}}, '"admit-4": not a code'),
        ({"ADMIT-4": "x"}, "ADMIT-4: not an object"),
        (
            {"ADMIT-4": {"name": "lower", "status": 403, "description": "d"}},
            'name "lower" is not SCREAMING_SNAKE',
        ),
        (
            {"ADMIT-4": {"name": "X", "status": 200, "description": "d"}},
            "status 200 is not a refusal's status",
        ),
        (
            {"ADMIT-4": {"name": "X", "status": True, "description": "d"}},
            "status true is not a refusal's status",
        ),
        ({"ADMIT-4": {"name": "X", "status": 403, "description": " "}}, 'description " " is not a sentence'),
        (
            {
                "A-1": {"name": "X", "status": 403, "description": "d"},
                "A-2": {"name": "X", "status": 403, "description": "d"},
            },
            "A-2: name X is also the name of A-1",
        ),
    ],
)
def test_a_refusal_this_generator_cannot_write_is_refused(refusals: object, said: str) -> None:
    assert said in refusal(artefact({"pull": kind({"type": "string"})}, refusals))


HOSTILE = 'x"""\nraise SystemExit("ran")\n"""'
"""Text that ends a docstring and runs a statement, were it written unescaped."""


@pytest.mark.parametrize(
    "said",
    [
        HOSTILE,
        'ends on a quote"',
        "ends on a backslash\\",
        '""""""',
        "a carriage\rreturn and a nul\x00",
        "a line separator\u2028inside",
    ],
)
def test_a_description_reads_back_as_written_and_runs_nothing(tmp_path: pathlib.Path, said: str) -> None:
    shape = {
        "description": said,
        "type": "object",
        "properties": {"inside": {"type": "string", "description": said}},
    }
    keyed = {"description": said, "type": "object", "properties": {"from": {"type": "string"}}}
    alias = {"description": said, "type": "string"}
    definitions: dict[str, object] = {"Shape": shape, "Keyed": keyed, "Alias": alias}
    data = {
        "type": "object",
        "properties": {
            "a": {"$ref": "#/$defs/Shape"},
            "b": {"$ref": "#/$defs/Keyed"},
            "c": {"$ref": "#/$defs/Alias"},
        },
    }
    module = generated(tmp_path, artefact({"pull": kind(data, definitions)}))
    assert (module.Shape.__doc__ or "").rstrip("\n") == said


@pytest.mark.parametrize("name", ["Pull", "1pull", "", "pull door", "pull.door", "pull\n", HOSTILE])
def test_a_kind_python_cannot_carry_is_refused(name: str) -> None:
    said = refusal(artefact({name: kind({"type": "string"})}))
    assert f"the kind {json.dumps(name)} is not lowercase letters, digits, hyphens and underscores" in said


def test_two_kinds_written_under_one_name_are_refused() -> None:
    said = refusal(artefact({"front-door": kind({"type": "string"}), "front_door": kind({"type": "string"})}))
    assert said == "the kinds `front-door` and `front_door` would both be written as `FrontDoorEnvelope`"


@pytest.mark.parametrize("stamp", [HOSTILE, "main", "abc123", "v1.0.0\nraise SystemExit"])
def test_a_stamp_that_is_not_a_revision_is_refused(
    tmp_path: pathlib.Path,
    stamp: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write(tmp_path, artefact({"pull": kind({"type": "string"})}), stamp=stamp)
    assert run(tmp_path) == 1
    assert not (tmp_path / OUT).exists()
    said = f"{STAMP} names {json.dumps(stamp)}, which is not a release tag or a full commit hash"
    assert said in capsys.readouterr().err


def test_nothing_is_written_when_the_artefact_is_refused(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write(tmp_path, artefact({"pull": kind({"type": "string"})}, version=9))
    assert run(tmp_path) == 1
    assert not (tmp_path / OUT).exists()
    assert "refused, and nothing was written" in capsys.readouterr().err


@pytest.mark.parametrize("body", ["{", "[]"])
def test_an_unreadable_artefact_is_refused(
    tmp_path: pathlib.Path,
    body: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract" / "web-api.contract.json").write_text(body, encoding="utf-8")
    assert run(tmp_path) == 1
    assert "contract/web-api.contract.json" in capsys.readouterr().err


def test_a_missing_artefact_is_refused(tmp_path: pathlib.Path) -> None:
    assert run(tmp_path) == 1


def test_the_generator_runs_against_its_own_repository() -> None:
    assert pathlib.Path(__file__).resolve().parent.parent == contract_generate.ROOT


def test_functional_shapes_naming_each_other_and_themselves_import(tmp_path: pathlib.Path) -> None:
    first = {"type": "object", "properties": {"in": {"$ref": "#/$defs/Second"}}, "required": ["in"]}
    second = {
        "type": "object",
        "properties": {"is": {"anyOf": [{"$ref": "#/$defs/Second"}, {"type": "null"}]}},
    }
    looped = {"type": "object", "properties": {"for": {"$ref": "#/$defs/Looped2"}}}
    looped_back = {"type": "object", "properties": {"as": {"$ref": "#/$defs/Looped"}}}
    definitions: dict[str, object] = {
        "First": first,
        "Second": second,
        "Looped": looped,
        "Looped2": looped_back,
    }
    module = generated(tmp_path, artefact({"a": kind({"$ref": "#/$defs/First"}, definitions)}))
    assert keys(module, "First") == ({"in"}, set())
    assert module.First.__annotations__["in"] is module.Second
    assert keys(module, "Looped") == (set(), {"for"})
