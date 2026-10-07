# Copyright (c) 2026 NightWorksIO
"""A revision's tree as lemonfiber serves it: a gzipped tarball, every path beneath one top directory."""

import io
import json
import pathlib
import tarfile

TOP = "lemonfiber-lemonfiber-d2bf74b"
"""The directory every path in a served tarball sits beneath."""

SINGLE: dict[str, object] = {
    "contract/web-api.contract.json": {"api_version": 1, "kinds": {"pull": {}, "start": {}}},
}
"""A tree holding the contract as one file."""

SPLIT: dict[str, object] = {
    "contract/web-api/index.json": {
        "api_version": 1,
        "kinds": {"pull": "kinds/pull.json", "start": "kinds/start.json"},
        "reads": "reads.json",
    },
    "contract/web-api/kinds/pull.json": {"properties": {"data": {"$ref": "../defs/Code.json"}}},
    "contract/web-api/kinds/start.json": {"type": "object"},
    "contract/web-api/defs/Code.json": {"type": "string"},
    "contract/web-api/reads.json": [],
}
"""A tree holding the contract as a directory."""


def tarball(files: dict[str, object], *, links: tuple[str, ...] = ()) -> bytes:
    """Return a tarball serving these files and their directories, JSON values as JSON and bytes as they are, beside these links."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.addfile(tarfile.TarInfo(f"{TOP}/README.md"), io.BytesIO())
        folders = {parent for path in files for parent in pathlib.PurePosixPath(path).parents if parent.parts}
        for folder in sorted(folders):
            entry = tarfile.TarInfo(f"{TOP}/{folder}")
            entry.type = tarfile.DIRTYPE
            archive.addfile(entry)
        for path, held in files.items():
            body = held if isinstance(held, bytes) else json.dumps(held).encode()
            info = tarfile.TarInfo(f"{TOP}/{path}")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        for path in links:
            link = tarfile.TarInfo(f"{TOP}/{path}")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            archive.addfile(link)
    return buffer.getvalue()
