# Copyright (c) 2026 NightWorksIO
"""Vendor the contract artefact one revision of lemonfiber serves, beside the revision it came from.

The only step in this package that reaches the network. Generation reads the
vendored copy, so a build never does. A revision is a release tag or a full
commit hash; both name exactly one artefact, so the vendored bytes can always be
checked against what that revision served.

    uv run just sync v1.0.0
    uv run just sync d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6
"""

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request
from typing import IO, TYPE_CHECKING, cast, override

if TYPE_CHECKING:
    from collections.abc import Callable
    from http.client import HTTPMessage

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTEFACT = pathlib.Path("contract/web-api.contract.json")
STAMP = pathlib.Path("contract/VERSION")
SERVED = "https://raw.githubusercontent.com/lemonfiber/lemonfiber/{revision}/contract/web-api.contract.json"
TIMEOUT_SECONDS = 30
REVISION = re.compile(r"^(v\d+\.\d+\.\d+|[0-9a-f]{40})$")
"""A release tag, or a full commit hash: an abbreviated one names one artefact today and may not later."""


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
            message = f"the artefact's address redirected to {newurl}, which is not HTTPS"
            raise SyncRefusedError(message)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(revision: str) -> bytes:
    """Return the artefact the revision serves, as the bytes it served."""
    opener = urllib.request.build_opener(HttpsOnly())
    try:
        with opener.open(SERVED.format(revision=revision), timeout=TIMEOUT_SECONDS) as answer:
            return cast("bytes", answer.read())
    except urllib.error.URLError as failed:
        message = f"{revision} serves no artefact: {failed}"
        raise SyncRefusedError(message) from failed


def described(served: bytes, revision: str) -> tuple[int, int]:
    """Return the wire version and the number of kinds an artefact describes."""
    try:
        artefact: object = json.loads(served)
    except ValueError as unreadable:
        message = f"what {revision} serves is not JSON"
        raise SyncRefusedError(message) from unreadable
    if not isinstance(artefact, dict):
        message = f"what {revision} serves is not an artefact"
        raise SyncRefusedError(message)
    fields = cast("dict[str, object]", artefact)
    version = fields.get("api_version")
    kinds = fields.get("kinds")
    if not isinstance(version, int) or not isinstance(kinds, dict):
        message = f"what {revision} serves names no api_version or no kinds"
        raise SyncRefusedError(message)
    return version, len(cast("dict[str, object]", kinds))


def run(arguments: list[str], root: pathlib.Path, take: Callable[[str], bytes] = fetch) -> int:
    """Vendor the artefact the named revision serves into `root`."""
    revision = arguments[0] if arguments else ""
    if not REVISION.fullmatch(revision):
        sys.stderr.write(
            "contract_sync: name a release tag or a full 40-character commit hash, as in `just sync v1.0.0`\n",
        )
        return 1
    try:
        served = take(revision)
        version, kinds = described(served, revision)
    except SyncRefusedError as refused:
        sys.stderr.write(f"contract_sync: refused, and nothing was written: {refused}\n")
        return 1
    (root / ARTEFACT).parent.mkdir(parents=True, exist_ok=True)
    (root / ARTEFACT).write_bytes(served)
    (root / STAMP).write_text(f"{revision}\n", encoding="utf-8")
    sys.stdout.write(
        f"vendored api_version {version}, {kinds} kinds, from {revision}. Now run `just generate`.\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], ROOT))
