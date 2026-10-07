# Copyright (c) 2026 NightWorksIO
"""The rules the tree is built to: generated stays generated, transports stay behind the client, files stay short."""

import ast
import io
import pathlib
import re
import tokenize

import pytest

from scripts.line_cap import LineCapError, line_cap, lines_in

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "lemonfiber"
GENERATED = PACKAGE / "_generated"
SHARED_GATE = ROOT / "scripts" / "no_open_codeql_alert.py"

TRANSPORTS = {
    "aiohttp": PACKAGE / "_aio.py",
    "urllib3": PACKAGE / "_sync.py",
}
"""Each HTTP library, and the one module allowed to import it."""

SOURCES = (ROOT / "src", ROOT / "scripts")
"""Where every file is held to the source cap."""

TESTS = ROOT / "tests"
"""Where every file is held to the test cap."""

IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9]*-R\d+\b")
"""A requirement identifier, which belongs in a commit trailer and a pull request, not beside the code."""

REASONING = re.compile(
    r"^\s*(?:because|we\b|the reason|this is why|originally|it turns out|note that|arguably)",
    re.IGNORECASE,
)
"""How a line opens that argues rather than states what a thing is or does."""

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


def prose(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return every line of a file's comments and docstrings, with the line it stands on."""
    text = path.read_text(encoding="utf-8")
    lines = [
        (token.start[0], token.string.lstrip("#"))
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    ]
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            lines.extend((node.lineno + at, line) for at, line in enumerate(node.value.value.splitlines()))
    return lines


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
def test_a_generated_module_depends_on_nothing_but_the_standard_typing_and_enum(path: pathlib.Path) -> None:
    assert imported(path) <= {"enum", "types", "typing"}


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


@pytest.mark.parametrize("path", python_files(*SOURCES), ids=str)
def test_no_source_file_outgrows_its_cap(path: pathlib.Path) -> None:
    lines = lines_in(path.read_text(encoding="utf-8"))
    cap = line_cap(ROOT, "source")
    assert lines <= cap, f"{path} holds {lines} lines, over the {cap} a source file may: split it by concept"


@pytest.mark.parametrize("path", python_files(TESTS), ids=str)
def test_no_test_file_outgrows_its_cap(path: pathlib.Path) -> None:
    lines = lines_in(path.read_text(encoding="utf-8"))
    cap = line_cap(ROOT, "tests")
    assert lines <= cap, (
        f"{path} holds {lines} lines, over the {cap} a test file may: split it by what it asserts"
    )


def test_each_cap_holds_files_to_it() -> None:
    assert python_files(*SOURCES)
    assert python_files(TESTS)
    assert any(GENERATED in path.parents for path in python_files(*SOURCES))


def test_a_cap_is_read_from_pyproject(tmp_path: pathlib.Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.lemonfiber.line-cap]\ntests = 40\n", encoding="utf-8")
    assert line_cap(tmp_path, "tests") == 40


@pytest.mark.parametrize(
    "declared",
    [
        "",
        "[tool.lemonfiber.line-cap]\nsource = '550'\n",
        "[tool.lemonfiber.line-cap]\nsource = true\n",
        "[tool.lemonfiber.line-cap]\nsource = 0\n",
    ],
)
def test_a_cap_that_is_not_a_number_of_lines_is_refused(tmp_path: pathlib.Path, declared: str) -> None:
    (tmp_path / "pyproject.toml").write_text(declared, encoding="utf-8")
    with pytest.raises(LineCapError, match=r"the source line cap as .*, and it is a whole number of lines"):
        line_cap(tmp_path, "source")


def test_a_files_lines_are_counted_as_it_holds_them() -> None:
    assert lines_in("one\ntwo\n") == 2
    assert lines_in("one\ntwo") == 2
    assert lines_in("") == 0


WRITTEN_ANYWHERE = [*written(), *python_files(ROOT / "scripts", TESTS)]
"""Every file written rather than generated: the package's, the scripts' and the tests'."""


@pytest.mark.parametrize("path", WRITTEN_ANYWHERE, ids=str)
def test_no_comment_cites_a_requirement(path: pathlib.Path) -> None:
    for number, line in prose(path):
        assert not IDENTIFIER.search(line), f"{path}:{number} cites a requirement; cite it in the commit"


@pytest.mark.parametrize("path", WRITTEN_ANYWHERE, ids=str)
def test_no_comment_argues(path: pathlib.Path) -> None:
    for number, line in prose(path):
        assert not REASONING.match(line), f"{path}:{number} argues; say what it is or does"


def test_comments_and_docstrings_are_read_line_by_line(tmp_path: pathlib.Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text('"""One.\n\nTwo."""\n\nx = 1  # three\n', encoding="utf-8")
    assert prose(sample) == [(5, " three"), (1, "One."), (2, ""), (3, "Two.")]
