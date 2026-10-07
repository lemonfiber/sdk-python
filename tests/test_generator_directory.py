# Copyright (c) 2026 NightWorksIO
"""Generating from the contract as a directory: the same files as the single file, and the same refusals."""

import json
import pathlib
import typing

import pytest

from scripts.contract_generator import OUT, ROOT, run
from scripts.contract_generator.vendored import read_artefact
from tests.generating import CODE, artefact, exploded, kind, source, write, write_directory

PROBLEM = {
    "description": "Something that went wrong.",
    "type": "object",
    "properties": {
        "cause": {"anyOf": [{"$ref": "#/$defs/Problem"}, {"type": "null"}]},
        "code": {"$ref": "#/$defs/Code"},
    },
    "required": ["code"],
}
"""A definition referring to itself and to another definition."""

WHOLE = artefact(
    {
        "error": kind({"$ref": "#/$defs/Problem"}, {"Problem": PROBLEM, "Code": CODE}),
        "pull": kind({"type": "string"}),
        "word": kind({"$ref": "#/$defs/Code"}, {"Code": CODE}),
    },
    refusals={
        "ADMIT-4": {"name": "NOT_ADMITTED", "status": 403, "description": "Raised when nothing admits it."},
    },
    key_callable=[{"action": "restart", "disturbs": True, "rehearsal": False, "idempotent": False}],
    reads=[{"path": "/api/status", "parameters": [], "kinds": ["pull"], "file": False}],
)
"""A contract with a definition two kinds share, one only one kind reaches, and every list."""

DIRECTORY = pathlib.Path("contract/web-api")


def generated_files(root: pathlib.Path) -> dict[pathlib.Path, str]:
    """Return every file generated under `root`, by its path beneath the generated package."""
    return {
        path.relative_to(root / OUT): path.read_text(encoding="utf-8") for path in (root / OUT).rglob("*.py")
    }


def test_the_vendored_contract_read_as_a_directory_is_the_artefact_it_was_split_from(
    tmp_path: pathlib.Path,
) -> None:
    whole, stamp = read_artefact(ROOT)
    write_directory(tmp_path, whole, stamp)
    assert read_artefact(tmp_path) == (whole, stamp)


def test_a_directory_writes_the_files_its_single_file_writes(tmp_path: pathlib.Path) -> None:
    single, split = tmp_path / "single", tmp_path / "split"
    write(single, WHOLE)
    write_directory(split, WHOLE)
    assert run(single) == 0
    assert run(split) == 0
    assert generated_files(split) == generated_files(single)
    assert "type Code = str" in source(split, "shared", "error__word.py")


def test_a_reference_is_resolved_against_the_file_it_sits_in(tmp_path: pathlib.Path) -> None:
    write_directory(tmp_path, WHOLE)
    problem = json.loads((tmp_path / DIRECTORY / "defs/Problem.json").read_text(encoding="utf-8"))
    assert problem["properties"]["code"] == {"$ref": "Code.json"}
    error = json.loads((tmp_path / DIRECTORY / "kinds/error.json").read_text(encoding="utf-8"))
    assert error["properties"]["data"] == {"$ref": "../defs/Problem.json"}
    whole, _ = read_artefact(tmp_path)
    kinds = typing.cast("dict[str, dict[str, object]]", whole["kinds"])
    assert set(typing.cast("dict[str, object]", kinds["error"]["$defs"])) == {"Problem", "Code"}
    assert set(typing.cast("dict[str, object]", kinds["word"]["$defs"])) == {"Code"}
    assert "$defs" not in kinds["pull"]


def amend(root: pathlib.Path, file: str, change: typing.Callable[[dict[str, object]], object]) -> None:
    """Rewrite one file of the vendored directory as `change` returns it."""
    path = root / DIRECTORY / file
    held = typing.cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(change(held)), encoding="utf-8")


def data_refers_to(reference: object) -> typing.Callable[[dict[str, object]], object]:
    """Return a change pointing a kind's `data` at this reference."""

    def change(schema: dict[str, object]) -> object:
        typing.cast("dict[str, object]", schema["properties"])["data"] = {"$ref": reference}
        return schema

    return change


def code_refers_to(reference: object) -> typing.Callable[[dict[str, object]], object]:
    """Return a change pointing a definition's `code` property at this reference."""

    def change(schema: dict[str, object]) -> object:
        typing.cast("dict[str, object]", schema["properties"])["code"] = {"$ref": reference}
        return schema

    return change


@pytest.mark.parametrize(
    ("file", "change", "said"),
    [
        (
            "kinds/error.json",
            data_refers_to("#/$defs/Problem"),
            'contract/web-api/kinds/error.json refers to "#/$defs/Problem", which is not a definition\'s file',
        ),
        (
            "kinds/error.json",
            data_refers_to("../defs/Missing.json"),
            (
                'contract/web-api/kinds/error.json refers to "../defs/Missing.json", and the vendored copy holds '
                "no contract/web-api/defs/Missing.json"
            ),
        ),
        (
            "defs/Problem.json",
            code_refers_to("Missing.json"),
            (
                'contract/web-api/defs/Problem.json refers to "Missing.json", and the vendored copy holds no '
                "contract/web-api/defs/Missing.json"
            ),
        ),
        (
            "defs/Problem.json",
            code_refers_to("../kinds/pull.json"),
            'contract/web-api/defs/Problem.json refers to "../kinds/pull.json", which is not a definition\'s file',
        ),
        (
            "kinds/error.json",
            data_refers_to("https://example.com/defs/Code.json"),
            'refers to "https://example.com/defs/Code.json", which is not a definition\'s file',
        ),
        (
            "kinds/error.json",
            data_refers_to("/defs/Code.json"),
            'refers to "/defs/Code.json", which is not a',
        ),
        ("kinds/error.json", data_refers_to("../defs/Code"), 'refers to "../defs/Code", which is not a'),
        ("kinds/error.json", data_refers_to(3), "refers to 3, which is not a definition's file"),
    ],
)
def test_a_reference_to_no_definition_is_refused_naming_it_and_its_file_and_nothing_is_written(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    file: str,
    change: typing.Callable[[dict[str, object]], object],
    said: str,
) -> None:
    write_directory(tmp_path, WHOLE)
    amend(tmp_path, file, change)
    assert run(tmp_path) == 1
    assert not (tmp_path / OUT).exists()
    assert said in capsys.readouterr().err


def refused(root: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> str:
    """Generate from what is vendored under `root`, and return the refusal, having checked nothing was written."""
    assert run(root) == 1
    assert not (root / OUT).exists()
    return capsys.readouterr().err


def test_both_layouts_vendored_at_once_are_refused(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write(tmp_path, WHOLE)
    write_directory(tmp_path, WHOLE)
    said = refused(tmp_path, capsys)
    assert "contract/web-api.contract.json and contract/web-api/ are both vendored" in said


def with_definitions(schema: dict[str, object]) -> object:
    """Return a kind's schema carrying definitions of its own, as the single file writes one."""
    return {**schema, "$defs": {"Code": CODE}}


def setting(key: str, value: object) -> typing.Callable[[dict[str, object]], object]:
    """Return a change setting one field of a file to this value."""
    return lambda held: {**held, key: value}


def replaced_by(value: object) -> typing.Callable[[dict[str, object]], object]:
    """Return a change replacing a file whole with this value."""
    return lambda _: value


@pytest.mark.parametrize(
    ("file", "change", "said"),
    [
        ("index.json", replaced_by([]), "contract/web-api/index.json is not an object"),
        ("index.json", setting("kinds", ["pull"]), 'names its kinds as ["pull"]'),
        (
            "index.json",
            setting("reads", "../reads.json"),
            'contract/web-api/index.json names "../reads.json", which is not a file in contract/web-api/',
        ),
        ("index.json", setting("reads", 3), "names 3, which is not a file in"),
        ("index.json", setting("reads", "/reads.json"), 'names "/reads.json", which is not a file in'),
        ("index.json", setting("reads", ""), 'names "", which is not a file in'),
        (
            "index.json",
            setting("reads", "lists.json"),
            "contract/web-api/lists.json could not be",
        ),
        ("kinds/pull.json", with_definitions, "contract/web-api/kinds/pull.json holds $defs"),
        ("defs/Code.json", replaced_by("a schema"), "contract/web-api/defs/Code.json is not an object"),
        (
            "defs/Code.json",
            setting("$schema", "http://json-schema.org/draft-07/schema#"),
            (
                'contract/web-api/defs/Code.json is written in "http://json-schema.org/draft-07/schema#", and '
                'contract/web-api/kinds/error.json, which reaches it, in "https://json-schema.org/draft/2020-12/schema"'
            ),
        ),
        ("index.json", setting("api_version", 2), "api_version 2"),
    ],
)
def test_a_directory_this_generator_cannot_read_is_refused_naming_the_file(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    file: str,
    change: typing.Callable[[dict[str, object]], object],
    said: str,
) -> None:
    write_directory(tmp_path, WHOLE)
    amend(tmp_path, file, change)
    assert said in refused(tmp_path, capsys)


def test_a_kind_that_is_not_a_schema_is_refused_as_the_single_file_refuses_it(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_directory(tmp_path, WHOLE)
    (tmp_path / DIRECTORY / "kinds/pull.json").write_text("3", encoding="utf-8")
    assert "the kind `pull` is 3" in refused(tmp_path, capsys)


@pytest.mark.parametrize(
    ("definitions", "said"),
    [
        (
            {
                "R": {"type": "object", "properties": {"v": {"$ref": "#/$defs/Code", "type": "string"}}},
                "Code": CODE,
            },
            "/a/$defs/R/properties/v (type)",
        ),
        ({"Kind": CODE}, "`Kind`, defined by `a`, takes a name this generator writes itself"),
        ({"lower": CODE}, "`lower`, defined by `a`, is not a name a Python type can carry"),
    ],
)
def test_a_guard_the_single_file_meets_is_met_by_the_directory(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    definitions: dict[str, object],
    said: str,
) -> None:
    first = next(iter(definitions))
    whole = artefact({"a": kind({"$ref": f"#/$defs/{first}"}, definitions)})
    write_directory(tmp_path / "split", whole)
    write(tmp_path / "single", whole)
    assert said in refused(tmp_path / "single", capsys)
    assert said in refused(tmp_path / "split", capsys)


def test_a_definition_no_kind_reaches_is_not_written(tmp_path: pathlib.Path) -> None:
    files = exploded(WHOLE)
    assert "defs/Code.json" in files
    write_directory(tmp_path, WHOLE)
    (tmp_path / DIRECTORY / "defs/Unreached.json").write_text(
        json.dumps({"type": "integer"}),
        encoding="utf-8",
    )
    assert run(tmp_path) == 0
    assert "Unreached" not in "".join(generated_files(tmp_path).values())
