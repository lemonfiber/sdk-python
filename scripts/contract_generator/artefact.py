# Copyright (c) 2026 NightWorksIO
"""The vendored artefact, read and held to everything the generator relies on."""

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from scripts.contract_generator.refused import refuse
from scripts.contract_generator.spelling import pascal
from scripts.contract_sync import REVISION, STAMP

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

UNKNOWN = "an unknown revision"
"""What the generated files say they came from when `contract/VERSION` is missing."""

SPOKEN = 1
"""The wire version this package implements."""

DIALECT = "$schema"
"""The keyword a schema names the dialect it is written in with."""

INLINE = "#/$defs/"
"""How the artefact spells a reference to a definition beside it, before the definition's name."""

ANNOTATIONS = frozenset({"description", "title", "default", "examples", "$comment"})
"""Keywords that describe a schema without constraining what it matches."""

KIND = re.compile(r"^[a-z][a-z0-9_-]*$")
"""A kind, as the core spells one: `front-door`."""

CODE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
"""A problem code, as the core spells one: `ADMIT-4`."""

SCREAMING_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
"""A registry name, as the core spells one: `NOT_ADMITTED`."""

ACTION = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
"""An action's name, as `POST /api/actions/<action>` spells one: `downloads-pause`."""

CALLABLE_FLAGS = ("disturbs", "rehearsal", "idempotent")
"""What the contract says of an action a key may call as true or false, in that order."""

CALLABLE_FIELDS = ("action", *CALLABLE_FLAGS, "moved")
"""Everything the contract says of an action a key may call, in that order. Anything else is refused, not dropped."""

READ_FIELDS = ("path", "parameters", "kinds", "file")
"""Everything the contract says of a read, in that order. Anything else is refused, not dropped."""

PARAMETER_FIELDS = ("name", "repeatable")
"""Everything the contract says of a read's query parameter. Anything else is refused, not dropped."""

READ_PATH = re.compile(r"^/api/[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:/\{[a-z][a-z_]*\})?$")
"""A read's path, as the core spells one: `/api/front-door`, or `/api/bundle/{name}` with its one placeholder."""

PARAMETER = re.compile(r"^[a-z][a-z0-9_]*$")
"""A query parameter's name, as the core spells one: `most`."""

REFUSAL_STATUSES = range(400, 600)
"""The statuses a refusal may be answered with: the request's fault or the machine's."""


def array_of(node: object) -> list[object] | None:
    """Return a decoded JSON value as the array it is, or None where it is not one."""
    return cast("list[object]", node) if isinstance(node, list) else None


def object_of(node: object) -> dict[str, object] | None:
    """Return a decoded JSON value as the object it is, whose keys JSON makes strings, or None."""
    return cast("dict[str, object]", node) if isinstance(node, dict) else None


def as_list(node: object) -> list[object]:
    """Read a JSON array a validated schema holds as the list it decodes to."""
    return cast("list[object]", node)


def as_map(node: object) -> dict[str, object]:
    """Read a JSON object a validated schema holds as the dict it decodes to."""
    return cast("dict[str, object]", node)


def as_maps(node: object) -> dict[str, dict[str, object]]:
    """Read a JSON object of JSON objects the artefact holds as the dicts it decodes to."""
    return cast("dict[str, dict[str, object]]", node)


def ambiguous(node: object, path: str) -> Iterator[str]:
    """Yield every reference in the artefact with a constraint sitting beside it.

    Draft-07 readers discard whatever accompanies a `$ref` and 2020-12 readers
    apply both, so such a shape means two different things to two readers.
    """
    items = array_of(node)
    if items is not None:
        for at, item in enumerate(items):
            yield from ambiguous(item, f"{path}/{at}")
        return
    named = object_of(node)
    if named is None:
        return
    constraints = sorted(key for key in named if key != "$ref" and key not in ANNOTATIONS)
    if "$ref" in named and constraints:
        yield f"{path} ({', '.join(constraints)})"
    for key, value in named.items():
        yield from ambiguous(value, f"{path}/{key}")


def malformed_refusal(code: str, entry: object) -> Iterator[str]:
    """Yield everything wrong with one listed refusal, as lines naming its code."""
    if not CODE.fullmatch(code):
        yield f"{json.dumps(code)}: not a code, which is a prefix and a number"
    listed = object_of(entry)
    if listed is None:
        yield f"{code}: not an object"
        return
    name = listed.get("name")
    status = listed.get("status")
    description = listed.get("description")
    if not isinstance(name, str) or not SCREAMING_SNAKE.fullmatch(name):
        yield f"{code}: name {json.dumps(name)} is not SCREAMING_SNAKE"
    if not isinstance(status, int) or isinstance(status, bool) or status not in REFUSAL_STATUSES:
        yield f"{code}: status {json.dumps(status)} is not a refusal's status"
    if not isinstance(description, str) or not description.strip():
        yield f"{code}: description {json.dumps(description)} is not a sentence"


def unread_fields(at: str, listed: Mapping[str, object], fields: tuple[str, ...]) -> list[str]:
    """Return a line naming every field `listed` carries that is not one of `fields`."""
    unread = sorted(set(listed) - set(fields))
    return [f"{at}: carries {', '.join(unread)}, which this generator does not read"] if unread else []


@dataclass(frozen=True)
class ByKey:
    """One action a key may call, as the contract lists it."""

    action: str
    disturbs: bool
    rehearsal: bool
    idempotent: bool
    moved: str | None = None


def read_by_key(at: int, entry: object) -> tuple[ByKey | None, list[str]]:
    """Return one action a key may call, or everything wrong with it as lines naming where it sits."""
    listed = object_of(entry)
    if listed is None:
        return None, [f"entry {at}: not an object"]
    action = listed.get("action")
    flags = [listed.get(one) for one in CALLABLE_FLAGS]
    moved = listed.get("moved")
    wrong: list[str] = []
    if not isinstance(action, str) or not ACTION.fullmatch(action):
        wrong.append(f"entry {at}: action {json.dumps(action)} is not an action's name")
    for flag, value in zip(CALLABLE_FLAGS, flags, strict=True):
        if not isinstance(value, bool):
            wrong.append(f"entry {at}: {flag} {json.dumps(value)} is not true or false")
    if moved is not None and (not isinstance(moved, str) or not CODE.fullmatch(moved)):
        wrong.append(f"entry {at}: moved {json.dumps(moved)} is not a code")
    wrong.extend(unread_fields(f"entry {at}", listed, CALLABLE_FIELDS))
    if wrong or not isinstance(action, str):
        return None, wrong
    disturbs, rehearsal, idempotent = (value is True for value in flags)
    return ByKey(action, disturbs, rehearsal, idempotent, moved if isinstance(moved, str) else None), []


@dataclass(frozen=True)
class Parameter:
    """One query parameter a read takes, as the contract lists it."""

    name: str
    repeatable: bool


@dataclass(frozen=True)
class Served:
    """One read the web API serves, as the contract lists it."""

    path: str
    parameters: tuple[Parameter, ...]
    kinds: tuple[str, ...]
    file: bool


def read_parameters(at: str, node: object) -> tuple[tuple[Parameter, ...], list[str]]:
    """Return a read's query parameters, and everything wrong with them as lines naming where each sits."""
    entries = array_of(node)
    if entries is None:
        return (), [f"{at}: parameters {json.dumps(node)} is not a list"]
    read: list[Parameter] = []
    wrong: list[str] = []
    for place, entry in enumerate(entries):
        here = f"{at}: parameter {place}"
        listed = object_of(entry)
        if listed is None:
            wrong.append(f"{here}: not an object")
            continue
        name = listed.get("name")
        repeatable = listed.get("repeatable")
        if not isinstance(name, str) or not PARAMETER.fullmatch(name):
            wrong.append(f"{here}: name {json.dumps(name)} is not a query parameter's name")
        elif name in {one.name for one in read}:
            wrong.append(f"{here}: {name} is listed twice")
        if not isinstance(repeatable, bool):
            wrong.append(f"{here}: repeatable {json.dumps(repeatable)} is not true or false")
        wrong.extend(unread_fields(here, listed, PARAMETER_FIELDS))
        if isinstance(name, str) and isinstance(repeatable, bool):
            read.append(Parameter(name, repeatable))
    return tuple(read), wrong


def read_served(at: int, entry: object, kinds: frozenset[str]) -> tuple[Served | None, list[str]]:
    """Return one read the web API serves, or everything wrong with it as lines naming where it sits."""
    here = f"entry {at}"
    listed = object_of(entry)
    if listed is None:
        return None, [f"{here}: not an object"]
    path = listed.get("path")
    answers = array_of(listed.get("kinds"))
    file = listed.get("file")
    parameters, wrong = read_parameters(here, listed.get("parameters"))
    if not isinstance(path, str) or not READ_PATH.fullmatch(path):
        wrong.append(f"{here}: path {json.dumps(path)} is not a read's path")
    if answers is None or not all(isinstance(kind, str) for kind in answers):
        wrong.append(f"{here}: kinds {json.dumps(listed.get('kinds'))} is not a list of kinds")
        answers = []
    wrong.extend(
        f"{here}: answers with {kind}, which the contract describes no kind as"
        for kind in answers
        if kind not in kinds
    )
    if not isinstance(file, bool):
        wrong.append(f"{here}: file {json.dumps(file)} is not true or false")
    elif not file and not answers:
        wrong.append(f"{here}: answers with neither a kind nor a file")
    elif not file and isinstance(path, str) and "{" in path:
        wrong.append(
            f"{here}: takes part of {path} as a value, and this generator writes only a file read so",
        )
    wrong.extend(unread_fields(here, listed, READ_FIELDS))
    if wrong or not isinstance(path, str):
        return None, wrong
    return Served(path, parameters, tuple(str(kind) for kind in answers), file is True), []


def checked(artefact: Mapping[str, object], stamp: str) -> None:
    """Refuse a stamp that names no revision, a version this package does not speak, and an ambiguous shape."""
    if stamp != UNKNOWN and not REVISION.fullmatch(stamp):
        refuse(f"{STAMP} names {json.dumps(stamp)}, which is not a release tag or a full commit hash")
    version = artefact.get("api_version")
    if version != SPOKEN:
        refuse(
            f"the vendored contract is api_version {json.dumps(version)}, and this package implements "
            f"{SPOKEN}. Sync a matching release, or implement the newer version first.",
        )
    found = list(ambiguous(kinds_of(artefact), ""))
    if found:
        refuse(
            "the vendored contract puts a constraint beside a reference, and generating would drop "
            "one of the two:\n  " + "\n  ".join(found),
        )


def kinds_of(artefact: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return the artefact's kinds, refusing an artefact describing none."""
    kinds = artefact.get("kinds")
    described = object_of(kinds)
    if not described:
        refuse("the vendored contract describes no kinds")
    spelled: dict[str, str] = {}
    for kind, schema in sorted(described.items()):
        if not KIND.fullmatch(kind):
            refuse(f"the kind {json.dumps(kind)} is not lowercase letters, digits, hyphens and underscores")
        if not isinstance(schema, dict):
            refuse(f"the kind `{kind}` is {json.dumps(schema)}, which is not an envelope's schema")
        name = f"{pascal(kind)}Envelope"
        if name in spelled:
            refuse(f"the kinds `{spelled[name]}` and `{kind}` would both be written as `{name}`")
        spelled[name] = kind
    return as_maps(described)


def users_of(kinds: Mapping[str, Mapping[str, object]]) -> dict[str, frozenset[str]]:
    """Return each definition's name, to every kind whose definitions carry it."""
    users: dict[str, set[str]] = {}
    for kind, schema in kinds.items():
        for name in as_map(schema.get("$defs", {})):
            users.setdefault(name, set()).add(kind)
    return {name: frozenset(carriers) for name, carriers in users.items()}


def refusals_of(artefact: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return the listed refusals, or none for an artefact older than the list."""
    listed = artefact.get("refusals", {})
    refusals = object_of(listed)
    if refusals is None:
        refuse(
            f"the vendored contract's refusals are {json.dumps(listed)}, and they are an object keyed by code",
        )
    problems = [line for code in sorted(refusals) for line in malformed_refusal(code, refusals[code])]
    named: dict[str, str] = {}
    if not problems:
        for code in sorted(refusals):
            name = str(as_map(refusals[code])["name"])
            if name in named:
                problems.append(f"{code}: name {name} is also the name of {named[name]}")
            named[name] = code
    if problems:
        refuse(
            "the vendored contract lists a refusal this generator cannot write:\n  " + "\n  ".join(problems),
        )
    return as_maps(refusals)


def key_callable_of(artefact: Mapping[str, object]) -> list[ByKey]:
    """Return the actions a key may call, in the contract's order, or none for an artefact older than the list."""
    listed = artefact.get("key_callable", [])
    entries = array_of(listed)
    if entries is None:
        refuse(f"the vendored contract's key_callable is {json.dumps(listed)}, and it is a list of actions")
    listed_refusals = object_of(artefact.get("refusals", {})) or {}
    read: list[ByKey] = []
    problems: list[str] = []
    seen: set[str] = set()
    for at, entry in enumerate(entries):
        one, wrong = read_by_key(at, entry)
        problems.extend(wrong)
        if one is None:
            continue
        if one.action in seen:
            problems.append(f"entry {at}: {one.action} is listed twice")
        if one.moved is not None and one.moved not in listed_refusals:
            problems.append(f"entry {at}: moved {one.moved} is not a refusal the contract lists")
        seen.add(one.action)
        read.append(one)
    if problems:
        refuse(
            "the vendored contract lists an action a key may call that this generator cannot write:\n  "
            + "\n  ".join(problems),
        )
    return read


def reads_of(artefact: Mapping[str, object]) -> list[Served]:
    """Return the reads the web API serves, in the contract's order, or none for an artefact older than the list."""
    listed = artefact.get("reads", [])
    entries = array_of(listed)
    if entries is None:
        refuse(f"the vendored contract's reads are {json.dumps(listed)}, and they are a list of reads")
    kinds = frozenset(kinds_of(artefact))
    read: list[Served] = []
    problems: list[str] = []
    for at, entry in enumerate(entries):
        one, wrong = read_served(at, entry, kinds)
        problems.extend(wrong)
        if one is None:
            continue
        if one.path in {served.path for served in read}:
            problems.append(f"entry {at}: {one.path} is listed twice")
        read.append(one)
    if problems:
        refuse("the vendored contract lists a read this generator cannot write:\n  " + "\n  ".join(problems))
    return read
