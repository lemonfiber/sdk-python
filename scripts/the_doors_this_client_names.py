# Copyright (c) 2026 NightWorksIO
"""The contract page names the reads, and this client holds a path for each.

The contract artefact carries kinds and no endpoints, so every path is written by
hand in `src/lemonfiber/reads.py`. This reads that module and the `## Reading`
block of the contract page against each other in both directions: a read the
page names that this client cannot reach, and a path this client holds that the
page does not name. The spec is a different repository, so the page arrives as
an argument; CI checks it out beside the tree.

    uv run python scripts/the_doors_this_client_names.py --spec ../spec

Reading too little is a failure, not a pass: a block that stopped matching the
shape this parses would otherwise agree with a client holding no paths at all.
"""

import argparse
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMES = pathlib.Path("src/lemonfiber/reads.py")
PAGE = pathlib.Path("20-architecture/contracts/web-api.md")
HEADING = "## Reading"
ENTRY = re.compile(r"GET (/api/[a-z0-9{}/-]+)")
FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
TEMPLATED = re.compile(r"/\{[^}]+\}$")
API = "/api"
NOT_A_READ = {
    "/api/events": "the live stream, which has its own section",
    "/api/actions": "the one door every action is asked for through",
    "/api/jobs": "where work already begun is asked about and released",
    "/api/session": "where a password is exchanged for a session",
}
"""Paths this client holds that the reading block does not name, each with what it is instead."""
FEWEST = 25
"""Below this a reading has found the wrong text rather than a smaller surface."""


def held(root: pathlib.Path) -> tuple[set[str], list[str]]:
    """Return every path this client holds: each `Read` member's, and each module-level path."""
    source = root / NAMES
    if not source.is_file():
        return set(), [f"no read list at {source}"]
    tree = ast.parse(source.read_text(encoding="utf-8"))
    paths: set[str] = set()
    twice: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Read":
            values = [
                statement.value.value
                for statement in node.body
                if isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ]
            for value in values:
                path = f"{API}/{value}"
                if path in paths:
                    twice.append(f"{source}: `{value}` is held twice")
                paths.add(path)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.value.value.startswith(f"{API}/")
        ):
            paths.add(node.value.value)
    return paths, twice


def named(spec: pathlib.Path) -> tuple[set[str], list[str]]:
    """Return every endpoint the reading block names, and anything unreadable about the page."""
    page = spec / PAGE
    if not page.is_file():
        return set(), [f"no contract page at {page} — is --spec a spec checkout?"]
    text = page.read_text(encoding="utf-8")
    if HEADING not in text:
        return set(), [f"{page} has no `{HEADING}` heading"]
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    blocks = FENCE.findall(section)
    if not blocks:
        return set(), [f"{page}: nothing is fenced under `{HEADING}`"]
    return {TEMPLATED.sub("", entry) for entry in ENTRY.findall("\n".join(blocks))}, []


def problems(spec: pathlib.Path, repo: pathlib.Path) -> tuple[list[str], int]:
    """Return everything wrong between the page and this client, and how many reads the page names."""
    paths, found = held(repo)
    entries, unreadable = named(spec)
    found.extend(unreadable)
    for count, what, where in (
        (len(paths), "paths", repo / NAMES),
        (len(entries), f"endpoints under `{HEADING}`", spec / PAGE),
    ):
        if count < FEWEST:
            found.append(
                f"read {count} {what} from {where}, fewer than the {FEWEST} this client has never gone below — "
                "the text has changed shape and this is no longer reading it",
            )
    unreachable = sorted(entries - paths)
    if unreachable:
        found.append(
            f"`{HEADING}` names these and this client holds no path for them: {', '.join(unreachable)}",
        )
    unnamed = sorted(path for path in paths - entries if path not in NOT_A_READ)
    if unnamed:
        found.append(
            f"this client holds these paths and `{HEADING}` does not name them — add them to the page, or say "
            f"here what they are instead of a read: {', '.join(unnamed)}",
        )
    return found, len(entries)


def main() -> int:
    """Compare the page with the client, and say what was compared."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=pathlib.Path, default=pathlib.Path(".spec-canonical"))
    parser.add_argument("--repo", type=pathlib.Path, default=ROOT)
    arguments = parser.parse_args()
    found, entries = problems(arguments.spec, arguments.repo)
    if found:
        for line in found:
            sys.stderr.write(f"::error::{line}\n")
        return 1
    sys.stdout.write(f"this client holds a path for each of the {entries} reads the contract page names\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
