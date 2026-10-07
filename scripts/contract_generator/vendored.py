# Copyright (c) 2026 NightWorksIO
"""The vendored contract, read whole from whichever layout `contract/` holds it in.

The directory `contract/web-api/` is an index naming a file for each kind and
each list, and a file for each definition under `defs/`, named for it. A `$ref`
is a path resolved against the file it sits in. The directory is read into the
artefact the single file `contract/web-api.contract.json` holds: each kind
carrying under `$defs` every definition it reaches, and every reference spelled
`#/$defs/<Name>`. The same contract in either layout is the same artefact, so it
generates the same files.
"""

import json
import pathlib
import posixpath
from dataclasses import dataclass, field

from scripts.contract_generator.artefact import INLINE, UNKNOWN, array_of, object_of
from scripts.contract_generator.refused import ArtefactRefusedError, refuse
from scripts.contract_sync import ARTEFACT, DIRECTORY, INDEX, LISTS, STAMP

DEFINITIONS = DIRECTORY / "defs"
"""Where the directory holds its definitions, one file each."""

SUFFIX = ".json"
"""What every file of the directory ends in."""


def document(root: pathlib.Path, path: pathlib.PurePosixPath) -> object:
    """Return the JSON one vendored file holds, refusing a file that cannot be read as JSON."""
    try:
        return json.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        message = f"{path} could not be read: {unreadable}"
        raise ArtefactRefusedError(message) from unreadable


@dataclass(frozen=True)
class Definition:
    """One definition's file, read: its schema with every reference spelled inline, and what it refers to."""

    path: pathlib.PurePosixPath
    schema: object
    dialect: object
    """The `$schema` the file names, which is the file's and not part of the definition."""
    refers: frozenset[str]


@dataclass
class Directory:
    """The contract as the directory `contract/web-api/` holds it, read into one artefact."""

    root: pathlib.Path
    read: dict[str, Definition] = field(default_factory=dict[str, Definition])
    """Each definition already read, by its name."""

    def artefact(self) -> dict[str, object]:
        """Return the artefact the directory describes, refusing a reference that resolves to no definition."""
        index = object_of(document(self.root, INDEX))
        if index is None:
            refuse(f"{INDEX} is not an object")
        kinds = object_of(index.get("kinds"))
        if kinds is None:
            refuse(
                f"{INDEX} names its kinds as {json.dumps(index.get('kinds'))}, and they are an object of files",
            )
        whole: dict[str, object] = {"api_version": index.get("api_version")}
        for listed in LISTS:
            if listed in index:
                whole[listed] = document(self.root, self.named(index[listed]))
        whole["kinds"] = {kind: self.kind(self.named(file)) for kind, file in kinds.items()}
        return whole

    @staticmethod
    def named(file: object) -> pathlib.PurePosixPath:
        """Return the path of a file the index names, refusing a name that leaves the directory."""
        relative = pathlib.PurePosixPath(file) if isinstance(file, str) else None
        if relative is None or relative.is_absolute() or ".." in relative.parts or not relative.parts:
            refuse(f"{INDEX} names {json.dumps(file)}, which is not a file in {DIRECTORY}/")
        return DIRECTORY / relative

    def kind(self, path: pathlib.PurePosixPath) -> object:
        """Return one kind's schema, carrying every definition it reaches."""
        schema = document(self.root, path)
        node = object_of(schema)
        if node is None:
            return schema
        if "$defs" in node:
            refuse(
                f"{path} holds $defs, and in {DIRECTORY}/ each definition is a file of its own under defs/",
            )
        refers: set[str] = set()
        written = self.spelled(node, path, refers)
        reached: dict[str, object] = {}
        waiting = sorted(refers)
        while waiting:
            name = waiting.pop()
            if name in reached:
                continue
            definition = self.definition(name)
            if definition.dialect != node.get("$schema"):
                refuse(
                    f"{definition.path} is written in {json.dumps(definition.dialect)}, and {path}, "
                    f"which reaches it, in {json.dumps(node.get('$schema'))}",
                )
            reached[name] = definition.schema
            waiting.extend(sorted(definition.refers))
        if reached:
            written["$defs"] = reached
        return written

    def definition(self, name: str) -> Definition:
        """Return one definition, read from its file the first time it is reached."""
        held = self.read.get(name)
        if held is not None:
            return held
        path = DEFINITIONS / f"{name}{SUFFIX}"
        node = object_of(document(self.root, path))
        if node is None:
            refuse(f"{path} is not an object, and a definition is a schema")
        refers: set[str] = set()
        schema = self.spelled({key: value for key, value in node.items() if key != "$schema"}, path, refers)
        self.read[name] = Definition(path, schema, node.get("$schema"), frozenset(refers))
        return self.read[name]

    def spelled(
        self,
        node: dict[str, object],
        path: pathlib.PurePosixPath,
        refers: set[str],
    ) -> dict[str, object]:
        """Return a schema with every reference in it spelled inline, adding each name it refers to to `refers`."""
        return {
            key: self.within(value, path, refers) if key != "$ref" else self.inline(value, path, refers)
            for key, value in node.items()
        }

    def within(self, value: object, path: pathlib.PurePosixPath, refers: set[str]) -> object:
        """Return a value inside a schema with every reference in it spelled inline."""
        items = array_of(value)
        if items is not None:
            return [self.within(item, path, refers) for item in items]
        node = object_of(value)
        return value if node is None else self.spelled(node, path, refers)

    def inline(self, reference: object, path: pathlib.PurePosixPath, refers: set[str]) -> str:
        """Return a reference made in the file at `path` as the single file spells it, refusing one to no definition."""
        target = None
        if isinstance(reference, str):
            target = pathlib.PurePosixPath(posixpath.normpath(posixpath.join(str(path.parent), reference)))
        if target is None or target.parent != DEFINITIONS or target.suffix != SUFFIX:
            refuse(
                f"{path} refers to {json.dumps(reference)}, which is not a definition's file in {DEFINITIONS}/",
            )
        if not (self.root / target).is_file():
            refuse(f"{path} refers to {json.dumps(reference)}, and the vendored copy holds no {target}")
        refers.add(target.stem)
        return f"{INLINE}{target.stem}"


def read_artefact(root: pathlib.Path) -> tuple[dict[str, object], str]:
    """Return the vendored artefact, from whichever layout `contract/` holds, and the revision it was taken from."""
    stamp_path = root / STAMP
    stamp = stamp_path.read_text(encoding="utf-8").strip() if stamp_path.is_file() else UNKNOWN
    if (root / DIRECTORY).is_dir():
        if (root / ARTEFACT).exists():
            refuse(
                f"{ARTEFACT} and {DIRECTORY}/ are both vendored, and generating from one would leave the other unread",
            )
        return Directory(root).artefact(), stamp
    read = object_of(document(root, ARTEFACT))
    if read is None:
        refuse(f"{ARTEFACT} is not an object")
    return read, stamp
