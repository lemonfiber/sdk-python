# Copyright (c) 2026 NightWorksIO
"""Compare this tree's public surface with every commit a consumer has vendored.

A consumer takes this package by commit: it copies `src/lemonfiber/` into its own
tree under `_vendor/lemonfiber/` and records the commit beside the copy, in
`_vendor/lemonfiber/REVISION`. Which repositories consume it is the spec's map,
`30-repos/repos.toml`: every Python repository with an edge to `sdk-python`.

Each recorded commit is loaded from this repository's history and compared with
the working tree by griffe, and every public value by this check, as griffe
compares none. A removed name, a changed signature, a narrowed type or a
changed value is a breakage and fails the check, naming the consumer it would
break. A default or a value written another way, a constant moved to another
module or a number become the enum member equal to it, is the same value and no
breakage. A consumer that records no commit yet is said so and compared with
nothing.

A change that breaks the surface on purpose lists each break it accepts in
`pyproject.toml`, under `[tool.lemonfiber.backward-compatibility]`, by the
symbol griffe names and the kind of break, with why. A listed break passes for
that symbol and that kind alone, and only where a commit since the consumer's
pin is marked breaking, which is what puts it in the changelog. An entry that
no longer matches a break is said so, to be removed.

    uv run python scripts/backward_compat.py --spec ../spec
"""

import argparse
import ast
import base64
import json
import os
import pathlib
import pkgutil
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import griffe

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
THIS = "sdk-python"
OWNER = "lemonfiber"
PACKAGE = "lemonfiber"
RECORD = "_vendor/lemonfiber/REVISION"
"""Where a consumer records the commit it vendored, relative to wherever it vendors."""
COMMIT = re.compile(r"^[0-9a-f]{40}$")
TIMEOUT_SECONDS = 30
VALUE_CHANGED = "attribute-changed-value"
"""The kind of break a public value that is no longer the one it was is accepted as."""

BREAKING = re.compile(r"\A\w+(\([^)\n]*\))?!:|^BREAKING[ -]CHANGE:", re.MULTILINE)
"""A commit message git-cliff files under breaking changes: `!` after its type, or a breaking-change footer."""

type Table = dict[str, object]
"""A TOML table, as `tomllib` reads one."""

type Loaded = griffe.Object | griffe.Alias
"""A package as griffe loads it."""

type Fetch = Callable[[str], object]
"""Return the decoded JSON a GitHub API path answers with, or None where there is nothing there."""


def consumers(spec: pathlib.Path) -> list[str]:
    """Return every Python repository the spec's map draws an edge from to this one."""
    repos = tomllib.loads((spec / "30-repos" / "repos.toml").read_text(encoding="utf-8"))
    python = {repo["name"] for repo in repos.get("repo", []) if repo.get("lang") == "Python"}
    return sorted({edge["from"] for edge in repos.get("edge", []) if edge.get("to") == THIS} & python)


def github(path: str) -> object:
    """Fetch a GitHub API path, answering None for a repository that is missing or empty."""
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Accept": "application/vnd.github+json"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.build_opener().open(request, timeout=TIMEOUT_SECONDS) as answer:
            return cast("object", json.loads(answer.read()))
    except urllib.error.HTTPError as refused:
        if refused.code in {404, 409}:
            return None
        raise


def pins(repo: str, fetch: Fetch) -> Iterator[str]:
    """Yield every commit a consumer records vendoring, read from its default branch."""
    tree = fetch(f"/repos/{OWNER}/{repo}/git/trees/HEAD?recursive=1")
    if not isinstance(tree, dict):
        return
    entries = cast("list[dict[str, str]]", cast("dict[str, object]", tree).get("tree", []))
    for entry in entries:
        path = entry.get("path", "")
        if path == RECORD or path.endswith(f"/{RECORD}"):
            blob = fetch(f"/repos/{OWNER}/{repo}/contents/{path}")
            content = cast("dict[str, str]", blob).get("content", "") if isinstance(blob, dict) else ""
            yield bytes_of(content).decode("ascii", errors="replace").strip()


def bytes_of(content: str) -> bytes:
    """Decode the base64 GitHub returns a file's content in."""
    return base64.b64decode(content)


class AcceptedRefusedError(ValueError):
    """The list of accepted breaks is not one this check can read."""


@dataclass(frozen=True)
class Break:
    """One way the tree breaks a consumer's pin: the symbol, the kind of break, and griffe's words for it."""

    symbol: str
    kind: str
    explained: str

    def entry(self) -> str:
        """Return the entry that would accept this break, as `pyproject.toml` lists one."""
        return f'{{ symbol = "{self.symbol}", kind = "{self.kind}", reason = "..." }}'


def accepted(repo: pathlib.Path) -> set[tuple[str, str]]:
    """Return the symbol and kind of every break `pyproject.toml` accepts, refusing an entry without its reason."""
    found: object = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    for key in ("tool", "lemonfiber", "backward-compatibility", "accepted"):
        found = cast("Table", found).get(key, {}) if isinstance(found, dict) else {}
    listed: set[tuple[str, str]] = set()
    for entry in cast("list[object]", found) if isinstance(found, list) else []:
        fields = cast("Table", entry) if isinstance(entry, dict) else {}
        if set(fields) != {"symbol", "kind", "reason"} or not all(
            isinstance(value, str) and value for value in fields.values()
        ):
            msg = f"An accepted break names its symbol, its kind and its reason, and nothing else; {entry!r} does not."
            raise AcceptedRefusedError(msg)
        listed.add((cast("str", fields["symbol"]), cast("str", fields["kind"])))
    return listed


def marked_breaking(repo: pathlib.Path, since: str) -> bool:
    """Tell whether a commit after `since` is marked breaking, so the changelog names the break."""
    git = shutil.which("git")
    if git is None:
        msg = "git is not on the path, and the commits since a consumer's pin are read with it."
        raise FileNotFoundError(msg)
    log = subprocess.run(
        [git, "-C", str(repo), "log", "--format=%B%x00", f"{since}..HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return any(BREAKING.search(message.strip()) for message in log.split("\0"))


def breakages(against: str, repo: pathlib.Path) -> list[Break]:
    """Return every way the working tree breaks what the commit `against` offered."""
    old = griffe.load_git(PACKAGE, ref=against, repo=repo, search_paths=["src"])
    new = griffe.load(PACKAGE, search_paths=[str(repo / "src")])
    return compared(old, new)


def compared(old: Loaded, new: Loaded) -> list[Break]:
    """Return every way `new` breaks what `old` offered, keeping a default or value that is the value it was."""
    found = [
        break_of(breakage)
        for breakage in griffe.find_breaking_changes(old, new)
        if not same_default(breakage, old, new)
    ]
    found.extend(
        value_break(before, after)
        for before, after in changed_values(old, new, set())
        if not same(before.value, old, after.value, new)
    )
    return found


def break_of(breakage: griffe.Breakage) -> Break:
    """Return a break as an entry accepts it: the object griffe names, with the parameter where it is to one."""
    symbol = breakage.obj.path
    for value in (breakage.old_value, breakage.new_value):
        if isinstance(value, griffe.Parameter):
            symbol = f"{symbol}({value.name})"
            break
    return Break(symbol, breakage.kind.name.lower().replace("_", "-"), breakage.explain())


def value_break(before: griffe.Attribute, after: griffe.Attribute) -> Break:
    """Return a public value that is no longer the one it was as a break, in the words griffe gives the others."""
    where = f"{after.relative_package_filepath}:{after.lineno}"
    said = f"{where}: {after.path}: Attribute value was changed: {before.value} -> {after.value}"
    return Break(after.path, VALUE_CHANGED, said)


def changed_values(
    old: Loaded,
    new: Loaded,
    seen: set[str],
) -> Iterator[tuple[griffe.Attribute, griffe.Attribute]]:
    """Yield each public attribute of `old` that `new` holds under its name, written another way.

    Modules and classes are walked as griffe walks them for the other breaks: a
    name that is not public is passed over, an alias is followed to its target,
    and one whose target cannot be found is passed over.
    """
    for name, was in old.all_members.items():
        if not was.is_public or name not in new.all_members:
            continue
        try:
            before = target(was)
            after = target(new.all_members[name])
        except griffe.AliasResolutionError, griffe.CyclicAliasError:
            continue
        if before.path in seen:
            continue
        seen.add(before.path)
        if isinstance(before, griffe.Attribute) and isinstance(after, griffe.Attribute):
            if str(before.value) != str(after.value):
                yield before, after
        elif before.kind is after.kind and (before.is_module or before.is_class):
            yield from changed_values(before, after, seen)


def target(member: Loaded) -> Loaded:
    """Return what a member is: itself, or what an alias of it finally points to."""
    return cast("Loaded", member.final_target) if isinstance(member, griffe.Alias) else member


def same_default(breakage: griffe.Breakage, old: Loaded, new: Loaded) -> bool:
    """Tell whether a changed default is the default it was, written another way."""
    if breakage.kind is not griffe.BreakageKind.PARAMETER_CHANGED_DEFAULT:
        return False
    before = cast("griffe.Parameter", breakage.old_value).default
    after = cast("griffe.Parameter", breakage.new_value).default
    return same(before, old, after, new)


def same(before: str | griffe.Expr | None, old: Loaded, after: str | griffe.Expr | None, new: Loaded) -> bool:
    """Tell whether a value written in `old` and one written in `new` are the same value."""
    try:
        was = value_of(before, old)
        now = value_of(after, new)
    except ValueError, SyntaxError, LookupError, ImportError, AttributeError:
        return False
    return isinstance(now, type(was)) and now == was


def value_of(written: str | griffe.Expr | None, package: Loaded) -> object:
    """Return what a default or value stands for.

    A literal is read as written. A name in `package` is followed to what it is
    assigned, and any other name is imported. Anything else raises.
    """
    if not isinstance(written, griffe.Expr):
        return ast.literal_eval(written or "")
    path = written.canonical_path
    inside = f"{package.path}."
    if path.startswith(inside):
        member = package[path.removeprefix(inside)]
        return value_of(cast("str | griffe.Expr | None", member.value), package)
    return cast("object", pkgutil.resolve_name(path))


def run(spec: pathlib.Path, repo: pathlib.Path, fetch: Fetch = github) -> int:
    """Check the tree against every consumer's pin, and say which were compared."""
    names = consumers(spec)
    if not names:
        sys.stdout.write(f"::notice::the spec's map names no consumer of {THIS}, so nothing was compared.\n")
        return 0
    try:
        listed = accepted(repo)
    except AcceptedRefusedError as refused:
        sys.stdout.write(f"::error::{refused}\n")
        return 1
    judge = Judge(repo, listed)
    failed = 0
    compared = 0
    for name in names:
        recorded = list(pins(name, fetch))
        if not recorded:
            sys.stdout.write(
                f"::notice::{name} records no vendored commit, so nothing was compared for it.\n",
            )
        for pin in recorded:
            if not COMMIT.fullmatch(pin):
                sys.stdout.write(
                    f"::error::{name} records {pin!r} in {RECORD}, which is not a full commit hash.\n",
                )
                failed += 1
                continue
            compared += 1
            failed += judge.judged(name, pin, breakages(pin, repo))
    for symbol, kind in sorted(listed - judge.used):
        sys.stdout.write(
            f"::warning::{kind} of {symbol} is accepted and breaks no consumer's pin; remove it.\n",
        )
    sys.stdout.write(f"compared against {compared} vendored commit(s) of {len(names)} consumer(s).\n")
    return 1 if failed else 0


class Judge:
    """Says each break of a consumer's pin, accepted or not, keeping which accepted breaks were met."""

    def __init__(self, repo: pathlib.Path, listed: set[tuple[str, str]]) -> None:
        """Hold the tree's history and the breaks it accepts, none of them met yet."""
        self._repo = repo
        self._listed = listed
        self.used: set[tuple[str, str]] = set()

    def judged(self, name: str, pin: str, found: list[Break]) -> int:
        """Say each break of one consumer's pin, and return how many fail the check."""
        failed = 0
        accepting = [one for one in found if (one.symbol, one.kind) in self._listed]
        for one in found:
            if one in accepting:
                sys.stdout.write(f"::notice::accepted, breaking {name} at {pin[:8]}: {one.explained}\n")
                self.used.add((one.symbol, one.kind))
            else:
                sys.stdout.write(
                    f"::error::breaks {name}, which vendors {pin[:8]}: {one.explained}. If it is meant, "
                    f"accept it under [tool.lemonfiber.backward-compatibility] in pyproject.toml: {one.entry()}\n",
                )
                failed += 1
        if accepting and not marked_breaking(self._repo, pin):
            sys.stdout.write(
                f"::error::breaks of {name}'s pin are accepted, and no commit since {pin[:8]} is marked "
                "breaking, with `!` after its type or a BREAKING CHANGE footer, so the changelog would "
                "not name them.\n",
            )
            failed += 1
        return failed


def main() -> int:
    """Read the arguments and run the check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=pathlib.Path, default=pathlib.Path(".spec-canonical"))
    parser.add_argument("--repo", type=pathlib.Path, default=ROOT)
    arguments = parser.parse_args()
    return run(arguments.spec, arguments.repo)


if __name__ == "__main__":
    raise SystemExit(main())
