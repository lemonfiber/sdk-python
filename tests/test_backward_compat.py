# Copyright (c) 2026 NightWorksIO
"""The backward-compatibility check: who consumes this package, what breaks them, and which breaks are accepted."""

import base64
import sys
from typing import TYPE_CHECKING

import griffe
import pytest

from scripts import backward_compat

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

REVISION = "d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6"


MAP = """
[[repo]]
name = "sdk-python"
lang = "Python"

[[repo]]
name = "integration-home-assistant"
lang = "Python"

[[repo]]
name = "lemonfiber"
lang = "Rust"

[[edge]]
from = "lemonfiber"
to = "sdk-python"

[[edge]]
from = "integration-home-assistant"
to = "sdk-python"

[[edge]]
from = "integration-home-assistant"
to = "lemonfiber"
"""


def spec_with(root: pathlib.Path, text: str) -> pathlib.Path:
    """Write a spec checkout holding only this map."""
    (root / "30-repos").mkdir(parents=True)
    (root / "30-repos/repos.toml").write_text(text, encoding="utf-8")
    return root


def test_the_consumers_are_the_python_repositories_drawn_to_this_one(tmp_path: pathlib.Path) -> None:
    assert backward_compat.consumers(spec_with(tmp_path, MAP)) == ["integration-home-assistant"]


def recording(
    pin: str,
    path: str = "custom_components/lemonfiber/_vendor/lemonfiber/REVISION",
) -> backward_compat.Fetch:
    """Answer as GitHub would for a consumer recording this pin at this path."""

    def fetch(asked: str) -> object:
        if asked.endswith("/git/trees/HEAD?recursive=1"):
            return {"tree": [{"path": "README.md"}, {"path": path}]}
        return {"content": base64.b64encode(f"{pin}\n".encode()).decode()}

    return fetch


def answers_nothing(_asked: str) -> object:
    """Answer as GitHub does for a repository that is missing or empty."""
    return None


def test_a_pin_is_read_from_wherever_the_consumer_vendors() -> None:
    assert list(backward_compat.pins("x", recording(REVISION))) == [REVISION]
    assert list(backward_compat.pins("x", recording(REVISION, "_vendor/lemonfiber/REVISION"))) == [REVISION]
    assert list(backward_compat.pins("x", recording(REVISION, "other/REVISION"))) == []


def test_an_empty_or_missing_consumer_pins_nothing() -> None:
    assert list(backward_compat.pins("x", answers_nothing)) == []


def test_no_consumer_and_no_pin_compare_nothing_and_say_so(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert backward_compat.run(spec_with(tmp_path / "a", "repo = []\n"), tmp_path, answers_nothing) == 0
    assert "names no consumer" in capsys.readouterr().out
    assert (
        backward_compat.run(spec_with(tmp_path / "b", MAP), project(tmp_path / "repo"), answers_nothing) == 0
    )
    assert "records no vendored commit" in capsys.readouterr().out


def project(root: pathlib.Path, accepted: str = "[]") -> pathlib.Path:
    """Write a `pyproject.toml` accepting these breaks under `root`, and return `root`."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f"[tool.lemonfiber.backward-compatibility]\naccepted = {accepted}\n",
        encoding="utf-8",
    )
    return root


GONE = backward_compat.Break("lemonfiber.Gone", "object-removed", "Gone: Public object was removed")
ASK = backward_compat.Break("lemonfiber.ask(query)", "parameter-removed", "ask(query): Parameter was removed")
ACCEPTING_GONE = (
    '[{ symbol = "lemonfiber.Gone", kind = "object-removed", reason = "named apart from the contract" }]'
)


def breaking(*found: backward_compat.Break) -> Callable[[str, pathlib.Path], list[backward_compat.Break]]:
    """Return a comparison that finds these breaks against any pin."""

    def compare(_against: str, _repo: pathlib.Path) -> list[backward_compat.Break]:
        return list(found)

    return compare


def checked(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    found: tuple[backward_compat.Break, ...],
    accepted: str = "[]",
    *,
    marked: bool = True,
) -> int:
    """Run the check against one consumer's pin, finding these breaks, with these accepted."""
    monkeypatch.setattr(backward_compat, "breakages", breaking(*found))

    def marking(_repo: pathlib.Path, _since: str) -> bool:
        return marked

    monkeypatch.setattr(backward_compat, "marked_breaking", marking)
    return backward_compat.run(
        spec_with(tmp_path / "spec", MAP),
        project(tmp_path / "repo", accepted),
        recording(REVISION),
    )


def test_a_pin_that_is_not_a_commit_fails(tmp_path: pathlib.Path) -> None:
    assert (
        backward_compat.run(spec_with(tmp_path / "spec", MAP), project(tmp_path / "repo"), recording("main"))
        == 1
    )


def test_a_break_against_a_pin_fails_naming_the_consumer_and_the_entry_that_would_accept_it(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert checked(tmp_path, monkeypatch, (GONE,)) == 1
    said = capsys.readouterr().out
    assert (
        "breaks integration-home-assistant, which vendors d2bf74b9: Gone: Public object was removed" in said
    )
    assert '{ symbol = "lemonfiber.Gone", kind = "object-removed", reason = "..." }' in said


def test_no_break_against_a_pin_passes(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert checked(tmp_path, monkeypatch, ()) == 0


def test_an_accepted_break_passes_and_is_said(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert checked(tmp_path, monkeypatch, (GONE,), ACCEPTING_GONE) == 0
    assert "accepted, breaking integration-home-assistant at d2bf74b9: Gone" in capsys.readouterr().out


def test_an_accepted_break_lets_no_other_break_through(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert checked(tmp_path, monkeypatch, (GONE, ASK), ACCEPTING_GONE) == 1
    said = capsys.readouterr().out
    assert "::error::breaks integration-home-assistant, which vendors d2bf74b9: ask(query)" in said
    assert "::error::breaks integration-home-assistant, which vendors d2bf74b9: Gone" not in said


def test_a_break_is_accepted_for_the_kind_it_names_alone(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = backward_compat.Break(
        "lemonfiber.Gone",
        "attribute-changed-value",
        "Gone: Attribute value was changed",
    )
    assert checked(tmp_path, monkeypatch, (changed,), ACCEPTING_GONE) == 1


def test_an_accepted_break_with_no_commit_marked_breaking_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert checked(tmp_path, monkeypatch, (GONE,), ACCEPTING_GONE, marked=False) == 1
    assert "no commit since d2bf74b9 is marked breaking" in capsys.readouterr().out


def test_an_accepted_break_that_breaks_nothing_is_said_to_be_removed(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert checked(tmp_path, monkeypatch, (), ACCEPTING_GONE) == 0
    assert "::warning::object-removed of lemonfiber.Gone is accepted and breaks no consumer's pin" in (
        capsys.readouterr().out
    )


@pytest.mark.parametrize(
    "accepted",
    [
        '[{ symbol = "lemonfiber.Gone", kind = "object-removed" }]',
        '[{ symbol = "lemonfiber.Gone", kind = "object-removed", reason = "" }]',
        '[{ symbol = "lemonfiber.Gone", kind = "object-removed", reason = "r", extra = "x" }]',
        '[{ symbol = "lemonfiber.Gone", kind = 1, reason = "r" }]',
        '["lemonfiber.Gone"]',
    ],
)
def test_an_accepted_break_that_is_not_a_symbol_a_kind_and_a_reason_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    accepted: str,
) -> None:
    assert checked(tmp_path, monkeypatch, (GONE,), accepted) == 1
    assert "names its symbol, its kind and its reason" in capsys.readouterr().out


def test_a_project_that_accepts_nothing_lists_nothing(tmp_path: pathlib.Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert backward_compat.accepted(tmp_path) == set()


def test_this_project_accepts_what_it_lists() -> None:
    assert isinstance(backward_compat.accepted(backward_compat.ROOT), set)


class Logged:
    """What `git log` printed, as `subprocess.run` hands it back."""

    def __init__(self, stdout: str) -> None:
        """Hold the output."""
        super().__init__()
        self.stdout = stdout


def logging(monkeypatch: pytest.MonkeyPatch, messages: list[str]) -> list[list[str]]:
    """Answer `git log` with these commit messages, recording each command it is asked."""
    asked: list[list[str]] = []

    def run(command: list[str], **_options: object) -> Logged:
        asked.append(command)
        return Logged("".join(f"{message}\n\x00\n" for message in messages))

    monkeypatch.setattr(backward_compat.subprocess, "run", run)
    return asked


@pytest.mark.parametrize(
    "messages",
    [
        ["feat!: name the session apart", "fix: a typo"],
        ["refactor(api)!: move it"],
        ["feat: a thing\n\nBREAKING CHANGE: the old one is gone"],
        ["feat: a thing\n\nBREAKING-CHANGE: the old one is gone"],
    ],
)
def test_a_commit_is_marked_breaking_as_the_changelog_reads_one(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    messages: list[str],
) -> None:
    asked = logging(monkeypatch, messages)
    assert backward_compat.marked_breaking(tmp_path, REVISION)
    [command] = asked
    assert command[1:] == ["-C", str(tmp_path), "log", "--format=%B%x00", f"{REVISION}..HEAD"]


@pytest.mark.parametrize(
    "messages",
    [
        ["feat: a thing", "fix: it says BREAKING CHANGE: in passing"],
        ["feat: a thing\n\nwhy!: not a subject"],
        ["fix: wow!: not a type"],
        [],
    ],
)
def test_a_commit_not_marked_breaking_is_not_read_as_one(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    messages: list[str],
) -> None:
    logging(monkeypatch, messages)
    assert not backward_compat.marked_breaking(tmp_path, REVISION)


def test_the_commits_cannot_be_read_without_git(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def finding_nothing(_name: str) -> None:
        return None

    monkeypatch.setattr(backward_compat.shutil, "which", finding_nothing)
    with pytest.raises(FileNotFoundError):
        backward_compat.marked_breaking(tmp_path, REVISION)


class Removed:
    """What a removed object's break is to."""

    path = "lemonfiber.Gone"


class Breakage:
    """A breaking change griffe found, explained in these words."""

    kind = griffe.BreakageKind.OBJECT_REMOVED
    obj = Removed()
    old_value = None
    new_value = None

    def __init__(self, said: str) -> None:
        """Hold the explanation."""
        super().__init__()
        self.said = said

    def explain(self) -> str:
        """Return the explanation."""
        return self.said


def test_a_breakage_is_what_griffe_finds_between_the_pin_and_the_tree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: list[tuple[str, dict[str, object]]] = []

    def load_git(package: str, **given: object) -> str:
        loaded.append((package, given))
        return "at the pin"

    def load(package: str, **given: object) -> str:
        loaded.append((package, given))
        return "in the tree"

    def find_breaking_changes(old: str, new: str) -> list[Breakage]:
        return [Breakage(f"{old} to {new}")]

    monkeypatch.setattr(backward_compat.griffe, "load_git", load_git)
    monkeypatch.setattr(backward_compat.griffe, "load", load)
    monkeypatch.setattr(backward_compat.griffe, "find_breaking_changes", find_breaking_changes)
    assert backward_compat.breakages(REVISION, tmp_path) == [
        backward_compat.Break("lemonfiber.Gone", "object-removed", "at the pin to in the tree"),
    ]
    assert loaded == [
        (backward_compat.PACKAGE, {"ref": REVISION, "repo": tmp_path, "search_paths": ["src"]}),
        (backward_compat.PACKAGE, {"search_paths": [str(tmp_path / "src")]}),
    ]


def surface(root: pathlib.Path, modules: dict[str, str]) -> griffe.Object | griffe.Alias:
    """Write a package of these modules under `root` and load its surface as the check does."""
    package = root / "surface"
    package.mkdir(parents=True)
    for name, text in modules.items():
        (package / f"{name}.py").write_text(text, encoding="utf-8")
    return griffe.load("surface", search_paths=[str(root)])


def changes(tmp_path: pathlib.Path, before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Return the breakages the check keeps between two versions of a package."""
    old = surface(tmp_path / "old", before)
    new = surface(tmp_path / "new", after)
    return [
        breakage.explain()
        for breakage in griffe.find_breaking_changes(old, new)
        if not backward_compat.same_value(breakage, old, new)
    ]


def test_a_default_moved_to_another_module_with_its_value_is_no_breakage(tmp_path: pathlib.Path) -> None:
    before = {
        "__init__": "from surface import _wire\n\ndef ask(*, timeout: float = _wire.TIMEOUT) -> None: ...\n",
        "_wire": "TIMEOUT = 30.0\n",
    }
    after = {
        "__init__": "from surface._calls import TIMEOUT\n\ndef ask(*, timeout: float = TIMEOUT) -> None: ...\n",
        "_calls": "TIMEOUT = 30.0\n",
    }
    assert changes(tmp_path, before, after) == []


def test_a_number_become_the_enum_member_equal_to_it_is_no_breakage(tmp_path: pathlib.Path) -> None:
    after = {"__init__": "from http import HTTPStatus\n\nOPENED = HTTPStatus.OK\n"}
    assert changes(tmp_path, {"__init__": "OPENED = 200\n"}, after) == []


@pytest.mark.parametrize(
    ("was", "now"),
    [
        ("30.0", "31.0"),
        ("200", "'200'"),
        ("200", "frozenset()"),
        ("200", "missing.NAME"),
    ],
)
def test_a_value_that_is_not_the_one_it_was_is_a_breakage(tmp_path: pathlib.Path, was: str, now: str) -> None:
    [found] = changes(tmp_path, {"__init__": f"VALUE = {was}\n"}, {"__init__": f"VALUE = {now}\n"})
    assert "VALUE" in found


def test_a_default_that_is_not_the_one_it_was_is_a_breakage(tmp_path: pathlib.Path) -> None:
    before = {"__init__": "def ask(*, timeout: float = 30.0) -> None: ...\n"}
    after = {"__init__": "def ask(*, timeout: float = 31.0) -> None: ...\n"}
    [found] = changes(tmp_path, before, after)
    assert "timeout" in found


def test_a_break_is_named_by_its_object_and_the_parameter_it_is_to(tmp_path: pathlib.Path) -> None:
    old = surface(tmp_path / "old", {"__init__": "def ask(query: str) -> None: ...\n\nGONE = 1\n"})
    new = surface(tmp_path / "new", {"__init__": "def ask() -> None: ...\n"})
    found = sorted(
        (one.symbol, one.kind)
        for one in map(backward_compat.break_of, griffe.find_breaking_changes(old, new))
    )
    assert found == [("surface.GONE", "object-removed"), ("surface.ask(query)", "parameter-removed")]


def test_the_command_line_names_the_spec_and_the_tree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[pathlib.Path, pathlib.Path]] = []

    def checking(spec: pathlib.Path, repo: pathlib.Path) -> int:
        asked.append((spec, repo))
        return 1

    monkeypatch.setattr(backward_compat, "run", checking)
    monkeypatch.setattr(
        sys,
        "argv",
        ["backward_compat.py", "--spec", str(tmp_path / "s"), "--repo", str(tmp_path)],
    )
    assert backward_compat.main() == 1
    assert asked == [(tmp_path / "s", tmp_path)]
