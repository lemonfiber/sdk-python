# Copyright (c) 2026 NightWorksIO
"""Generating the shapes from the artefact, and refusing an artefact that cannot be read one way."""

import importlib.util
import json
import pathlib
import typing

import pytest

from scripts import contract_generate
from scripts.contract_generate import OUT, STAMP, ArtefactRefusedError, generate, run

if typing.TYPE_CHECKING:
    import types

ENVELOPE_DESCRIPTION = "The wrapper every machine-readable payload arrives in."


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


def artefact(kinds: dict[str, object], refusals: object = None, version: object = 1) -> dict[str, object]:
    """Return a whole artefact describing these kinds."""
    whole: dict[str, object] = {"api_version": version, "kinds": kinds}
    if refusals is not None:
        whole["refusals"] = refusals
    return whole


def write(root: pathlib.Path, whole: object, stamp: str | None = "v1.0.0") -> None:
    """Vendor an artefact under `root` as `contract/` holds one."""
    (root / "contract").mkdir(parents=True, exist_ok=True)
    (root / "contract" / "web-api.contract.json").write_text(json.dumps(whole), encoding="utf-8")
    if stamp is not None:
        (root / "contract" / "VERSION").write_text(f"{stamp}\n", encoding="utf-8")


def load(root: pathlib.Path) -> types.ModuleType:
    """Import the contract module generated under `root`."""
    path = root / OUT / "contract.py"
    spec = importlib.util.spec_from_file_location(f"generated_{abs(hash(root))}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generated(tmp_path: pathlib.Path, whole: object) -> types.ModuleType:
    """Generate from an artefact and import what was written."""
    write(tmp_path, whole)
    assert run(tmp_path) == 0
    return load(tmp_path)


def refusal(whole: dict[str, object]) -> str:
    """Return the sentence generation refuses an artefact with."""
    with pytest.raises(ArtefactRefusedError) as refused:
        generate(whole, "v1.0.0")
    return str(refused.value)


def keys(module: types.ModuleType, name: str) -> tuple[set[str], set[str]]:
    """Return a generated TypedDict's required and optional keys."""
    shape = getattr(module, name)
    return set(shape.__required_keys__), set(shape.__optional_keys__)


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
CODE = {"description": "A stable identifier.\n\nNever recycled.", "type": "string"}


def test_the_vendored_artefact_generates_what_is_committed() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    whole = json.loads((root / "contract/web-api.contract.json").read_text(encoding="utf-8"))
    stamp = (root / "contract/VERSION").read_text(encoding="utf-8").strip()
    files = generate(whole, stamp)
    assert set(files) == {OUT / "__init__.py", OUT / "contract.py"}
    committed = (root / OUT / "contract.py").read_text(encoding="utf-8")
    for name in ("class StatusEnvelope(typing.TypedDict):", f"artefact at {stamp}", "__all__ = ["):
        assert name in files[OUT / "contract.py"]
        assert name in committed


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
    source = (tmp_path / OUT / "contract.py").read_text(encoding="utf-8")
    assert 'type Scope = ScopeWholeStack | ScopeService\n"""How much a backup covers."""' in source


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


def test_a_missing_stamp_says_the_revision_is_unknown(tmp_path: pathlib.Path) -> None:
    write(tmp_path, artefact({"pull": kind({"type": "string"})}), stamp=None)
    assert run(tmp_path) == 0
    assert "an unknown revision" in (tmp_path / OUT / "contract.py").read_text(encoding="utf-8")


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
        ({"$ref": "other.json#/x"}, "refers to other.json#/x, outside the definitions beside it"),
        ({"$ref": "#/$defs/Missing"}, "`a` refers to `Missing`, which it does not define"),
    ],
)
def test_a_shape_this_generator_cannot_read_is_refused_rather_than_guessed(schema: object, said: str) -> None:
    assert said in refusal(artefact({"a": kind(schema, {})}))


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
