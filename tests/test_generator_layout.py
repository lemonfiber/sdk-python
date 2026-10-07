# Copyright (c) 2026 NightWorksIO
"""Which module each generated shape is written in, and the cap no module outgrows."""

import typing

from scripts import contract_generator
from scripts.contract_generator import OUT, run
from scripts.line_cap import LineCapError, lines_in
from tests.generating import CODE, artefact, generated, kind, refusal, source, write

if typing.TYPE_CHECKING:
    import pathlib

    import pytest

SHARED = {
    "description": "Carried by more than one kind.",
    "type": "object",
    "properties": {"code": {"$ref": "#/$defs/Code"}},
    "required": ["code"],
}
OWN = {"description": "Carried by one kind.", "type": "object", "properties": {"at": {"type": "integer"}}}


def long(name: str, *refers: str, lines: int = 12) -> dict[str, object]:
    """Return an object schema whose description runs to `lines` lines, naming `refers` as its fields."""
    return {
        "description": "\n".join(f"{name} says one more thing on line {line}." for line in range(lines)),
        "type": "object",
        "properties": {other.lower(): {"$ref": f"#/$defs/{other}"} for other in refers},
    }


def test_a_kinds_own_shapes_are_its_module_and_shared_ones_a_module_of_their_carriers(
    tmp_path: pathlib.Path,
) -> None:
    whole = artefact(
        {
            "a": kind({"$ref": "#/$defs/Shared"}, {"Shared": SHARED, "Code": CODE, "Own": OWN}),
            "b": kind({"$ref": "#/$defs/Shared"}, {"Shared": SHARED, "Code": CODE}),
        },
    )
    module = generated(tmp_path, whole)
    own = source(tmp_path, "kinds", "a.py")
    assert "class AEnvelope(typing.TypedDict):" in own
    assert "class Own(typing.TypedDict):" in own
    assert "from ..shared.a__b import Shared" in own
    assert "class Shared(typing.TypedDict):" in source(tmp_path, "shared", "a__b.py")
    assert '"""The shapes `a` and `b` both carry.' in source(tmp_path, "shared", "a__b.py")
    assert module.AEnvelope.__annotations__["data"] is module.Shared
    assert {"AEnvelope", "BEnvelope", "Code", "Own", "Shared"} <= set(module.__all__)


def test_a_module_spelling_nothing_through_typing_does_not_import_it(tmp_path: pathlib.Path) -> None:
    module = generated(
        tmp_path,
        artefact({one: kind({"$ref": "#/$defs/Code"}, {"Code": CODE}) for one in ("a", "b", "c")}),
    )
    shared = source(tmp_path, "shared", "a__b__c.py")
    assert "import typing" not in shared
    assert '"""The shapes `a`, `b` and `c` all carry.' in shared
    assert module.Code.__value__ is str


def test_a_kind_python_reserves_is_written_as_a_module_it_can_import(tmp_path: pathlib.Path) -> None:
    module = generated(tmp_path, artefact({"import": kind({"type": "string"})}))
    assert "class ImportEnvelope(typing.TypedDict):" in source(tmp_path, "kinds", "import_.py")
    assert module.ImportEnvelope.__annotations__["kind"] == typing.Literal["import"]


def test_a_module_over_the_cap_is_a_package_of_parts_importing_one_way(tmp_path: pathlib.Path) -> None:
    definitions: dict[str, object] = {
        "First": long("First"),
        "Second": long("Second", "First"),
        "Third": long("Third", "Second"),
        "Fourth": long("Fourth", "Third", "First"),
    }
    module = generated(tmp_path, artefact({"big": kind({"$ref": "#/$defs/Fourth"}, definitions)}), cap=60)
    parts = sorted((tmp_path / OUT / "kinds" / "big").glob("*.py"))
    assert [part.name for part in parts] == ["__init__.py", "big_envelope.py", "first.py", "third.py"]
    for part in parts:
        assert lines_in(part.read_text(encoding="utf-8")) <= 60
    assert "from .first import First" in source(tmp_path, "kinds", "big", "third.py")
    assert "from .third import Fourth" in source(tmp_path, "kinds", "big", "big_envelope.py")
    assert "gathered from its parts" in source(tmp_path, "kinds", "big", "__init__.py")
    assert module.Fourth.__annotations__["third"] == typing.NotRequired[module.Third]
    assert module.BigEnvelope.__annotations__["data"] is module.Fourth


def test_shapes_that_fit_together_share_a_part(tmp_path: pathlib.Path) -> None:
    small = {"type": "object", "properties": {"n": {"type": "integer"}}}
    definitions: dict[str, object] = {"Huge": long("Huge", lines=40), "Little": small, "Tiny": small}
    generated(tmp_path, artefact({"big": kind({"$ref": "#/$defs/Huge"}, definitions)}), cap=64)
    parts = sorted((tmp_path / OUT / "kinds" / "big").glob("*.py"))
    assert len(parts) > 2
    holding = [part.read_text(encoding="utf-8") for part in parts]
    assert [text for text in holding if "class Little(" in text] == [
        text for text in holding if "class Tiny(" in text
    ]


def test_shapes_naming_one_another_past_the_cap_are_refused_naming_them_and_their_kind() -> None:
    definitions: dict[str, object] = {"Ping": long("Ping", "Pong"), "Pong": long("Pong", "Ping")}
    said = refusal(artefact({"big": kind({"$ref": "#/$defs/Ping"}, definitions)}), cap=40)
    assert said.startswith("`Ping` and `Pong`, which only `big` carries, name one another and would hold ")
    assert said.endswith(" lines as one module, over the 40 a module may hold")


def test_one_shape_past_the_cap_is_refused_naming_it_and_its_kind() -> None:
    said = refusal(artefact({"big": kind({"$ref": "#/$defs/Ping"}, {"Ping": long("Ping")})}), cap=20)
    assert said.startswith("`Ping`, which only `big` carries, would hold ")


def test_a_list_past_the_cap_is_refused_naming_its_module() -> None:
    refusals = {
        f"READ-{at}": {"name": f"NUMBER_{at}", "status": 404, "description": f"Raised the {at} time."}
        for at in range(40)
    }
    said = refusal(artefact({"pull": kind({"type": "string"})}, refusals), cap=60)
    assert said.startswith(f"{OUT}/refusals.py would hold ")
    assert said.endswith(" lines, over the 60 a module may hold")


def test_a_shape_naming_one_some_of_its_carriers_lack_is_refused() -> None:
    said = refusal(
        artefact(
            {
                "a": kind({"$ref": "#/$defs/Shared"}, {"Shared": SHARED, "Code": CODE}),
                "b": kind({"$ref": "#/$defs/Shared"}, {"Shared": SHARED}),
            },
        ),
    )
    assert said == "`Shared`, which `a` and `b` both carry, names `Code`, which `b` does not define"


def test_two_sets_of_kinds_written_as_one_module_are_refused() -> None:
    said = refusal(
        artefact(
            {
                "a": kind({"$ref": "#/$defs/Left"}, {"Left": CODE}),
                "b__c": kind({"$ref": "#/$defs/Left"}, {"Left": CODE}),
                "a__b": kind({"$ref": "#/$defs/Right"}, {"Right": CODE}),
                "c": kind({"$ref": "#/$defs/Right"}, {"Right": CODE}),
            },
        ),
    )
    assert said.endswith("would both be written as `shared.a__b__c`")


def test_two_parts_written_under_one_name_are_refused() -> None:
    definitions: dict[str, object] = {"AB": long("AB"), "Ab": long("Ab")}
    said = refusal(artefact({"a": kind({"$ref": "#/$defs/AB"}, definitions)}), cap=40)
    assert said == "two parts of `kinds.a` would both be written as `kinds.a.ab`"


def test_what_an_earlier_generation_wrote_is_replaced(tmp_path: pathlib.Path) -> None:
    gone = tmp_path / OUT / "kinds" / "gone.py"
    gone.parent.mkdir(parents=True)
    gone.write_text("", encoding="utf-8")
    write(tmp_path, artefact({"pull": kind({"type": "string"})}))
    assert run(tmp_path) == 0
    assert not gone.exists()
    assert (tmp_path / OUT / "kinds" / "pull.py").is_file()


def test_a_cap_pyproject_does_not_declare_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def undeclared(root: pathlib.Path, held: str) -> int:
        message = f"no {held} cap under {root}"
        raise LineCapError(message)

    monkeypatch.setattr(contract_generator, "line_cap", undeclared)
    said = refusal(artefact({"pull": kind({"type": "string"})}))
    assert said.startswith("no source cap under ")
