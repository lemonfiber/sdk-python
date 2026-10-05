# Copyright (c) 2026 NightWorksIO
"""Compare this tree's public surface with every commit a consumer has vendored.

A consumer takes this package by commit: it copies `src/lemonfiber/` into its own
tree under `_vendor/lemonfiber/` and records the commit beside the copy, in
`_vendor/lemonfiber/REVISION`. Which repositories consume it is the spec's map,
`30-repos/repos.toml`: every Python repository with an edge to `sdk-python`.

Each recorded commit is loaded from this repository's history and compared with
the working tree by griffe. A removed name, a changed signature or a narrowed
type is a breakage and fails the check, naming the consumer it would break. A
consumer that records no commit yet is said so and compared with nothing.

    uv run python scripts/backward_compat.py --spec ../spec
"""

import argparse
import base64
import json
import os
import pathlib
import re
import sys
import tomllib
import urllib.error
import urllib.request
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


def breakages(against: str, repo: pathlib.Path) -> list[str]:
    """Return every way the working tree breaks what the commit `against` offered."""
    old = griffe.load_git(PACKAGE, ref=against, repo=repo, search_paths=["src"])
    new = griffe.load(PACKAGE, search_paths=[str(repo / "src")])
    return [breakage.explain() for breakage in griffe.find_breaking_changes(old, new)]


def run(spec: pathlib.Path, repo: pathlib.Path, fetch: Fetch = github) -> int:
    """Check the tree against every consumer's pin, and say which were compared."""
    names = consumers(spec)
    if not names:
        sys.stdout.write(f"::notice::the spec's map names no consumer of {THIS}, so nothing was compared.\n")
        return 0
    failed = 0
    compared = 0
    for name in names:
        recorded = list(pins(name, fetch))
        if not recorded:
            sys.stdout.write(
                f"::notice::{name} records no vendored commit, so nothing was compared for it.\n",
            )
        for pin in recorded:
            if not COMMIT.match(pin):
                sys.stdout.write(
                    f"::error::{name} records {pin!r} in {RECORD}, which is not a full commit hash.\n",
                )
                failed += 1
                continue
            compared += 1
            found = breakages(pin, repo)
            for explained in found:
                sys.stdout.write(f"::error::breaks {name}, which vendors {pin[:8]}: {explained}\n")
            failed += len(found)
    sys.stdout.write(f"compared against {compared} vendored commit(s) of {len(names)} consumer(s).\n")
    return 1 if failed else 0


def main() -> int:
    """Read the arguments and run the check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=pathlib.Path, default=pathlib.Path(".spec-canonical"))
    parser.add_argument("--repo", type=pathlib.Path, default=ROOT)
    arguments = parser.parse_args()
    return run(arguments.spec, arguments.repo)


if __name__ == "__main__":
    raise SystemExit(main())
