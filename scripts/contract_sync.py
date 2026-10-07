# Copyright (c) 2026 NightWorksIO
"""Vendor the contract one revision of lemonfiber serves, beside the revision it came from.

The only step in this package that reaches the network. Generation reads the
vendored copy, so a build never does. A revision is a release tag or a full
commit hash; both name exactly one contract, so the vendored bytes can always
be checked against what that revision served.

lemonfiber serves the contract as the directory `contract/web-api/`, an index
naming one file per kind, per definition and per list, or, at an older revision,
as the single file `contract/web-api.contract.json`. Whichever the revision
holds is vendored, and the other layout is removed.

    uv run just sync v1.0.0
    uv run just sync d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6
"""

import io
import json
import pathlib
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
from typing import IO, TYPE_CHECKING, NoReturn, cast, override

if TYPE_CHECKING:
    from collections.abc import Callable
    from http.client import HTTPMessage

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTEFACT = pathlib.PurePosixPath("contract/web-api.contract.json")
"""The contract as one file, as a revision older than the directory holds it."""
DIRECTORY = pathlib.PurePosixPath("contract/web-api")
"""The contract as a directory of files, an index naming the rest."""
INDEX = DIRECTORY / "index.json"
STAMP = pathlib.PurePosixPath("contract/VERSION")
SERVED = "https://codeload.github.com/lemonfiber/lemonfiber/tar.gz/{revision}"
"""Where a revision's tree is served, as one gzipped tarball."""
TIMEOUT_SECONDS = 30
REVISION = re.compile(r"^(v\d+\.\d+\.\d+|[0-9a-f]{40})$")
"""A release tag, or a full commit hash: an abbreviated one names one contract today and may not later."""
LISTS = ("key_callable", "reads", "refusals")
"""The lists the index names a file for, beside the kinds."""

type Contract = dict[pathlib.PurePosixPath, bytes]
"""A contract's files by their path in the repository: the one file, or every file of the directory."""


class SyncRefusedError(Exception):
    """The revision cannot be vendored, and nothing was written."""


class HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to another HTTPS address."""

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Refuse a redirect that would leave HTTPS."""
        if not newurl.startswith("https://"):
            message = f"the contract's address redirected to {newurl}, which is not HTTPS"
            raise SyncRefusedError(message)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def refuse(message: str) -> NoReturn:
    """Refuse the revision, saying why."""
    raise SyncRefusedError(message)


def fetch(revision: str) -> bytes:
    """Return the tarball of the revision's tree, as the bytes it served."""
    opener = urllib.request.build_opener(HttpsOnly())
    try:
        with opener.open(SERVED.format(revision=revision), timeout=TIMEOUT_SECONDS) as answer:
            return cast("bytes", answer.read())
    except urllib.error.URLError as failed:
        refuse(f"{revision} serves no tree: {failed}")


def unpacked(tarball: bytes, revision: str) -> Contract:
    """Return the contract a revision's tarball holds: the directory where it holds an index, the one file otherwise."""
    found: Contract = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
            for member in archive:
                parts = pathlib.PurePosixPath(member.name).parts[1:]
                path = pathlib.PurePosixPath(*parts)
                if (path != ARTEFACT and DIRECTORY not in path.parents) or member.isdir():
                    continue
                held = archive.extractfile(member) if member.isfile() and ".." not in parts else None
                if held is None:
                    refuse(
                        f"what {revision} serves holds {member.name}, which is not a plain file of the contract",
                    )
                found[path] = held.read()
    except (tarfile.TarError, OSError, EOFError) as unreadable:
        message = f"what {revision} serves is not a gzipped tarball: {unreadable}"
        raise SyncRefusedError(message) from unreadable
    if INDEX in found:
        return {path: body for path, body in found.items() if path != ARTEFACT}
    if ARTEFACT in found:
        return {ARTEFACT: found[ARTEFACT]}
    refuse(f"what {revision} serves holds neither {INDEX} nor {ARTEFACT}")


def decoded(contract: Contract, path: pathlib.PurePosixPath, revision: str) -> object:
    """Return the JSON one file of a contract holds, refusing a file that is not JSON."""
    try:
        return cast("object", json.loads(contract[path]))
    except ValueError as unreadable:
        message = f"{path} at {revision} is not JSON"
        raise SyncRefusedError(message) from unreadable


def described(contract: Contract, revision: str) -> tuple[int, int]:
    """Return the wire version and the number of kinds a contract describes, refusing one that is not whole."""
    for path in sorted(contract):
        decoded(contract, path, revision)
    head = INDEX if INDEX in contract else ARTEFACT
    fields = decoded(contract, head, revision)
    if not isinstance(fields, dict):
        refuse(f"{head} at {revision} is not an object")
    read = cast("dict[str, object]", fields)
    version = read.get("api_version")
    kinds = read.get("kinds")
    if not isinstance(version, int) or not isinstance(kinds, dict):
        refuse(f"{head} at {revision} names no api_version or no kinds")
    listed = cast("dict[str, object]", kinds)
    if head == INDEX:
        for file in [*listed.values(), *(read[one] for one in LISTS if one in read)]:
            if not isinstance(file, str) or DIRECTORY / file not in contract:
                refuse(f"{INDEX} at {revision} names {json.dumps(file)}, which the revision does not hold")
    return version, len(listed)


def vendor(root: pathlib.Path, contract: Contract, revision: str) -> None:
    """Replace whichever contract is vendored under `root` with this one, and record the revision."""
    shutil.rmtree(root / DIRECTORY, ignore_errors=True)
    (root / ARTEFACT).unlink(missing_ok=True)
    for path, body in sorted(contract.items()):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(body)
    (root / STAMP).write_text(f"{revision}\n", encoding="utf-8")


def run(arguments: list[str], root: pathlib.Path, take: Callable[[str], bytes] = fetch) -> int:
    """Vendor the contract the named revision serves into `root`."""
    revision = arguments[0] if arguments else ""
    if not REVISION.fullmatch(revision):
        sys.stderr.write(
            "contract_sync: name a release tag or a full 40-character commit hash, as in `just sync v1.0.0`\n",
        )
        return 1
    try:
        contract = unpacked(take(revision), revision)
        version, kinds = described(contract, revision)
    except SyncRefusedError as refused:
        sys.stderr.write(f"contract_sync: refused, and nothing was written: {refused}\n")
        return 1
    vendor(root, contract, revision)
    layout = DIRECTORY if INDEX in contract else ARTEFACT
    sys.stdout.write(
        f"vendored api_version {version}, {kinds} kinds, from {revision} as {layout}. Now run `just generate`.\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], ROOT))
