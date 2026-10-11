# Copyright (c) 2026 NightWorksIO
"""Compare the vendored contract with the one a revision of lemonfiber serves.

A copy in the directory layout is compared file by file with a revision that
serves the directory: the same set of files, each holding the same JSON. A copy
of the single file is compared with a revision that serves the single file, as
the JSON it holds. A copy in one layout and a revision serving the other differ.

`contract-bump` runs this to learn whether there is a contract to take.
`contract-drift` asks the same of every pull request through spec's shared
`upstream-drift`.

    uv run python -m scripts.contract_drift <revision>

Exits 0 when the copy is what the revision serves, 1 when it differs, and 2
when the revision serves no contract this can read.
"""

import json
import sys
from typing import TYPE_CHECKING, cast

from scripts.contract_sync import (
    ARTEFACT,
    DIRECTORY,
    REVISION,
    ROOT,
    Contract,
    SyncRefusedError,
    fetch,
    unpacked,
)

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

CURRENT = 0
"""The exit code when the copy is what the revision serves."""

BEHIND = 1
"""The exit code when the copy differs from what the revision serves."""

REFUSED = 2
"""The exit code when the revision serves no contract this can read, or none was named."""


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


def run(arguments: list[str], root: pathlib.Path, take: Callable[[str], bytes] = fetch) -> int:
    """Compare the contract vendored under `root` with the one the named revision serves."""
    revision = arguments[0] if len(arguments) == 1 else ""
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
    found = differences(vendored(root), theirs)
    said = found or [f"the vendored contract is what lemonfiber {revision} serves"]
    sys.stdout.write("".join(f"{line}\n" for line in said))
    return BEHIND if found else CURRENT


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], ROOT))
