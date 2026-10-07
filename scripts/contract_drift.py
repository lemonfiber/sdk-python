# Copyright (c) 2026 NightWorksIO
"""Compare the vendored contract with the one a revision of lemonfiber serves.

A copy in the directory layout is compared file by file with a revision that
serves the directory: the same set of files, each holding the same JSON. A copy
of the single file is compared with a revision that serves the single file, as
the JSON it holds. A copy in one layout and a revision serving the other differ.

`contract-drift` runs this with `--gate` on every pull request, and on a
difference it fails with the files that differ and the two commands that take
the contract. `contract-bump` runs it without, to learn whether there is a
contract to take.

    uv run python -m scripts.contract_drift --gate <revision>

Exits 0 when the copy is what the revision serves, 1 when it differs, and 2
when the revision serves no contract this can read.
"""

import json
import os
import pathlib
import sys
from typing import TYPE_CHECKING, cast

from scripts.contract_sync import (
    ARTEFACT,
    DIRECTORY,
    INDEX,
    REVISION,
    ROOT,
    STAMP,
    Contract,
    SyncRefusedError,
    fetch,
    unpacked,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CURRENT = 0
"""The exit code when the copy is what the revision serves."""

BEHIND = 1
"""The exit code when the copy differs from what the revision serves."""

REFUSED = 2
"""The exit code when the revision serves no contract this can read, or none was named."""

GATE = "--gate"
"""The argument that asks for the verdict a pull request reads, with the remedy."""


def vendored(root: pathlib.Path) -> Contract:
    """Return the contract vendored under `root`, in whichever layout it is held."""
    directory = root / DIRECTORY
    if directory.is_dir():
        return {
            DIRECTORY / path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }
    single = root / ARTEFACT
    return {ARTEFACT: single.read_bytes()} if single.is_file() else {}


def layout(contract: Contract) -> str:
    """Name the layout a contract is held in."""
    if any(DIRECTORY in path.parents for path in contract):
        return f"the directory {DIRECTORY}/"
    if ARTEFACT in contract:
        return f"the single file {ARTEFACT}"
    return "nothing"


def decoded(body: bytes) -> object:
    """Return the JSON a file holds, or its bytes where it holds none, so two such files compare as bytes."""
    try:
        return cast("object", json.loads(body))
    except ValueError:
        return body


def differences(ours: Contract, theirs: Contract) -> list[str]:
    """Return a line naming each file that differs between the vendored contract and the served one."""
    if layout(ours) != layout(theirs):
        return [f"lemonfiber serves {layout(theirs)}, and what is vendored here is {layout(ours)}"]
    found: list[str] = []
    for path in sorted(ours.keys() | theirs.keys()):
        if path not in theirs:
            found.append(f"{path}: vendored here, and not served")
        elif path not in ours:
            found.append(f"{path}: served, and not vendored here")
        elif decoded(ours[path]) != decoded(theirs[path]):
            found.append(f"{path}: holds something else")
    return found


def described(contract: Contract) -> tuple[object, set[str]]:
    """Return the wire version and the kinds a contract names, as far as it names them."""
    read = decoded(contract.get(INDEX if INDEX in contract else ARTEFACT, b""))
    fields = cast("dict[str, object]", read) if isinstance(read, dict) else {}
    kinds = fields.get("kinds")
    named = set(cast("dict[str, object]", kinds)) if isinstance(kinds, dict) else set[str]()
    return fields.get("api_version"), named


def verdict(
    root: pathlib.Path,
    revision: str,
    ours: Contract,
    theirs: Contract,
    found: list[str],
) -> list[str]:
    """Return what a pull request reads of the comparison: the verdict, and on a difference the remedy."""
    stamp_path = root / STAMP
    stamp = stamp_path.read_text(encoding="utf-8").strip() if stamp_path.is_file() else "no revision"
    if not found:
        return [
            "## The vendored contract is current",
            "",
            f"It matches the one lemonfiber `{revision}` describes, vendored at `{stamp}`.",
        ]
    version, kinds = described(ours)
    served_version, served_kinds = described(theirs)
    lines = [
        "## The vendored contract is behind",
        "",
        "**This check gates.** It fails every pull request against `main` until",
        "the contract in `contract/` is the one lemonfiber serves. You did not",
        "break this and you do not need to understand the kinds below to fix it.",
        "",
        f"- vendored at `{stamp}`: api_version {version}, {len(kinds)} kinds",
        f"- served at lemonfiber `{revision}`: api_version {served_version}, {len(served_kinds)} kinds",
    ]
    if served_kinds - kinds:
        lines.append(f"- described by the server and not here: {', '.join(sorted(served_kinds - kinds))}")
    if kinds - served_kinds:
        lines.append(f"- described here and not by the server: {', '.join(sorted(kinds - served_kinds))}")
    lines.extend(["", "### What differs", "", *(f"- {line}" for line in found)])
    lines.extend(
        [
            "",
            "### Run this",
            "",
            "```sh",
            f"uv run just sync {revision}",
            "uv run just generate",
            "```",
            "",
            "Then commit `contract/` and `src/lemonfiber/_generated`. Where that regenerates more",
            "than types — a kind arriving is a change to this package's surface — land",
            "the sync on its own first; that is the change this gate is asking for.",
        ],
    )
    return lines


def run(arguments: list[str], root: pathlib.Path, take: Callable[[str], bytes] = fetch) -> int:
    """Compare the contract vendored under `root` with the one the named revision serves."""
    gate = arguments[:1] == [GATE]
    named = arguments[1:] if gate else arguments
    revision = named[0] if len(named) == 1 else ""
    if not REVISION.fullmatch(revision):
        sys.stderr.write(
            "contract_drift: name a release tag or a full 40-character commit hash, and nothing else\n",
        )
        return REFUSED
    try:
        theirs = unpacked(take(revision), revision)
    except SyncRefusedError as refused:
        sys.stderr.write(f"::error::{refused}\n")
        return REFUSED
    ours = vendored(root)
    found = differences(ours, theirs)
    if not gate:
        said = found or [f"the vendored contract is what lemonfiber {revision} serves"]
        sys.stdout.write("".join(f"{line}\n" for line in said))
        return BEHIND if found else CURRENT
    lines = verdict(root, revision, ours, theirs, found)
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        pathlib.Path(summary).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    if not found:
        return CURRENT
    sys.stdout.write(
        f"::error::the vendored contract is behind lemonfiber {revision} — run `uv run just sync {revision}` "
        "then `uv run just generate`, and commit contract/ and src/lemonfiber/_generated\n",
    )
    return BEHIND


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], ROOT))
