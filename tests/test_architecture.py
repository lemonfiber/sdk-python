# Copyright (c) 2026 NightWorksIO
"""The rules the tree is built to: generated stays generated, and transports stay behind the client."""

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "lemonfiber"
GENERATED = PACKAGE / "_generated"
SHARED_GATE = ROOT / "scripts" / "no_open_codeql_alert.py"

TRANSPORTS = {
    "aiohttp": PACKAGE / "_aio.py",
    "urllib3": PACKAGE / "_sync.py",
}
"""Each HTTP library, and the one module allowed to import it."""

SUPPRESSIONS = re.compile(r"#\s*(type:\s*ignore|pyright:|noqa|pragma:\s*no\s*(cover|branch))", re.IGNORECASE)


def python_files(*roots: pathlib.Path) -> list[pathlib.Path]:
    """Return every Python file under these roots but the shared gate's copy."""
    return sorted(path for root in roots for path in root.rglob("*.py") if path != SHARED_GATE)


def imported(path: pathlib.Path) -> set[str]:
    """Return the top-level name of every module a file imports."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def written() -> list[pathlib.Path]:
    """Return every module of the package that is written rather than generated."""
    return [path for path in python_files(PACKAGE) if GENERATED not in path.parents]


@pytest.mark.parametrize("path", python_files(ROOT / "src", ROOT / "tests", ROOT / "scripts"), ids=str)
def test_nothing_silences_a_checker(path: pathlib.Path) -> None:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        assert not SUPPRESSIONS.search(line), f"{path}:{number} silences a checker"


@pytest.mark.parametrize("path", python_files(GENERATED), ids=str)
def test_a_generated_module_says_it_is_generated(path: pathlib.Path) -> None:
    assert "Do not edit" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", python_files(GENERATED), ids=str)
def test_a_generated_module_depends_on_nothing_but_the_standard_typing(path: pathlib.Path) -> None:
    assert imported(path) <= {"types", "typing"}


@pytest.mark.parametrize("path", written(), ids=str)
def test_no_written_module_declares_a_response_shape(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = {ast.unparse(base) for base in node.bases}
            assert not bases & {"TypedDict", "typing.TypedDict"}, f"{path} declares {node.name} by hand"
        if isinstance(node, ast.Call):
            assert ast.unparse(node.func) not in {"TypedDict", "typing.TypedDict"}, f"{path} declares a shape"


@pytest.mark.parametrize("library", sorted(TRANSPORTS))
def test_each_transport_is_imported_by_its_own_module_alone(library: str) -> None:
    importers = {path for path in python_files(PACKAGE) if library in imported(path)}
    assert importers <= {TRANSPORTS[library]}
